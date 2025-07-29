#!/usr/bin/env python3
"""
Simple Query Interface for NHAI Circular RAG System
Provides an easy-to-use interface for searching indexed circulars
"""

import sys
import os

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from rag_indexer import NHAIRAGIndexer
except ImportError as e:
    print("Error: RAG dependencies not installed.")
    print("Install with: pip install -r requirements-rag.txt")
    print(f"Details: {e}")
    sys.exit(1)

def interactive_search():
    """Interactive search interface"""
    print("NHAI Circular RAG Search")
    print("=" * 40)
    
    # Initialize indexer
    try:
        indexer = NHAIRAGIndexer()
        
        # Check if database exists
        if not os.path.exists("output/chroma_db"):
            print("❌ Vector database not found.")
            print("Please run indexing first:")
            print("python src/rag_indexer.py index")
            return
        
        # Get stats
        stats = indexer.get_indexing_stats()
        print(f"📊 Database contains {stats.get('total_chunks', 0)} chunks from {stats.get('unique_policies', 0)} policies")
        print()
        
    except Exception as e:
        print(f"❌ Error initializing indexer: {e}")
        return
    
    while True:
        try:
            # Get user query
            query = input("\n🔍 Enter your search query (or 'quit' to exit): ").strip()
            
            if not query or query.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            
            # Perform search
            print(f"\n🔎 Searching for: '{query}'...")
            results = indexer.search_circulars(query, k=5)
            
            if not results:
                print("❌ No results found. Try a different query.")
                continue
            
            # Display results
            print(f"\n📋 Found {len(results)} relevant results:")
            print("=" * 80)
            
            for i, result in enumerate(results, 1):
                print(f"\n{i}. 📄 {result['subject']}")
                print(f"   📋 Policy No: {result['policy_no']}")
                print(f"   📅 Date: {result['date']}")
                print(f"   🔗 URL: {result['url']}")
                
                if result['used_ocr']:
                    print("   📷 OCR: Used (scanned document)")
                else:
                    print("   📝 OCR: Not needed (text-based)")
                
                # Show content preview
                content_preview = result['content'][:300]
                if len(result['content']) > 300:
                    content_preview += "..."
                print(f"   📖 Content: {content_preview}")
                print("-" * 80)
            
            # Ask if user wants to see more details
            while True:
                choice = input("\n📋 Enter result number for full content (or press Enter to search again): ").strip()
                
                if not choice:
                    break
                
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(results):
                        result = results[idx]
                        print(f"\n📄 Full Content - {result['subject']}")
                        print("=" * 80)
                        print(result['content'])
                        print("=" * 80)
                    else:
                        print("❌ Invalid result number.")
                except ValueError:
                    print("❌ Please enter a valid number.")
                
        except KeyboardInterrupt:
            print("\n\n👋 Search interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error during search: {e}")

def main():
    """Main function"""
    if len(sys.argv) > 1:
        # Command line query
        query = " ".join(sys.argv[1:])
        
        try:
            indexer = NHAIRAGIndexer()
            
            if not os.path.exists("output/chroma_db"):
                print("❌ Vector database not found. Run indexing first:")
                print("python src/rag_indexer.py index")
                return
            
            print(f"🔎 Searching for: '{query}'")
            results = indexer.search_circulars(query, k=5)
            
            if not results:
                print("❌ No results found.")
                return
            
            print(f"\n📋 Found {len(results)} results:")
            for i, result in enumerate(results, 1):
                print(f"\n{i}. {result['subject']} ({result['policy_no']})")
                print(f"   📅 {result['date']} | OCR: {'Yes' if result['used_ocr'] else 'No'}")
                print(f"   📖 {result['content'][:200]}...")
                
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        # Interactive mode
        interactive_search()

if __name__ == "__main__":
    main()
