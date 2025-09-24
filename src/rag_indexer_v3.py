#!/usr/bin/env python3
"""
NHAI RAG Indexer v3
- Uses MarkdownHeaderTextSplitter to capture document structure (headings as metadata)
- Applies RecursiveCharacterTextSplitter within each section for max chunk size + overlap
- Preserves all circular metadata
"""
import os
import json
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv


from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.text_splitter import MarkdownHeaderTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

from enrich_circulars import enrich_circulars_with_text  # Import the function
    

# Whoosh integration
from whoosh_indexer import build_whoosh_index, bm25_search

load_dotenv()

class NHAIRAGIndexerV3:

    #TODO: Do this after cron for re-scraping
    def remove_deleted_docs(self, current_circulars: List[Dict]):
        """
        Remove documents from Chroma and Whoosh that are not present in the current_circulars.
        """
        # 1. Build set of current policy_no (or chunk_id if more granular)
        current_ids = set()
        for circ in current_circulars:
            policy_no = circ.get('policy_no')
            if policy_no:
                current_ids.add(policy_no)

        # 2. Load all indexed docs from Chroma
        vectorstore = Chroma(
            persist_directory=self.vector_db_path,
            embedding_function=self.embeddings
        )
        all_docs = vectorstore.similarity_search("*", k=10000)
        to_delete = []
        for doc in all_docs:
            indexed_id = doc.metadata.get('policy_no')
            if indexed_id and indexed_id not in current_ids:
                to_delete.append(doc)

        # 3. Remove from Chroma
        if to_delete:
            print(f"Removing {len(to_delete)} deleted docs from Chroma...")
            ids = [doc.metadata.get('chunk_id') for doc in to_delete if doc.metadata.get('chunk_id')]
            if hasattr(vectorstore, 'delete'):  # Chroma supports delete by ids
                vectorstore.delete(ids)
            else:
                print("Warning: Chroma does not support deletion by id in this version.")
        else:
            print("No deleted docs to remove from Chroma.")

        # 4. Remove from Whoosh
        try:
            from whoosh.index import open_dir
            from whoosh.query import Term
            import shutil
            ix_dir = "output/whoosh_index"
            if not os.path.exists(ix_dir):
                print("Whoosh index directory not found.")
                return
            ix = open_dir(ix_dir)
            writer = ix.writer()
            removed = 0
            for doc in to_delete:
                chunk_id = doc.metadata.get('chunk_id')
                if chunk_id:
                    writer.delete_by_term('chunk_id', chunk_id)
                    removed += 1
            writer.commit()
            print(f"Removed {removed} docs from Whoosh index.")
        except Exception as e:
            print(f"Warning: Could not remove from Whoosh: {e}")
    
    def __init__(self, embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"): #all-MiniLM-L6-v2
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        self.vector_db_path = "output/chroma_db_v3"
        os.makedirs(self.vector_db_path, exist_ok=True)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""]
        )
        self.header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
        )
        print(f"✓ RAG Indexer v3 initialized with model: {embedding_model}")

    def load_circulars(self, jsonl_path: str) -> List[Dict]:
        circulars = []
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    circular = json.loads(line)
                    circulars.append(circular)
                except Exception as e:
                    print(f"Warning: Could not parse line: {e}")
        print(f"Loaded {len(circulars)} circulars from {jsonl_path}")
        return circulars

    def create_document_chunks(self, content: str, metadata: Dict) -> List[Document]:
        if not content.strip():
            return []

        # First, try to split by Markdown headers
        header_sections = self.header_splitter.split_text(content)
        
        # If no headers are found, treat the whole document as a single section
        if not header_sections:
            from langchain.schema import Document as LangchainDocument
            header_sections = [LangchainDocument(page_content=content, metadata={})]

        documents = []
        pdf_url = metadata.get('direct_pdf_url')
        pdf_filename = os.path.basename(pdf_url) if pdf_url else None

        for section_doc in header_sections:
            section_text = section_doc.page_content
            section_metadata = metadata.copy()
            if section_doc.metadata:
                section_metadata.update(section_doc.metadata)

            page_number = None
            for key in ['page', 'pages', 'page_no', 'page_number']:
                if key in section_metadata:
                    page_number = section_metadata[key]
                    break
            
            text_chunks = self.text_splitter.split_text(section_text)
            
            start_offset = 0
            for i, chunk in enumerate(text_chunks):
                doc_metadata = section_metadata.copy()
                chunk_hash = self._get_content_hash(chunk)
                
                header_id_parts = [str(doc_metadata.get(h_key, '')) for h_key in ['h1', 'h2', 'h3'] if doc_metadata.get(h_key)]
                header_id = "_".join(header_id_parts).replace(" ", "_") if header_id_parts else "no_header"

                doc_metadata.update({
                    'chunk_id': f"{metadata.get('policy_no', 'N/A')}_{header_id}_{i}",
                    'chunk_index': i,
                    'total_chunks': len(text_chunks),
                    'source_start': start_offset,
                    'source_end': start_offset + len(chunk),
                    'embedding_model': self.embedding_model,
                    'chunk_created_on': datetime.now().isoformat(),
                    'content_hash': chunk_hash,
                })
                if pdf_filename:
                    doc_metadata['pdf_filename'] = pdf_filename
                if page_number is not None:
                    doc_metadata['page_number'] = page_number
                
                doc = Document(page_content=chunk, metadata=doc_metadata)
                documents.append(doc)
                start_offset += len(chunk)
        return documents

    import hashlib

    def _get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _load_indexed_docs(self):
        """Load set of (policy_no, content_hash) for already indexed docs from Chroma."""
        try:
            vectorstore = Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
            # Use .get() to efficiently retrieve all metadata
            existing_docs = vectorstore.get(include=["metadatas"])
            indexed = set()
            if existing_docs and existing_docs.get('metadatas'):
                for meta in existing_docs['metadatas']:
                    policy_no = meta.get('policy_no')
                    content_hash = meta.get('content_hash')
                    if policy_no and content_hash:
                        indexed.add((policy_no, content_hash))
            print(f"Found {len(indexed)} already indexed documents in ChromaDB.")
            return indexed
        except Exception as e:
            # This can happen if the DB is empty or new, which is not an error.
            print(f"Info: Could not load indexed docs, assuming new index. Reason: {e}")
            return set()

    def index_circulars(self, circulars: List[Dict], batch_size: int = 10) -> Dict:
        stats = {
            'total_circulars': len(circulars),
            'processed': 0,
            'skipped_existing': 0,
            'failed': 0,
            'total_chunks': 0,
            'errors': []
        }
        print(f"Starting incremental indexing of {len(circulars)} circulars...")
        vectorstore = Chroma(
            persist_directory=self.vector_db_path,
            embedding_function=self.embeddings
        )
        all_documents_to_add = []
        indexed_docs = self._load_indexed_docs()
        
        for i, circular in enumerate(circulars):
            policy_no = circular.get('policy_no', f'Unknown_ID_{i}')
            print(f"Processing circular {i+1}/{len(circulars)}: {policy_no}")

            try:
                content = circular.get('text') or circular.get('content') or ''
                if not content.strip():
                    stats['failed'] += 1
                    stats['errors'].append(f"Skipping empty content for policy_no: {policy_no}")
                    print(f" -> Failed: Empty content.")
                    continue

                content_hash = self._get_content_hash(content)
                if (policy_no, content_hash) in indexed_docs:
                    stats['skipped_existing'] += 1
                    print(f" -> Skipped: Already indexed.")
                    continue

                metadata = dict(circular)
                for k, v in list(metadata.items()):
                    if isinstance(v, list):
                        metadata[k] = ' > '.join(str(x) for x in v)
                
                documents = self.create_document_chunks(content, metadata)
                
                if not documents:
                    stats['failed'] += 1
                    stats['errors'].append(f"No chunks created for policy_no: {policy_no}")
                    print(f" -> Failed: No chunks were created.")
                    continue

                all_documents_to_add.extend(documents)
                stats['total_chunks'] += len(documents)
                stats['processed'] += 1
                print(f" -> Success: Created {len(documents)} chunks.")

                if len(all_documents_to_add) >= batch_size:
                    print(f"\nAdding batch of {len(all_documents_to_add)} documents to ChromaDB...\n")
                    vectorstore.add_documents(all_documents_to_add)
                    all_documents_to_add = []

            except Exception as e:
                error_msg = f"Error processing {policy_no}: {str(e)}"
                print(f" -> Failed: {error_msg}")
                stats['errors'].append(error_msg)
                stats['failed'] += 1
        
        if all_documents_to_add:
            print(f"\nAdding final batch of {len(all_documents_to_add)} documents to ChromaDB...\n")
            vectorstore.add_documents(all_documents_to_add)
        
        # Rebuild Whoosh index from the full vectorstore content
        try:
            print("Rebuilding Whoosh keyword index...")
            all_docs_for_whoosh = vectorstore.get(include=["metadatas", "documents"])
            docs_to_index = [
                Document(page_content=doc, metadata=meta)
                for doc, meta in zip(all_docs_for_whoosh['documents'], all_docs_for_whoosh['metadatas'])
            ]
            if docs_to_index:
                build_whoosh_index(docs_to_index)
                print("Whoosh keyword index built successfully.")
            else:
                print("No documents found in vectorstore to build Whoosh index.")
        except Exception as e:
            print(f"Warning: Could not build Whoosh index: {e}")

        print(f"Indexing complete. Processed: {stats['processed']}, Skipped: {stats['skipped_existing']}, Failed: {stats['failed']}.")
        return stats

    def search_circulars(self, query: str, k: int = 5, filter_dict: Optional[Dict] = None, alpha: float = 0.5) -> List[Dict]:
        """
        Hybrid search: combine Chroma vector search and Whoosh BM25 keyword search.
        filter_dict: dict of metadata filters to apply to both Chroma and Whoosh results.
        """
        try:
            vectorstore = Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
            # 1. Vector search (with filter)
            if filter_dict:
                vector_results = vectorstore.similarity_search_with_score(query, k=k*2, filter=filter_dict)
            else:
                vector_results = vectorstore.similarity_search_with_score(query, k=k*2)
            vector_docs = {doc.metadata.get('chunk_id',''): (doc, score) for doc, score in vector_results}

            # 2. Keyword (BM25) search
            bm25_results = bm25_search(query, top_k=k*2)
            # Apply filter_dict to Whoosh results in Python
            if filter_dict:
                def match_filter(meta):
                    return all(str(meta.get(k, "")) == str(v) for k, v in filter_dict.items())
                bm25_results = [r for r in bm25_results if match_filter(r)]
            bm25_docs = {r['chunk_id']: (r, r.get('score', 1.0)) for r in bm25_results}

            # 3. Merge and re-rank (same as before)
            all_ids = set(vector_docs) | set(bm25_docs)
            merged = []
            for doc_id in all_ids:
                v_score = vector_docs.get(doc_id, (None, 0))[1]
                k_score = bm25_docs.get(doc_id, (None, 0))[1]
                v_score = 1/(1+v_score) if v_score else 0
                k_score = k_score or 0
                combined_score = alpha * v_score + (1 - alpha) * k_score
                doc = vector_docs.get(doc_id, (None,))[0]
                if doc is None and doc_id in bm25_docs:
                    bm = bm25_docs[doc_id][0]
                    from langchain.schema import Document
                    doc = Document(page_content=bm['content'], metadata={k: bm[k] for k in bm if k != 'content'})
                merged.append((doc, combined_score))

            merged.sort(key=lambda x: x[1], reverse=True)
            formatted_results = []
            for doc, score in merged[:k]:
                result = {
                    'content': doc.page_content,
                    'metadata': doc.metadata,
                    'hybrid_score': score
                }
                formatted_results.append(result)
            return formatted_results
        except Exception as e:
            print(f"Search error: {e}")
            return []

