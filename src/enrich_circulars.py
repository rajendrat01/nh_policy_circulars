import os
import json
import requests
import pypdf
from io import BytesIO
import logging
import tempfile
import shutil
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _extract_text_regular(pdf_path: str) -> str:
    text = ""
    try:
        pdf_file = open(pdf_path, 'rb')
        pdf_reader = pypdf.PdfReader(pdf_file)
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
    except Exception as e:
        print(f"Error extracting text with pypdf: {e}")
    return text


def enrich_circulars_with_text(input_file: str, output_file: str, limit: int = 0, use_ocr: bool = True):
    """
    Reads a JSONL file of circulars, downloads the PDF for each, extracts text,
    and writes the enriched data to a new JSONL file.  Includes OCR functionality.

    Args:
        input_file (str): Path to the input JSONL file.
        output_file (str): Path to the output JSONL file.
        limit (int): The number of circulars to process. If 0, all are processed.
        use_ocr (bool): Whether to use OCR if regular extraction fails.
    """
    if not os.path.exists(input_file):
        logging.error(f"Input file not found: {input_file}")
        return

    circulars = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            circulars.append(json.loads(line))

    if limit > 0:
        circulars = circulars[:limit]
        logging.info(f"Processing a limit of {limit} circulars.")

    ocr_reader = None
    if OCR_AVAILABLE:
        try:
            ocr_reader = easyocr.Reader(['en'], gpu=False)
            print("✓ OCR initialized successfully")
        except Exception as e:
            print(f"Warning: Could not initialize OCR: {e}")

    processed_count = 0
    with open(output_file, 'w', encoding='utf-8') as f_out:
        for i, circular in enumerate(circulars):
            policy_no = circular.get('policy_no', f'Unknown_{i}')
            pdf_url = circular.get('direct_pdf_url')

            if not pdf_url:
                logging.warning(f"[{i+1}/{len(circulars)}] Skipping {policy_no}: No PDF URL found.")
                circular['content'] = ''
                f_out.write(json.dumps(circular) + '\n')
                continue

            try:
                logging.info(f"[{i+1}/{len(circulars)}] Processing {policy_no} from {pdf_url}")
                response = requests.get(pdf_url, timeout=30, verify=False)
                response.raise_for_status()
                logging.info(f"[{i+1}/{len(circulars)}] Successfully downloaded {pdf_url}")

                pdf_file = BytesIO(response.content)

                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tf:
                    tf.write(response.content)
                    temp_file = tf.name

                text = _extract_text_regular(temp_file)
                logging.info(f"[{i+1}/{len(circulars)}] Extracted {len(text)} bytes of text with _extract_text_regular")

                if not text.strip() and use_ocr:
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
                                if ocr_reader:
                                    import numpy as np
                                    img_array = np.array(image)
                                    results = ocr_reader.readtext(img_array, detail=0)
                                    page_text = " ".join(results)
                                    print(f"[Gemini DEBUG] EasyOCR fallback result for page {page_num+1}: {repr(page_text)[:200]}")
                                    full_text += f"\n--- Page {page_num + 1} (EasyOCR) ---\n{page_text}\n"
                                else:
                                    print("No EasyOCR available for fallback.")
                        doc.close()
                        if len(full_text.strip()) > 50:
                            print(f"✓ OCR extraction successful ({len(full_text)} chars)")
                            text = full_text
                        else:
                            print("⚠ OCR extraction yielded minimal text")
                     except Exception as e:
                         print(f"[Gemini DEBUG] Gemini OCR error: {e}")
                circular['content'] = text.strip()
                f_out.write(json.dumps(circular) + '\n')
                processed_count += 1

                if temp_file and os.path.exists(temp_file):
                    try:
                        os.unlink(temp_file)
                    except:
                        pass

            except requests.exceptions.RequestException as e:
                logging.error(f"[{i+1}/{len(circulars)}] Failed to download {pdf_url}. Error: {e}")
                circular['content'] = f"Error: Failed to download PDF. {e}"
                f_out.write(json.dumps(circular) + '\n')
            except Exception as e:
                logging.error(f"[{i+1}/{len(circulars)}] Failed to process PDF for {policy_no}. Error: {e}")
                circular['content'] = f"Error: Failed to process PDF. {e}"
                f_out.write(json.dumps(circular) + '\n')

    logging.info(f"Enrichment complete. Processed {processed_count}/{len(circulars)} circulars.")
    logging.info(f"Output saved to {output_file}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Enrich NHAI circulars with text from PDFs.")
    parser.add_argument(
        '--input',
        type=str,
        default='output/selenium_circulars.jsonl',
        help='Input JSONL file path.'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='output/circulars_with_text.jsonl',
        help='Output JSONL file path.'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=0,
        help='Limit the number of circulars to process (0 for all).'
    )
    parser.add_argument(
        '--use_ocr',
        action='store_true',
        help='Enable OCR if regular text extraction fails.'
    )
    args = parser.parse_args()

    enrich_circulars_with_text(args.input, args.output, args.limit, args.use_ocr)