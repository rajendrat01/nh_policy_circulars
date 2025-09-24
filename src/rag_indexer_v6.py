#!/usr/bin/env python3
"""
NHAI RAG Indexer v6
- FINAL, ROBUST INDEXER.
- Solves memory leaks by running the indexing process in a loop, with each
  loop being a separate, memory-isolated run processing a small batch of documents.
- Self-contained: no external runner script needed.
- Can be stopped and restarted at any time, picking up where it left off.
- Uses a lightweight log file for deduplication to avoid high memory usage on startup.
"""
import os
import json
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv
import hashlib
import time

from langchain.text_splitter import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

# Whoosh integration for hybrid search
from whoosh_indexer import build_whoosh_index, bm25_search

load_dotenv()


class NHAIRAGIndexerV6:

    def __init__(self, embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        self.vector_db_path = "output/chroma_db_v4" # Keep same DB as v4
        self.indexed_hashes_path = "output/indexed_hashes.log"
        os.makedirs(self.vector_db_path, exist_ok=True)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        )
        print(f"✓ RAG Indexer v6 initialized with model: {embedding_model}")

    def create_document_chunks(self, content: str, metadata: Dict) -> List[Document]:
        if not content.strip(): return []
        header_sections = self.header_splitter.split_text(content)
        if not header_sections:
            from langchain.schema import Document as LangchainDocument
            header_sections = [LangchainDocument(page_content=content, metadata={})]
        documents = []
        for section_doc in header_sections:
            section_text = section_doc.page_content
            section_metadata = metadata.copy()
            if section_doc.metadata: section_metadata.update(section_doc.metadata)
            text_chunks = self.text_splitter.split_text(section_text)
            for i, chunk in enumerate(text_chunks):
                doc_metadata = section_metadata.copy()
                chunk_hash = self._get_content_hash(chunk)
                header_id_parts = [str(doc_metadata.get(h, '')) for h in ['h1', 'h2', 'h3'] if doc_metadata.get(h)]
                header_id = "_".join(header_id_parts).replace(" ", "_") or "no_header"
                # The content_hash is the unique identifier for a chunk's content
                doc_metadata.update({
                    'chunk_id': f"{metadata.get('policy_no', 'N/A')}_{header_id}_{i}",
                    'content_hash': chunk_hash,
                })
                doc = Document(page_content=chunk, metadata=doc_metadata)
                documents.append(doc)
        return documents

    def _get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _load_indexed_docs(self) -> set:
        indexed = set()
        # Strategy: Prefer the fast log file. If it doesn't exist, create it once from the slow DB query.
        if os.path.exists(self.indexed_hashes_path):
            print(f"Loading indexed document hashes from {self.indexed_hashes_path}")
            with open(self.indexed_hashes_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line: indexed.add(line)
            print(f"Found {len(indexed)} already indexed document versions from log file.")
            return indexed

        print("Indexed hashes log not found. Performing one-time migration from ChromaDB...")
        print("This may take a while and use significant memory...")
        try:
            vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
            existing_docs = vectorstore.get(include=["metadatas"])
            if existing_docs and existing_docs.get('metadatas'):
                with open(self.indexed_hashes_path, 'w') as f:
                    for meta in existing_docs['metadatas']:
                        # Use content_hash as the unique key, as policy_no can be duplicated for different content versions
                        content_hash = meta.get('content_hash')
                        if content_hash:
                            indexed.add(content_hash)
                            f.write(content_hash + '\n')
            print(f"Migration complete. Found and saved {len(indexed)} unique content hashes.")
            return indexed
        except Exception as e:
            print(f"Could not load existing documents from ChromaDB for migration: {e}")
            print("Assuming new index.")
            return set()

    def _persist_document_hashes(self, documents: List[Document]):
        try:
            with open(self.indexed_hashes_path, 'a') as f:
                for doc in documents:
                    content_hash = doc.metadata.get('content_hash')
                    if content_hash:
                        f.write(content_hash + '\n')
        except Exception as e:
            print(f"Warning: Could not write to indexed hashes log: {e}")

    def index_circulars(self, input_file: str, chunk_batch_size: int = 250, process_limit: int = 100) -> Dict:
        stats = {'total_in_file': 0, 'processed_this_run': 0, 'skipped': 0, 'failed': 0, 'chunks_added': 0}
        
        # Load the lightweight set of hashes first.
        indexed_content_hashes = self._load_indexed_docs()
        
        # Only initialize ChromaDB after the memory-light part is done.
        vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
        docs_to_add = []

        print(f"Starting indexing run. Processing up to {process_limit} new documents.")
        
        with open(input_file, 'r', encoding='utf-8') as f_in:
            for i, line in enumerate(f_in):
                stats['total_in_file'] += 1
                if stats['processed_this_run'] >= process_limit:
                    print(f"Process limit of {process_limit} reached for this run. Stopping.")
                    break
                line = line.strip();
                if not line: continue
                try:
                    circular = json.loads(line)
                except json.JSONDecodeError:
                    stats['failed'] += 1; continue

                content = circular.get('content', '')
                if not content.strip(): stats['failed'] += 1; continue
                
                metadata = dict(circular)
                for k, v in list(metadata.items()):
                    if isinstance(v, list): metadata[k] = ' > '.join(str(x) for x in v)

                documents = self.create_document_chunks(content, metadata)
                
                # Deduplication happens here, before adding to the batch
                new_documents = []
                for doc in documents:
                    if doc.metadata['content_hash'] not in indexed_content_hashes:
                        new_documents.append(doc)
                    else:
                        stats['skipped'] += 1
                
                if new_documents:
                    stats['processed_this_run'] += 1 # A circular is "processed" if it has at least one new chunk
                
                for doc in new_documents:
                    docs_to_add.append(doc)
                    if len(docs_to_add) >= chunk_batch_size:
                        print(f"\n[Batch] At circular ~{i+1}. Processing batch of {len(docs_to_add)} chunks.")
                        vectorstore.add_documents(docs_to_add)
                        self._persist_document_hashes(docs_to_add)
                        stats['chunks_added'] += len(docs_to_add)
                        # Add newly indexed hashes to the set to avoid re-adding in the same run
                        for d in docs_to_add: indexed_content_hashes.add(d.metadata['content_hash'])
                        print(f"  > Batch added successfully.")
                        docs_to_add = []
        
        if docs_to_add:
            print(f"\n[Batch] Processing final batch of {len(docs_to_add)} chunks for this run.")
            vectorstore.add_documents(docs_to_add)
            self._persist_document_hashes(docs_to_add)
            stats['chunks_added'] += len(docs_to_add)
            print(f"  > Final batch added successfully.")

        try:
            if stats['chunks_added'] > 0:
                print("Rebuilding Whoosh keyword index...")
                # Re-fetch all docs to ensure Whoosh index is complete
                all_docs = vectorstore.get(include=["metadatas", "documents"])
                docs_to_index = [Document(page_content=doc, metadata=meta) for doc, meta in zip(all_docs['documents'], all_docs['metadatas'])]
                if docs_to_index: build_whoosh_index(docs_to_index)
        except Exception as e:
            print(f"Warning: Could not build Whoosh index: {e}")

        print(f"\nIndexing run complete. Processed this run: {stats['processed_this_run']}.")
        return stats

    def search_circulars(self, query: str, k: int = 5) -> List[Dict]:
        vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
        vector_results = vectorstore.similarity_search_with_score(query, k=k)
        return [{'content': doc.page_content, 'metadata': doc.metadata, 'score': score} for doc, score in vector_results]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer v6 - Robust, looping indexer")
    parser.add_argument('action', choices=['index', 'search'], help='Action to perform')
    parser.add_argument('--input', type=str, default="output/circulars_with_text.jsonl")
    parser.add_argument('--query', '-q', type=str, help='Search query')
    args = parser.parse_args()

    if args.action == 'search':
        indexer = NHAIRAGIndexerV6()
        results = indexer.search_circulars(args.query)
        for res in results: print(res)
        return

    # --- Robust Indexing Loop ---
    print("Starting robust indexing process...")
    run_count = 0
    while True:
        run_count += 1
        print("----------------------------------------------------")
        print(f"Starting indexing RUN #{run_count} at {datetime.now().isoformat()}")
        
        # Each loop creates a new indexer instance to ensure memory is cleared
        indexer = NHAIRAGIndexerV6()
        stats = indexer.index_circulars(args.input)
        
        if stats['processed_this_run'] == 0:
            print("\nSUCCESS: No new documents were processed in the last run.")
            print("The index is now fully up-to-date.")
            break
        
        print(f"Run #{run_count} complete. Waiting 5 seconds before next run...")
        time.sleep(5)
    
    print("----------------------------------------------------")
    print("Robust indexing process finished.")


if __name__ == "__main__":
    main()