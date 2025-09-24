"""
Query the NHAI Circulars RAG Index.

This script provides a command-line interface to query the hybrid search index
built by the rag_indexer. It combines results from both semantic (ChromaDB)
and keyword (Whoosh) search to provide a comprehensive set of results.

This file is also designed to be used as a module by other applications (e.g., Chainlit).
"""

import argparse
import os
import sys
from pprint import pprint

# Ensure the 'src' directory is in the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from whoosh.index import open_dir
    from whoosh.qparser import QueryParser, OrGroup
except ImportError:
    print("Error: Required libraries are not installed.")
    print("Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# --- Configuration ---
VECTOR_DB_PATH = "output/chroma_db_v4"
WHOOSH_INDEX_PATH = "output/whoosh_index"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_TOP_K = 3

class NHAISearch:
    """A class to handle querying the NHAI RAG index."""

    def __init__(self, vector_db_path, whoosh_index_path, embedding_model):
        """
        Initializes the search interface by loading the indexes and models.
        """
        print("Initializing NHAI Search Engine...")
        if not os.path.exists(vector_db_path) or not os.path.exists(whoosh_index_path):
            print(f"Error: Index paths not found.")
            print(f"  - Searched for ChromaDB at: {vector_db_path}")
            print(f"  - Searched for Whoosh at: {whoosh_index_path}")
            print("Please run the indexing script first (e.g., rag_indexer_v6.py).")
            sys.exit(1)

        print(f"✓ Loading embedding model: {embedding_model}")
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        
        print(f"✓ Loading Chroma vector store from: {vector_db_path}")
        self.vectorstore = Chroma(persist_directory=vector_db_path, embedding_function=self.embeddings)
        
        print(f"✓ Loading Whoosh keyword index from: {whoosh_index_path}")
        self.whoosh_index = open_dir(whoosh_index_path)
        self.whoosh_searcher = self.whoosh_index.searcher()
        self.whoosh_parser = QueryParser("content", self.whoosh_index.schema, group=OrGroup)
        
        print("✅ Search Engine Ready.\n")

    def search(self, query, top_k=DEFAULT_TOP_K):
        """
        Performs a hybrid search and returns a ranked list of results.
        """
        # 1. Semantic Search (ChromaDB)
        vector_results = self.vectorstore.similarity_search_with_score(query, k=top_k)

        # 2. Keyword Search (Whoosh)
        parsed_query = self.whoosh_parser.parse(query)
        keyword_hits = self.whoosh_searcher.search(parsed_query, limit=top_k)

        # 3. Combine and Rank Results
        combined_results = {}

        # Add vector results
        for doc, score in vector_results:
            policy_no = doc.metadata.get("policy_no", "N/A")
            if policy_no not in combined_results:
                combined_results[policy_no] = {
                    "metadata": doc.metadata,
                    "content_snippet": doc.page_content[:500] + "...",
                    "sources": {"semantic"},
                    "score": 1.0 - score  # Higher is better
                }

        # Add keyword results
        for hit in keyword_hits:
            policy_no = hit.get("policy_no", "N/A")
            if policy_no in combined_results:
                combined_results[policy_no]["sources"].add("keyword")
                combined_results[policy_no]["score"] += hit.score # Boost score
            else:
                combined_results[policy_no] = {
                    "metadata": dict(hit),
                    "content_snippet": hit.get("content", "")[:500] + "...",
                    "sources": {"keyword"},
                    "score": hit.score
                }
        
        # Sort by final score
        sorted_results = sorted(combined_results.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results

def main():
    """Main function to handle command-line arguments and run the search."""
    parser = argparse.ArgumentParser(description="Query the NHAI Circulars knowledge base.")
    parser.add_argument("query", type=str, help="The search query.")
    parser.add_argument("--top_k", type=int, default=DEFAULT_TOP_K, help="Number of results to return.")
    args = parser.parse_args()

    search_engine = NHAISearch(VECTOR_DB_PATH, WHOOSH_INDEX_PATH, EMBEDDING_MODEL)
    results = search_engine.search(args.query, top_k=args.top_k)
    pprint(results)

if __name__ == "__main__":
    main()