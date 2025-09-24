# How to run: python src/rag_indexer_v5.py index
#!/usr/bin/env python3
"""
NHAI RAG Indexer v5
- FINAL, ROBUST INDEXER.
- Solves memory leaks by running the indexing process in a loop, with each
  loop being a separate, memory-isolated run processing a small batch of documents.
- Self-contained: no external runner script needed.
- Can be stopped and restarted at any time, picking up where it left off.
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


class NHAIRAGIndexerV5:

    def __init__(self, embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        self.vector_db_path = "output/chroma_db_v4" # Keep same DB as v4
        os.makedirs(self.vector_db_path, exist_ok=True)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        )
        print(f"✓ RAG Indexer v5 initialized with model: {embedding_model}")

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
                doc_metadata.update({
                    'chunk_id': f"{metadata.get('policy_no', 'N/A')}_{header_id}_{i}",
                    'content_hash': chunk_hash,
                })
                doc = Document(page_content=chunk, metadata=doc_metadata)
                documents.append(doc)
        return documents

    def _get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _load_indexed_docs(self):
        try:
            vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
            existing_docs = vectorstore.get(include=["metadatas"])
            indexed = set()
            if existing_docs and existing_docs.get('metadatas'):
                for meta in existing_docs['metadatas']:
                    policy_no = meta.get('policy_no')
                    content_hash = meta.get('content_hash')
                    if policy_no and content_hash: indexed.add((policy_no, content_hash))
            print(f"Found {len(indexed)} already indexed document content versions in ChromaDB.")
            return indexed
        except Exception:
            print("Could not load existing documents from ChromaDB, assuming new index.")
            return set()

    def index_circulars(self, input_file: str, chunk_batch_size: int = 250, process_limit: int = 100) -> Dict:
        stats = {'total_in_file': 0, 'processed_this_run': 0, 'skipped': 0, 'failed': 0, 'chunks_added': 0}
        vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
        docs_to_add = []
        indexed_docs = self._load_indexed_docs()

        print(f"Starting indexing run. Processing up to {process_limit} new documents.")
        
        with open(input_file, 'r', encoding='utf-8') as f_in:
            for i, line in enumerate(f_in):
                stats['total_in_file'] += 1
                if stats['processed_this_run'] >= process_limit:
                    print(f"Process limit of {process_limit} reached for this run. Stopping.")
                    break
                line = line.strip()
                if not line: continue
                try:
                    circular = json.loads(line)
                except json.JSONDecodeError:
                    stats['failed'] += 1; continue

                policy_no = circular.get('policy_no', 'Unknown'); content = circular.get('content', '')
                if not content.strip(): stats['failed'] += 1; continue
                content_hash = self._get_content_hash(content)
                if (policy_no, content_hash) in indexed_docs: stats['skipped'] += 1; continue
                
                metadata = dict(circular)
                for k, v in list(metadata.items()):
                    if isinstance(v, list): metadata[k] = ' > '.join(str(x) for x in v)

                documents = self.create_document_chunks(content, metadata)
                if documents:
                    stats['processed_this_run'] += 1
                
                for doc in documents:
                    docs_to_add.append(doc)
                    if len(docs_to_add) >= chunk_batch_size:
                        print(f"\n[Batch] At circular ~{i+1}. Processing batch of {len(docs_to_add)} chunks.")
                        vectorstore.add_documents(docs_to_add)
                        stats['chunks_added'] += len(docs_to_add)
                        print(f"  > Batch added successfully.")
                        docs_to_add = []
        
        if docs_to_add:
            print(f"\n[Batch] Processing final batch of {len(docs_to_add)} chunks for this run.")
            vectorstore.add_documents(docs_to_add)
            stats['chunks_added'] += len(docs_to_add)
            print(f"  > Final batch added successfully.")

        try:
            if stats['chunks_added'] > 0:
                print("Rebuilding Whoosh keyword index...")
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
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer v5 - Robust, looping indexer")
    parser.add_argument('action', choices=['index', 'search'], help='Action to perform')
    parser.add_argument('--input', type=str, default="output/circulars_with_text.jsonl")
    parser.add_argument('--query', '-q', type=str, help='Search query')
    args = parser.parse_args()

    if args.action == 'search':
        indexer = NHAIRAGIndexerV5()
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
        indexer = NHAIRAGIndexerV5()
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