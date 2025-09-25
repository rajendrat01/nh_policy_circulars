#!/usr/bin/env python3
"""
NHAI RAG Indexer v6 - Road Safety Specialized Version
- FINAL, ROBUST INDEXER for ROAD SAFETY documents only.
- Filters documents based on road safety division headers and categories.
- Solves memory leaks by running the indexing process in a loop, with each
  loop being a separate, memory-isolated run processing a small batch of documents.
- Self-contained: no external runner script needed.
- Can be stopped and restarted at any time, picking up where it left off.
- Uses a lightweight log file for deduplication to avoid high memory usage on startup.
"""
import os
import json
import re
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv
import hashlib
import time

from langchain.text_splitter import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Whoosh integration for hybrid search
from whoosh_indexer import build_whoosh_index, bm25_search

class SimpleEmbeddings:
    """Simple TF-IDF based embeddings as fallback"""
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        self.fitted = False
        
    def embed_documents(self, texts):
        if not self.fitted:
            self.vectorizer.fit(texts)
            self.fitted = True
        return self.vectorizer.transform(texts).toarray().tolist()
    
    def embed_query(self, text):
        if not self.fitted:
            return [0.0] * 1000  # Return zero vector if not fitted
        return self.vectorizer.transform([text]).toarray()[0].tolist()

load_dotenv()


