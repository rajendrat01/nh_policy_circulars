#!/usr/bin/env python3
"""
NHAI RAG Indexer with OCR Support
Integrates with nhai_scraper.py to create a searchable vector database
with OCR capabilities for scanned PDFs using LangChain
"""

import os
import sys
import json
import hashlib
from typing import List, Dict, Optional
from datetime import datetime
import tempfile

# LangChain imports
from langchain_community.document_loaders import UnstructuredPDFLoader, PyMuPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

# OCR fallback imports
try:
    import easyocr
    import fitz  # PyMuPDF
    from PIL import Image
    import io
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: OCR dependencies not installed. Install with: pip install easyocr PyMuPDF pillow")

# Import existing scraper
from nhai_scraper import NHAIScraper

class NHAIRAGIndexer:
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialize RAG indexer with OCR capabilities
        
        Args:
            embedding_model: HuggingFace model for embeddings (free alternative to OpenAI)
        """
        self.scraper = NHAIScraper()
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        
        # Text splitter for chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""]
        )
        
        # Vector store directory
        self.vector_db_path = "output/chroma_db"
        os.makedirs(self.vector_db_path, exist_ok=True)
        
        # PDF storage directory
        self.pdf_storage_path = "output/pdfs"
        os.makedirs(self.pdf_storage_path, exist_ok=True)
        
        # Initialize OCR reader if available
        self.ocr_reader = None
        if OCR_AVAILABLE:
            try:
                self.ocr_reader = easyocr.Reader(['en'], gpu=False)
                print("✓ OCR initialized successfully")
            except Exception as e:
                print(f"Warning: Could not initialize OCR: {e}")
        
        print(f"✓ RAG Indexer initialized with model: {embedding_model}")
    
    def extract_pdf_content(self, pdf_url: str, policy_no: str, use_ocr: bool = True) -> tuple[str, bool, str]:
        """
        Extract text content from PDF with OCR fallback
        
        Args:
            pdf_url: URL to the PDF file
            policy_no: Policy number for filename
            use_ocr: Whether to use OCR for scanned PDFs
            
        Returns:
            tuple: (extracted_text, used_ocr, local_pdf_path)
        """
        # Create safe filename
        safe_filename = f"{policy_no.replace('/', '_').replace('.', '_')}.pdf"
        local_pdf_path = os.path.join(self.pdf_storage_path, safe_filename)
        
        temp_file = None
        try:
            # Download PDF to temporary file
            print(f"Downloading PDF: {pdf_url}")
            response = self.scraper.session.get(pdf_url, timeout=60)
            response.raise_for_status()
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tf:
                tf.write(response.content)
                temp_file = tf.name
            
            # Try regular text extraction first
            print("Attempting text extraction...")
            text_content = self._extract_text_regular(temp_file)
            
            # Check if text extraction was successful
            if len(text_content.strip()) > 100:
                print(f"✓ Text extracted successfully ({len(text_content)} chars)")
                used_ocr = False
            # Fallback to OCR if text is too short (likely scanned)
            elif use_ocr:
                print("Text extraction insufficient, trying Gemini OCR...")
                try:
                    from gemini_ocr import gemini_ocr_image
                    import os
                    from PIL import Image
                    import fitz
                    import io
                    gemini_api_key = os.environ.get("GEMINI_API_KEY")
                    if not gemini_api_key:
                        raise RuntimeError("GEMINI_API_KEY environment variable not set.")
                    doc = fitz.open(temp_file)
                    full_text = ""
                    for page_num in range(doc.page_count):
                        page = doc[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        img_data = pix.tobytes("png")
                        image = Image.open(io.BytesIO(img_data))
                        gemini_text = gemini_ocr_image(image, gemini_api_key)
                        if gemini_text and not gemini_text.startswith("[Gemini OCR Error]"):
                            full_text += f"\n--- Page {page_num + 1} (Gemini) ---\n{gemini_text}\n"
                        else:
                            # Fallback to EasyOCR for this page
                            print(f"Gemini failed for page {page_num+1}, using EasyOCR fallback...")
                            if self.ocr_reader:
                                import numpy as np
                                img_array = np.array(image)
                                results = self.ocr_reader.readtext(img_array, detail=0)
                                page_text = " ".join(results)
                                full_text += f"\n--- Page {page_num + 1} (EasyOCR) ---\n{page_text}\n"
                            else:
                                print("No EasyOCR available for fallback.")
                    doc.close()
                    if len(full_text.strip()) > 50:
                        print(f"✓ OCR extraction successful ({len(full_text)} chars)")
                        text_content = full_text
                        used_ocr = True
                    else:
                        print("⚠ OCR extraction yielded minimal text")
                        used_ocr = False
                except Exception as e:
                    print(f"Gemini OCR error: {e}")
                    used_ocr = False
            else:
                print("⚠ No OCR available, using basic text extraction")
                used_ocr = False
            
            # Save PDF permanently if we got good content
            if len(text_content.strip()) > 50:
                try:
                    # Copy to permanent storage
                    import shutil
                    shutil.copy2(temp_file, local_pdf_path)
                    print(f"✓ PDF saved to {local_pdf_path}")
                except Exception as e:
                    print(f"⚠ Could not save PDF locally: {e}")
                    local_pdf_path = ""
            else:
                local_pdf_path = ""
                
            return text_content, used_ocr, local_pdf_path
                
        except Exception as e:
            print(f"✗ Error extracting PDF content: {e}")
            return "", False, ""
        finally:
            # Cleanup temporary file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass
    
    def _extract_text_regular(self, pdf_path: str) -> str:
        """Extract text using regular PDF text extraction"""
        try:
            # Try UnstructuredPDFLoader first (better structure preservation)
            loader = UnstructuredPDFLoader(pdf_path, mode="single")
            documents = loader.load()
            if documents and len(documents[0].page_content.strip()) > 100:
                return documents[0].page_content
        except Exception as e:
            print(f"UnstructuredPDFLoader failed: {e}")
        
        try:
            # Fallback to PyMuPDFLoader
            loader = PyMuPDFLoader(pdf_path)
            documents = loader.load()
            return "\n".join([doc.page_content for doc in documents])
        except Exception as e:
            print(f"PyMuPDFLoader failed: {e}")
            return ""
    
    def _extract_text_ocr(self, pdf_path: str) -> str:
        """Extract text using OCR for scanned PDFs"""
        if not self.ocr_reader:
            return ""
        
        try:
            import numpy as np
            doc = fitz.open(pdf_path)
            full_text = ""
            
            for page_num in range(min(doc.page_count, 10)):  # Limit to 10 pages for performance
                page = doc[page_num]
                
                # Convert page to image
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scaling for better OCR
                img_data = pix.tobytes("png")
                image = Image.open(io.BytesIO(img_data))
                
                # Convert PIL image to numpy array for EasyOCR
                img_array = np.array(image)
                
                # OCR the image
                results = self.ocr_reader.readtext(img_array, detail=0)  # detail=0 returns only text
                page_text = " ".join(results)
                
                if page_text.strip():
                    full_text += f"\n--- Page {page_num + 1} ---\n{page_text}\n"
                
                print(f"OCR processed page {page_num + 1}/{doc.page_count}")
            
            doc.close()
            return full_text
            
        except Exception as e:
            print(f"OCR extraction error: {e}")
            return ""
    
    def create_document_chunks(self, content: str, metadata: Dict) -> List[Document]:
        """Create LangChain Document chunks with metadata"""
        if not content.strip():
            return []
        
        # Split content into chunks
        text_chunks = self.text_splitter.split_text(content)
        
        # Create Document objects with metadata
        documents = []
        for i, chunk in enumerate(text_chunks):
            doc_metadata = metadata.copy()
            doc_metadata.update({
                'chunk_id': f"{metadata['policy_no']}_{i}",
                'chunk_index': i,
                'total_chunks': len(text_chunks)
            })
            
            doc = Document(
                page_content=chunk,
                metadata=doc_metadata
            )
            documents.append(doc)
        
        return documents
    
    def index_circulars(self, circulars: List[Dict], batch_size: int = 5) -> Dict:
        """
        Index circulars in vector database with OCR support
        
        Args:
            circulars: List of circular dictionaries from scraper
            batch_size: Number of PDFs to process in each batch
            
        Returns:
            Dict with processing statistics
        """
        stats = {
            'total_circulars': len(circulars),
            'processed': 0,
            'failed': 0,
            'used_ocr': 0,
            'total_chunks': 0,
            'errors': []
        }
        
        print(f"Starting indexing of {len(circulars)} circulars...")
        
        # Initialize or load existing vector store
        vectorstore = Chroma(
            persist_directory=self.vector_db_path,
            embedding_function=self.embeddings
        )
        
        all_documents = []
        
        for i, circular in enumerate(circulars):
            try:
                print(f"\n[{i+1}/{len(circulars)}] Processing: {circular['policy_no']}")
                
                # Extract content with OCR
                content, used_ocr, local_pdf_path = self.extract_pdf_content(
                    circular['direct_pdf_url'], 
                    circular['policy_no'],
                    use_ocr=True
                )
                
                if not content.strip():
                    print(f"⚠ No content extracted for {circular['policy_no']}")
                    stats['failed'] += 1
                    continue
                
                # Create metadata
                metadata = {
                    'policy_no': circular['policy_no'],
                    'subject': circular['subject'],
                    'date': circular['date'],
                    'url': circular['full_url'],
                    'link_path': circular['link_path'],
                    'local_pdf_path': local_pdf_path,
                    'category': 'NHAI_Circular',
                    'extracted_on': circular.get('extracted_on', datetime.now().isoformat()),
                    'indexed_on': datetime.now().isoformat(),
                    'used_ocr': used_ocr,
                    'content_length': len(content)
                }
                
                # Create document chunks
                documents = self.create_document_chunks(content, metadata)
                
                if documents:
                    all_documents.extend(documents)
                    stats['total_chunks'] += len(documents)
                    if used_ocr:
                        stats['used_ocr'] += 1
                    print(f"✓ Created {len(documents)} chunks")
                    
                stats['processed'] += 1
                
                # Process in batches to avoid memory issues
                if len(all_documents) >= batch_size * 10:  # ~50 documents per batch
                    print(f"\nProcessing batch of {len(all_documents)} documents...")
                    vectorstore.add_documents(all_documents)
                    all_documents = []
                    print("✓ Batch indexed successfully")
                
            except Exception as e:
                error_msg = f"Error processing {circular['policy_no']}: {str(e)}"
                print(f"✗ {error_msg}")
                stats['errors'].append(error_msg)
                stats['failed'] += 1
        
        # Process remaining documents
        if all_documents:
            print(f"\nProcessing final batch of {len(all_documents)} documents...")
            vectorstore.add_documents(all_documents)
            print("✓ Final batch indexed successfully")
        
        # Persist the vector store
        vectorstore.persist()
        
        return stats
    
    def search_circulars(self, query: str, k: int = 5, filter_dict: Optional[Dict] = None) -> List[Dict]:
        """
        Search circulars using semantic similarity
        
        Args:
            query: Search query
            k: Number of results to return
            filter_dict: Metadata filters (e.g., {'date': {'$gte': '2025-01-01'}})
            
        Returns:
            List of search results with metadata
        """
        try:
            vectorstore = Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
            
            # Perform similarity search
            if filter_dict:
                results = vectorstore.similarity_search(query, k=k, filter=filter_dict)
            else:
                results = vectorstore.similarity_search(query, k=k)
            
            # Format results
            formatted_results = []
            for doc in results:
                result = {
                    'content': doc.page_content,
                    'metadata': doc.metadata,
                    'policy_no': doc.metadata.get('policy_no', 'Unknown'),
                    'subject': doc.metadata.get('subject', 'Unknown'),
                    'date': doc.metadata.get('date', 'Unknown'),
                    'url': doc.metadata.get('url', ''),
                    'used_ocr': doc.metadata.get('used_ocr', False)
                }
                formatted_results.append(result)
            
            return formatted_results
            
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def get_indexing_stats(self) -> Dict:
        """Get statistics about the indexed documents"""
        try:
            vectorstore = Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
            
            # Get collection info
            collection = vectorstore._collection
            total_docs = collection.count()
            
            # Sample some documents to get metadata stats
            sample_results = vectorstore.similarity_search("policy", k=min(100, total_docs))
            
            stats = {
                'total_chunks': total_docs,
                'unique_policies': len(set(doc.metadata.get('policy_no', '') for doc in sample_results)),
                'ocr_documents': sum(1 for doc in sample_results if doc.metadata.get('used_ocr', False)),
                'latest_indexed': max((doc.metadata.get('indexed_on', '') for doc in sample_results), default='Unknown')
            }
            
            return stats
            
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {'error': str(e)}

def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer with OCR")
    parser.add_argument('action', choices=['index', 'search', 'stats'], 
                       help='Action to perform')
    parser.add_argument('--query', '-q', type=str, 
                       help='Search query (for search action)')
    parser.add_argument('--results', '-r', type=int, default=5,
                       help='Number of search results (default: 5)')
    parser.add_argument('--new-only', action='store_true',
                       help='Index only new circulars from latest scrape')
    parser.add_argument('--embedding-model', type=str, default="all-MiniLM-L6-v2",
                       help='HuggingFace embedding model to use')
    
    args = parser.parse_args()
    
    # Initialize indexer
    indexer = NHAIRAGIndexer(embedding_model=args.embedding_model)
    
    if args.action == 'index':
        # Load circulars from existing database
        if args.new_only and os.path.exists("output/new_circulars.txt"):
            # Try to extract new circulars info
            print("Indexing new circulars only...")
            # For simplicity, load all and let user run scraper first
            circulars_file = "output/existing_links.json"
        else:
            circulars_file = "output/existing_links.json"
        
        if not os.path.exists(circulars_file):
            print(f"Error: {circulars_file} not found. Run the scraper first:")
            print("python src/nhai_scraper.py")
            return
        
        with open(circulars_file, 'r', encoding='utf-8') as f:
            circulars = json.load(f)
        
        if not circulars:
            print("No circulars found to index.")
            return
        
        print(f"Loaded {len(circulars)} circulars from {circulars_file}")
        
        # Index circulars
        stats = indexer.index_circulars(circulars)
        
        # Print results
        print("\n" + "="*50)
        print("INDEXING COMPLETED")
        print("="*50)
        print(f"Total circulars: {stats['total_circulars']}")
        print(f"Successfully processed: {stats['processed']}")
        print(f"Failed: {stats['failed']}")
        print(f"Used OCR: {stats['used_ocr']}")
        print(f"Total chunks created: {stats['total_chunks']}")
        
        if stats['errors']:
            print(f"\nErrors ({len(stats['errors'])}):")
            for error in stats['errors'][:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(stats['errors']) > 5:
                print(f"  ... and {len(stats['errors']) - 5} more")
    
    elif args.action == 'search':
        if not args.query:
            print("Error: Please provide a search query with --query")
            return
        
        print(f"Searching for: '{args.query}'")
        results = indexer.search_circulars(args.query, k=args.results)
        
        if not results:
            print("No results found.")
            return
        
        print(f"\nFound {len(results)} results:")
        print("="*80)
        
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result['subject']}")
            print(f"   Policy No: {result['policy_no']}")
            print(f"   Date: {result['date']}")
            print(f"   OCR Used: {'Yes' if result['used_ocr'] else 'No'}")
            print(f"   URL: {result['url']}")
            print(f"   Content: {result['content'][:200]}...")
            print("-" * 80)
    
    elif args.action == 'stats':
        stats = indexer.get_indexing_stats()
        
        print("\nIndexing Statistics:")
        print("="*30)
        for key, value in stats.items():
            print(f"{key.replace('_', ' ').title()}: {value}")

if __name__ == "__main__":
    main()