def main():

    # Define input and output file paths for enrichment
    input_file = "output/selenium_circulars.jsonl"
    output_file = "output/circulars_with_text.jsonl"

    enrich_circulars_with_text(input_file, output_file)

    import argparse
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer v3")
    parser.add_argument('action', choices=['index', 'search'], help='Action to perform')
    parser.add_argument('--input', type=str, default=output_file, help='Input JSONL file') # Correct default input file
    parser.add_argument('--query', '-q', type=str, help='Search query (for search action)')
    parser.add_argument('--results', '-r', type=int, default=5, help='Number of search results (default: 5)')
    parser.add_argument('--embedding-model', type=str, default="all-MiniLM-L6-v2", help='HuggingFace embedding model to use')
    args = parser.parse_args()
    
    indexer = NHAIRAGIndexerV3(embedding_model=args.embedding_model)
    if args.action == 'index':
        circulars = indexer.load_circulars(args.input)
        stats = indexer.index_circulars(circulars)
        print(stats)
    elif args.action == 'search':
        if not args.query:
            print("Error: Please provide a search query with --query")
            return
        results = indexer.search_circulars(args.query, k=args.results)
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['metadata'].get('subject','(no subject)')}")
            print(f"   Policy No: {result['metadata'].get('policy_no','')}")
            print(f"   Date: {result['metadata'].get('date','')}")
            print(f"   h1: {result['metadata'].get('h1','')}")
            print(f"   h2: {result['metadata'].get('h2','')}")
            print(f"   h3: {result['metadata'].get('h3','')}")
            print(f"   Content: {result['content'][:200]}...")
            print("-" * 80)

if __name__ == "__main__":
    main()