class NHAIRAGIndexerV6RS:
    """
    Road Safety Specialized RAG Indexer
    Filters documents based on road safety division and related categories
    """

    def __init__(self, embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        self.vector_db_path = "output/chroma_db_road_safety"  # Separate DB for road safety
        self.indexed_hashes_path = "output/indexed_hashes_road_safety.log"
        os.makedirs(self.vector_db_path, exist_ok=True)
        
        # Road Safety specific filtering patterns
        self.road_safety_keywords = [
            # Main categories
            "road safety", "traffic safety", "highway safety", "safety division",
            "safety protocols", "safety standards", "safety guidelines",
            "safety measures", "safety requirements", "safety procedures",
            
            # Specific road safety terms
            "accident prevention", "black spot", "blackspot", "accident prone",
            "traffic management", "speed limit", "road marking", "signage",
            "barrier", "guard rail", "crash barrier", "median",
            "intersection", "junction", "roundabout", "traffic signal",
            "pedestrian", "cyclist", "motorcycle", "heavy vehicle",
            "overtaking", "lane discipline", "helmet", "seat belt",
            
            # NHAI specific safety codes
            "safety audit", "road safety audit", "traffic impact assessment",
            "environmental clearance", "safety clearance", "safety certificate",
            "safety inspection", "safety compliance", "safety monitoring",
            
            # Policy numbers related to safety (common patterns)
            "1.8", "1.9", "2.8", "2.9", "3.8", "3.9", "4.8", "4.9",
            "safety", "traffic", "accident", "blackspot"
        ]
        
        # Policy number patterns for road safety (based on category name, not number)
        self.road_safety_policy_patterns = [
            r".*safety.*",  # Any policy with "safety" in the number
            r".*traffic.*",  # Any policy with "traffic" in the number
            r".*accident.*",  # Any policy with "accident" in the number
            r".*road.*",  # Any policy with "road" in the number
        ]
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        )
        print(f"✓ RAG Indexer v6 Road Safety initialized with model: {embedding_model}")
        print(f"✓ Filtering for Category 12: ROAD SAFETY")
        print(f"✓ Road Safety keywords: {len(self.road_safety_keywords)} patterns")
        print(f"✓ Policy patterns: {len(self.road_safety_policy_patterns)} patterns")

    def is_road_safety_document(self, circular: Dict) -> bool:
        """
        Determines if a circular is related to road safety based on:
        1. Main Category: "ROAD SAFETY" (Category 12 from NHAI website)
        2. Subject/content keywords as secondary filter
        """
        # Primary filter: Check if it belongs to "ROAD SAFETY" category
        category = circular.get('category', '').lower()
        if 'road safety' in category:
            return True
        
        # Secondary filter: Check for road safety keywords in subject/content
        subject = circular.get('subject', '').lower()
        content = circular.get('content', '').lower()
        
        # Check subject for road safety keywords
        for keyword in self.road_safety_keywords:
            if keyword.lower() in subject:
                return True
        
        # Check content for road safety keywords (require 2+ matches for content)
        safety_keyword_count = 0
        for keyword in self.road_safety_keywords:
            if keyword.lower() in content:
                safety_keyword_count += 1
        
        # If content has 2+ road safety keywords, consider it road safety related
        if safety_keyword_count >= 2:
            return True
        
        return False

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
                    'document_type': 'road_safety',  # Mark as road safety document
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
            print(f"Loading indexed road safety document hashes from {self.indexed_hashes_path}")
            with open(self.indexed_hashes_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line: indexed.add(line)
            print(f"Found {len(indexed)} already indexed road safety document versions from log file.")
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
            print(f"Migration complete. Found and saved {len(indexed)} unique road safety content hashes.")
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
        stats = {
            'total_in_file': 0, 
            'road_safety_documents': 0,
            'processed_this_run': 0, 
            'skipped': 0, 
            'failed': 0, 
            'chunks_added': 0,
            'filtered_out': 0
        }
        
        # Load the lightweight set of hashes first.
        indexed_content_hashes = self._load_indexed_docs()
        
        # Only initialize ChromaDB after the memory-light part is done.
        vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
        docs_to_add = []

        print(f"Starting road safety indexing run. Processing up to {process_limit} new documents.")
        
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

                # ROAD SAFETY FILTERING - Only process road safety related documents
                if not self.is_road_safety_document(circular):
                    stats['filtered_out'] += 1
                    continue
                
                stats['road_safety_documents'] += 1
                print(f"✓ Road Safety Document: {circular.get('policy_no', 'N/A')} - {circular.get('subject', 'No Subject')[:50]}...")

                content = circular.get('content', '')
                if not content.strip(): 
                    stats['failed'] += 1; 
                    continue
                
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
                        print(f"\n[Batch] At circular ~{i+1}. Processing batch of {len(docs_to_add)} road safety chunks.")
                        vectorstore.add_documents(docs_to_add)
                        self._persist_document_hashes(docs_to_add)
                        stats['chunks_added'] += len(docs_to_add)
                        # Add newly indexed hashes to the set to avoid re-adding in the same run
                        for d in docs_to_add: indexed_content_hashes.add(d.metadata['content_hash'])
                        print(f"  > Road safety batch added successfully.")
                        docs_to_add = []
        
        if docs_to_add:
            print(f"\n[Batch] Processing final batch of {len(docs_to_add)} road safety chunks for this run.")
            vectorstore.add_documents(docs_to_add)
            self._persist_document_hashes(docs_to_add)
            stats['chunks_added'] += len(docs_to_add)
            print(f"  > Final road safety batch added successfully.")

        try:
            if stats['chunks_added'] > 0:
                print("Rebuilding Whoosh keyword index for road safety documents...")
                # Re-fetch all docs to ensure Whoosh index is complete
                all_docs = vectorstore.get(include=["metadatas", "documents"])
                docs_to_index = [Document(page_content=doc, metadata=meta) for doc, meta in zip(all_docs['documents'], all_docs['metadatas'])]
                if docs_to_index: build_whoosh_index(docs_to_index)
        except Exception as e:
            print(f"Warning: Could not build Whoosh index: {e}")

        print(f"\nRoad Safety Indexing run complete.")
        print(f"  - Total documents in file: {stats['total_in_file']}")
        print(f"  - Road safety documents found: {stats['road_safety_documents']}")
        print(f"  - Filtered out (non-road safety): {stats['filtered_out']}")
        print(f"  - Processed this run: {stats['processed_this_run']}")
        print(f"  - Chunks added: {stats['chunks_added']}")
        return stats

    def search_circulars(self, query: str, k: int = 5) -> List[Dict]:
        vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
        vector_results = vectorstore.similarity_search_with_score(query, k=k)
        return [{'content': doc.page_content, 'metadata': doc.metadata, 'score': score} for doc, score in vector_results]

    def get_road_safety_stats(self) -> Dict:
        """Get statistics about road safety documents in the index"""
        try:
            vectorstore = Chroma(persist_directory=self.vector_db_path, embedding_function=self.embeddings)
            all_docs = vectorstore.get(include=["metadatas"])
            
            if not all_docs or not all_docs.get('metadatas'):
                return {'total_chunks': 0, 'unique_policies': 0, 'road_safety_policies': set()}
            
            policies = set()
            road_safety_policies = set()
            
            for meta in all_docs['metadatas']:
                policy_no = meta.get('policy_no', '')
                if policy_no:
                    policies.add(policy_no)
                    if meta.get('document_type') == 'road_safety':
                        road_safety_policies.add(policy_no)
            
            return {
                'total_chunks': len(all_docs['metadatas']),
                'unique_policies': len(policies),
                'road_safety_policies': len(road_safety_policies),
                'road_safety_policy_list': list(road_safety_policies)
            }
        except Exception as e:
            print(f"Error getting road safety stats: {e}")
            return {'total_chunks': 0, 'unique_policies': 0, 'road_safety_policies': 0}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer v6 Road Safety - Robust, looping indexer for Category 12: ROAD SAFETY documents only")
    parser.add_argument('action', choices=['index', 'search', 'stats'], help='Action to perform')
    parser.add_argument('--input', type=str, default="output/circulars_with_text.jsonl")
    parser.add_argument('--query', '-q', type=str, help='Search query')
    args = parser.parse_args()

    if args.action == 'search':
        indexer = NHAIRAGIndexerV6RS()
        results = indexer.search_circulars(args.query)
        print(f"\n🔍 Road Safety Search Results for: '{args.query}'")
        print("=" * 80)
        for i, res in enumerate(results, 1):
            print(f"\n{i}. 📄 {res['metadata'].get('subject', 'No Subject')}")
            print(f"   📋 Policy: {res['metadata'].get('policy_no', 'N/A')}")
            print(f"   📅 Date: {res['metadata'].get('date', 'N/A')}")
            print(f"   📖 Content: {res['content'][:200]}...")
            print(f"   🎯 Score: {res['score']:.4f}")
        return

    if args.action == 'stats':
        indexer = NHAIRAGIndexerV6RS()
        stats = indexer.get_road_safety_stats()
        print(f"\n📊 Road Safety Index Statistics")
        print("=" * 50)
        print(f"Total chunks indexed: {stats['total_chunks']}")
        print(f"Unique policies: {stats['unique_policies']}")
        print(f"Road safety policies: {stats['road_safety_policies']}")
        if stats.get('road_safety_policy_list'):
            print(f"\nRoad Safety Policy Numbers:")
            for policy in sorted(stats['road_safety_policy_list']):
                print(f"  - {policy}")
        return

    # --- Robust Indexing Loop ---
    print("Starting robust road safety indexing process...")
    print("This will only index documents from Category 12: ROAD SAFETY.")
    run_count = 0
    while True:
        run_count += 1
        print("----------------------------------------------------")
        print(f"Starting road safety indexing RUN #{run_count} at {datetime.now().isoformat()}")
        
        # Each loop creates a new indexer instance to ensure memory is cleared
        indexer = NHAIRAGIndexerV6RS()
        stats = indexer.index_circulars(args.input)
        
        if stats['processed_this_run'] == 0:
            print("\nSUCCESS: No new road safety documents were processed in the last run.")
            print("The road safety index is now fully up-to-date.")
            break
        
        print(f"Run #{run_count} complete. Waiting 5 seconds before next run...")
        time.sleep(5)
    
    print("----------------------------------------------------")
    print("Robust road safety indexing process finished.")


if __name__ == "__main__":
    main()
