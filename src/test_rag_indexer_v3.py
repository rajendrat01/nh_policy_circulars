import sys
import os
from rag_indexer_v3 import NHAIRAGIndexerV3

def test_index_and_search():
    # Setup
    input_jsonl = "output/selenium_circulars.jsonl"
    if not os.path.exists(input_jsonl):
        print(f"Test failed: {input_jsonl} not found.")
        sys.exit(1)
    indexer = NHAIRAGIndexerV3()
    # Indexing
    circulars = indexer.load_circulars(input_jsonl)
    stats = indexer.index_circulars(circulars)
    print("Indexing stats:", stats)
    assert stats['total_circulars'] > 0, "No circulars loaded."
    # Search
    test_query = "toll plaza"
    results = indexer.search_circulars(test_query, k=3)
    print(f"Search results for query '{test_query}':")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['metadata'].get('subject','(no subject)')}")
        print(f"   Policy No: {result['metadata'].get('policy_no','')}")
        print(f"   Date: {result['metadata'].get('date','')}")
        print(f"   h1: {result['metadata'].get('h1','')}")
        print(f"   h2: {result['metadata'].get('h2','')}")
        print(f"   h3: {result['metadata'].get('h3','')}")
        print(f"   Content: {result['content'][:200]}...")
        print(f"   Hybrid Score: {result.get('hybrid_score','')}")
        print("-" * 80)
    assert len(results) > 0, "No search results returned."
    print("Test passed.")

if __name__ == "__main__":
    test_index_and_search()
