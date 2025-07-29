#!/usr/bin/env python3
"""
Quick test of RAG system with a small sample
"""
import sys
import os
import json
sys.path.append('src')

from rag_indexer import NHAIRAGIndexer

def test_small_sample():
    """Test with just the first 3 circulars"""
    
    # Load circulars
    with open('output/existing_links.json', 'r') as f:
        all_circulars = json.load(f)
    
    # Take just the first 3 for testing
    test_circulars = all_circulars[:3]
    
    print(f"Testing RAG system with {len(test_circulars)} circulars...")
    
    # Initialize indexer
    indexer = NHAIRAGIndexer()
    
    # Index the test circulars
    print("\n" + "="*50)
    print("STARTING INDEXING TEST")
    print("="*50)
    
    stats = indexer.index_circulars(test_circulars)
    
    print("\n" + "="*50)
    print("INDEXING COMPLETED")
    print("="*50)
    print(f"Processed: {stats['processed']}/{stats['total_circulars']}")
    print(f"Failed: {stats['failed']}")
    print(f"Used OCR: {stats['used_ocr']}")
    print(f"Total chunks: {stats['total_chunks']}")
    
    if stats['processed'] > 0:
        print("\n" + "="*50)
        print("TESTING SEARCH")
        print("="*50)
        
        # Test search
        test_queries = ["highway", "policy", "construction", "maintenance"]
        
        for query in test_queries:
            print(f"\n🔍 Searching for: '{query}'")
            results = indexer.search_circulars(query, k=2)
            
            if results:
                print(f"✅ Found {len(results)} results")
                for i, result in enumerate(results, 1):
                    print(f"  {i}. {result['policy_no']} - {result['subject'][:50]}...")
            else:
                print("❌ No results")
    
    return stats['processed'] > 0

if __name__ == "__main__":
    success = test_small_sample()
    if success:
        print("\n🎉 RAG system test completed successfully!")
        print("You can now use:")
        print("- python src/rag_indexer.py search --query 'your search'")
        print("- python query_circulars.py 'your search'")
        print("- python query_circulars.py  # for interactive mode")
    else:
        print("\n❌ Test failed. Check the errors above.")
