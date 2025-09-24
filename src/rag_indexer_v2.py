#!/usr/bin/env python3
"""
NHAI RAG Indexer v2
Reads circulars from output/selenium_circulars.jsonl (one JSON object per line, with full metadata),
chunks and embeds each circular, and stores in a Chroma vector DB for RAG.
"""

import os
from dotenv import load_dotenv
import json
from typing import List, Dict, Optional
from datetime import datetime

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document


# OCR and PDF extraction imports
try:
    import easyocr
    import fitz  # PyMuPDF
    from PIL import Image
    import io
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: OCR dependencies not installed. Install with: pip install easyocr PyMuPDF pillow")

from langchain_community.document_loaders import UnstructuredPDFLoader, PyMuPDFLoader
import tempfile
import requests
import shutil

class NHAIRAGIndexerV2:
    # Load .env file if present
    load_dotenv()
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""]
        )
        self.vector_db_path = "output/chroma_db_v2"
        os.makedirs(self.vector_db_path, exist_ok=True)
        self.pdf_storage_path = "output/pdfs_v2"
        os.makedirs(self.pdf_storage_path, exist_ok=True)
        self.ocr_reader = None
        if OCR_AVAILABLE:
            try:
                self.ocr_reader = easyocr.Reader(['en'], gpu=False)
                print("✓ OCR initialized successfully")
            except Exception as e:
                print(f"Warning: Could not initialize OCR: {e}")
        print(f"✓ RAG Indexer v2 initialized with model: {embedding_model}")

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

    def extract_pdf_content(self, pdf_url: str, policy_no: str, use_ocr: bool = True) -> tuple[str, bool, str]:
        safe_filename = f"{policy_no.replace('/', '_').replace('.', '_')}.pdf"
        local_pdf_path = os.path.join(self.pdf_storage_path, safe_filename)
        temp_file = None
        try:
            print(f"Downloading PDF: {pdf_url}")
            # SSL verification disabled as a workaround for certificate issues
            response = requests.get(pdf_url, timeout=60, verify=False)
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tf:
                tf.write(response.content)
                temp_file = tf.name
            print("Attempting text extraction...")
            text_content = self._extract_text_regular(temp_file)
            if len(text_content.strip()) > 100:
                print(f"✓ Text extracted successfully ({len(text_content)} chars)")
                used_ocr = False
            elif use_ocr:
                print("Text extraction insufficient, trying Gemini OCR...")
                try:
                    from gemini_ocr import gemini_ocr_image
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
                        print(f"[Gemini DEBUG] OCR page {page_num+1}/{doc.page_count}")
                        try:
                            gemini_text = gemini_ocr_image(image, gemini_api_key)
                            print(f"[Gemini DEBUG] Gemini OCR result for page {page_num+1}: {repr(gemini_text)[:200]}")
                        except Exception as gemini_exc:
                            print(f"[Gemini DEBUG] Exception in gemini_ocr_image for page {page_num+1}: {gemini_exc}")
                            gemini_text = None
                        if gemini_text and not str(gemini_text).startswith("[Gemini OCR Error]"):
                            full_text += f"\n--- Page {page_num + 1} (Gemini) ---\n{gemini_text}\n"
                        else:
                            print(f"Gemini failed for page {page_num+1}, using EasyOCR fallback...")
                            if self.ocr_reader:
                                import numpy as np
                                img_array = np.array(image)
                                results = self.ocr_reader.readtext(img_array, detail=0)
                                page_text = " ".join(results)
                                print(f"[Gemini DEBUG] EasyOCR fallback result for page {page_num+1}: {repr(page_text)[:200]}")
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
                    print(f"[Gemini DEBUG] Gemini OCR error: {e}")
                    used_ocr = False
            else:
                print("⚠ No OCR available, using basic text extraction")
                used_ocr = False
            # Always save the PDF, even if extraction fails
            try:
                shutil.copy2(temp_file, local_pdf_path)
                print(f"✓ PDF saved to {local_pdf_path}")
            except Exception as e:
                print(f"⚠ Could not save PDF locally: {e}")
                local_pdf_path = ""
            return text_content, used_ocr, local_pdf_path
        except Exception as e:
            print(f"✗ Error extracting PDF content: {e}")
            return "", False, ""
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass

    def _extract_text_regular(self, pdf_path: str) -> str:
        try:
            loader = UnstructuredPDFLoader(pdf_path, mode="single")
            documents = loader.load()
            if documents and len(documents[0].page_content.strip()) > 100:
                return documents[0].page_content
        except Exception as e:
            print(f"UnstructuredPDFLoader failed: {e}")
        try:
            loader = PyMuPDFLoader(pdf_path)
            documents = loader.load()
            return "\n".join([doc.page_content for doc in documents])
        except Exception as e:
            print(f"PyMuPDFLoader failed: {e}")
            return ""

    def create_document_chunks(self, content: str, metadata: Dict) -> List[Document]:
        if not content.strip():
            return []
        text_chunks = self.text_splitter.split_text(content)
        documents = []
        for i, chunk in enumerate(text_chunks):
            doc_metadata = metadata.copy()
            doc_metadata.update({
                'chunk_id': f"{metadata.get('policy_no','')}_{i}",
                'chunk_index': i,
                'total_chunks': len(text_chunks)
            })
            doc = Document(
                page_content=chunk,
                metadata=doc_metadata
            )
            documents.append(doc)
        return documents

    def index_circulars(self, circulars: List[Dict], batch_size: int = 10) -> Dict:
        stats = {
            'total_circulars': len(circulars),
            'processed': 0,
            'failed': 0,
            'used_ocr': 0,
            'total_chunks': 0,
            'errors': []
        }
        print(f"Starting indexing of {len(circulars)} circulars...")
        vectorstore = Chroma(
            persist_directory=self.vector_db_path,
            embedding_function=self.embeddings
        )
        all_documents = []
        for i, circular in enumerate(circulars):
            try:
                print(f"\n[{i+1}/{len(circulars)}] Processing: {circular.get('policy_no','?')}")
                pdf_url = circular.get('direct_pdf_url')
                policy_no = circular.get('policy_no','')
                content, used_ocr, local_pdf_path = ("", False, "")
                if pdf_url and policy_no:
                    content, used_ocr, local_pdf_path = self.extract_pdf_content(pdf_url, policy_no, use_ocr=True)
                else:
                    print("No PDF URL or policy_no, skipping.")
                    stats['failed'] += 1
                    continue
                if not content.strip():
                    print(f"⚠ No content extracted for {policy_no}")
                    stats['failed'] += 1
                    continue
                metadata = dict(circular)
                # Convert any list-type metadata fields to a string joined by ' > '
                for k, v in list(metadata.items()):
                    if isinstance(v, list):
                        metadata[k] = ' > '.join(str(x) for x in v)
                metadata['local_pdf_path'] = local_pdf_path
                metadata['used_ocr'] = used_ocr
                metadata['indexed_on'] = datetime.now().isoformat()
                metadata['content_length'] = len(content)
                documents = self.create_document_chunks(content, metadata)
                if documents:
                    all_documents.extend(documents)
                    stats['total_chunks'] += len(documents)
                    if used_ocr:
                        stats['used_ocr'] += 1
                    print(f"✓ Created {len(documents)} chunks")
                stats['processed'] += 1
                if len(all_documents) >= batch_size:
                    vectorstore.add_documents(all_documents)
                    all_documents = []
            except Exception as e:
                error_msg = f"Error processing {circular.get('policy_no','?')}: {str(e)}"
                print(error_msg)
                stats['errors'].append(error_msg)
                stats['failed'] += 1
        if all_documents:
            vectorstore.add_documents(all_documents)
        vectorstore.persist()
        print(f"Indexing complete. {stats['processed']} processed, {stats['failed']} failed.")
        return stats

    def search_circulars(self, query: str, k: int = 5, filter_dict: Optional[Dict] = None) -> List[Dict]:
        try:
            vectorstore = Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
            if filter_dict:
                results = vectorstore.similarity_search(query, k=k, filter=filter_dict)
            else:
                results = vectorstore.similarity_search(query, k=k)
            formatted_results = []
            for doc in results:
                result = {
                    'content': doc.page_content,
                    'metadata': doc.metadata
                }
                formatted_results.append(result)
            return formatted_results
        except Exception as e:
            print(f"Search error: {e}")
            return []

def main():
    import argparse
    parser = argparse.ArgumentParser(description="NHAI RAG Indexer v2")
    parser.add_argument('action', choices=['index', 'search'], help='Action to perform')
    parser.add_argument('--input', type=str, default="output/selenium_circulars.jsonl", help='Input JSONL file')
    parser.add_argument('--query', '-q', type=str, help='Search query (for search action)')
    parser.add_argument('--results', '-r', type=int, default=5, help='Number of search results (default: 5)')
    parser.add_argument('--embedding-model', type=str, default="all-MiniLM-L6-v2", help='HuggingFace embedding model to use')
    args = parser.parse_args()
    indexer = NHAIRAGIndexerV2(embedding_model=args.embedding_model)
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
            print(f"   Category: {result['metadata'].get('category','')}")
            print(f"   Subcategory: {result['metadata'].get('subcategory','')}")
            print(f"   Content: {result['content'][:200]}...")
            print("-" * 80)

if __name__ == "__main__":
    main()
