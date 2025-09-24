import sys
import os
import io
from PIL import Image
import fitz  # PyMuPDF
import numpy as np
import easyocr

from rag_indexer import NHAIRAGIndexer
from gemini_ocr import gemini_ocr_image

# Set your Gemini API key here or use an environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

def compare_ocr(pdf_path, page_limit=2):
    idx = NHAIRAGIndexer()
    reader = idx.ocr_reader

    doc = fitz.open(pdf_path)
    for page_num in range(min(doc.page_count, page_limit)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_data = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_data))
        img_array = np.array(image)

        print(f"\n=== Page {page_num+1} ===")

        # EasyOCR
        easy_text = " ".join(reader.readtext(img_array, detail=0))
        print("\n[EasyOCR Result]:\n", easy_text[:1000], "\n...")

        # Gemini OCR
        try:
            gemini_text = gemini_ocr_image(image, GEMINI_API_KEY)
            print("\n[Gemini OCR Result]:\n", gemini_text[:1000], "\n...")
        except Exception as e:
            print(f"\n[Gemini OCR Error]: {e}")

    doc.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare_ocr.py <pdf_path> [page_limit]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    page_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    compare_ocr(pdf_path, page_limit)
