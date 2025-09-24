#!/usr/bin/env python3
"""
Test script for NHAI RAG Indexer v2
Indexes a small sample of circulars and performs a test search.
"""
import os
import json
from rag_indexer_v2 import NHAIRAGIndexerV2

def main():
    # Use a small sample for testing
    sample_jsonl = "output/selenium_circulars.jsonl"
    test_db_path = "output/chroma_db_v2_test"
    embedding_model = "all-MiniLM-L6-v2"

    # Read first 3 circulars from JSONL
    circulars = []
    with open(sample_jsonl, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= 3:
                break
            circulars.append(json.loads(line))
    print(f"Loaded {len(circulars)} circulars for test indexing.")

    # Initialize test indexer (use a separate DB path)
    indexer = NHAIRAGIndexerV2(embedding_model=embedding_model)
    indexer.vector_db_path = test_db_path
    os.makedirs(test_db_path, exist_ok=True)

    # Index the sample circulars
    stats = indexer.index_circulars(circulars, batch_size=1)
    print("Indexing stats:", stats)

    # Perform a test search
    query = "delegation of powers"
    print(f"\nTest search for: '{query}'")
    results = indexer.search_circulars(query, k=2)
    for i, result in enumerate(results, 1):
        print(f"\nResult {i}:")
        print(f"Subject: {result['metadata'].get('subject')}")
        print(f"Policy No: {result['metadata'].get('policy_no')}")
        print(f"Date: {result['metadata'].get('date')}")
        print(f"Content: {result['content'][:200]}...")
        print(f"Path: {result['metadata'].get('path')}")
        print(f"OCR Used: {result['metadata'].get('used_ocr')}")

if __name__ == "__main__":
    main()
