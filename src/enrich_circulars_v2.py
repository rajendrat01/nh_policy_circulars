import os
import json
import requests
import pypdf
from io import BytesIO
import logging
import tempfile
from dotenv import load_dotenv
import hashlib
from datetime import datetime

# Optional OCR deps
try:
    import easyocr
    import fitz  # PyMuPDF
    from PIL import Image
    import io
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

MANIFEST_PATH = os.path.join("output", "enrich_manifest.json")


def ensure_output_dir():
    os.makedirs("output", exist_ok=True)


def load_manifest() -> dict:
    try:
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.warning(f"Could not load manifest: {e}")
        return {}


def save_manifest(manifest: dict):
    try:
        with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"Could not save manifest: {e}")


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def extract_text_regular(pdf_path: str) -> str:
    text = ""
    try:
        with open(pdf_path, 'rb') as pdf_file:
            pdf_reader = pypdf.PdfReader(pdf_file)
            for page in pdf_reader.pages:
                text += page.extract_text() or ""
    except Exception as e:
        logging.warning(f"pypdf extract error: {e}")
    return text


def enrich_circulars_with_text_v2(input_file: str,
                                  output_file: str,
                                  limit: int = 0,
                                  use_ocr: bool = True,
                                  revalidate: bool = False,
                                  verbose: bool = False) -> None:
    if not os.path.exists(input_file):
        logging.error(f"Input file not found: {input_file}")
        return

    ensure_output_dir()
    manifest = load_manifest()

    circulars = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                circulars.append(json.loads(line))

    if limit > 0:
        circulars = circulars[:limit]
        logging.info(f"Processing a limit of {limit} circulars.")

    ocr_reader = None
    if use_ocr and OCR_AVAILABLE:
        try:
            ocr_reader = easyocr.Reader(['en'], gpu=False)
            logging.info("OCR initialized (EasyOCR)")
        except Exception as e:
            logging.warning(f"OCR init failed: {e}")
            ocr_reader = None

    processed = 0
    with open(output_file, 'w', encoding='utf-8') as f_out:
        for i, circular in enumerate(circulars):
            policy_no = circular.get('policy_no', f'Unknown_{i}')
            pdf_url = circular.get('direct_pdf_url')

            if not pdf_url:
                logging.warning(f"[{i+1}/{len(circulars)}] Skipping {policy_no}: no PDF URL")
                circular['content'] = ''
                f_out.write(json.dumps(circular) + '\n')
                continue

            try:
                manifest_key = pdf_url or policy_no
                cached = manifest.get(manifest_key)

                # Fast path: reuse cached content without download when not revalidating
                if cached and not revalidate:
                    text = cached.get('content', '')
                    logging.info(f"[{i+1}/{len(circulars)}] SKIP download (cached). content_len={len(text)}")
                    pdf_hash = cached.get('pdf_hash', '')
                else:
                    logging.info(f"[{i+1}/{len(circulars)}] GET {pdf_url}")
                    resp = requests.get(pdf_url, timeout=60, verify=False)
                    resp.raise_for_status()
                    logging.info(f"[{i+1}/{len(circulars)}] Successfully downloaded {pdf_url}")

                    pdf_hash = sha256_bytes(resp.content)

                    # If cached and hashes match, reuse cached content and skip extraction
                    if cached and cached.get('pdf_hash') == pdf_hash:
                        text = cached.get('content', '')
                        logging.info(f"[{i+1}] Using cached content (len={len(text)}) for unchanged PDF")
                    else:
                        # Write temp PDF and extract
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tf:
                            tf.write(resp.content)
                            temp_pdf = tf.name
                        try:
                            text = extract_text_regular(temp_pdf)
                            logging.info(f"[{i+1}] Extracted {len(text)} bytes of text with _extract_text_regular")

                            # OCR fallback
                            if use_ocr and not text.strip():
                                if verbose:
                                    print("Text extraction insufficient, trying Gemini OCR...")
                                else:
                                    logging.info(f"[{i+1}] Trying OCR fallback")
                                try:
                                    from gemini_ocr import gemini_ocr_image
                                    gemini_api_key = os.environ.get("GEMINI_API_KEY")
                                    if not gemini_api_key:
                                        raise RuntimeError("GEMINI_API_KEY not set")
                                    doc = fitz.open(temp_pdf)
                                    full_text = ""
                                    for page_num in range(doc.page_count):
                                        page = doc[page_num]
                                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                                        img_data = pix.tobytes("png")
                                        image = Image.open(io.BytesIO(img_data))
                                        try:
                                            gemini_text = gemini_ocr_image(image, gemini_api_key)
                                            if verbose:
                                                print(f"[Gemini DEBUG] OCR page {page_num+1}/{doc.page_count}")
                                                print(f"[Gemini DEBUG] Gemini OCR result for page {page_num+1}: {repr(gemini_text)[:200]}")
                                        except Exception as ge:
                                            logging.warning(f"Gemini OCR error p{page_num+1}: {ge}")
                                            gemini_text = None
                                        if gemini_text and not str(gemini_text).startswith("[Gemini OCR Error]"):
                                            full_text += f"\n--- Page {page_num+1} (Gemini) ---\n{gemini_text}\n"
                                        elif ocr_reader:
                                            import numpy as np
                                            page_text = " ".join(ocr_reader.readtext(np.array(image), detail=0))
                                            if verbose:
                                                print(f"[Gemini DEBUG] EasyOCR fallback result for page {page_num+1}: {repr(page_text)[:200]}")
                                            full_text += f"\n--- Page {page_num+1} (EasyOCR) ---\n{page_text}\n"
                                    doc.close()
                                    if len(full_text.strip()) > 50:
                                        text = full_text
                                        logging.info(f"[{i+1}] OCR extracted {len(text)} chars")
                                    else:
                                        logging.info(f"[{i+1}] OCR extraction yielded minimal text")
                                except Exception as e:
                                    logging.warning(f"OCR fallback error: {e}")
                        finally:
                            try:
                                os.unlink(temp_pdf)
                            except Exception:
                                pass

                text = (text or '').strip()
                circular['content'] = text

                # Update manifest
                content_hash = sha256_text(text) if text else ''
                manifest[manifest_key] = {
                    'policy_no': policy_no,
                    'pdf_hash': pdf_hash,
                    'content_hash': content_hash,
                    'content_length': len(text),
                    'last_updated': datetime.now().isoformat(),
                    'content': text,
                }

                f_out.write(json.dumps(circular) + '\n')
                processed += 1

            except requests.exceptions.RequestException as e:
                logging.error(f"[{i+1}] Download failed {pdf_url}: {e}")
                circular['content'] = f"Error: Failed to download PDF. {e}"
                f_out.write(json.dumps(circular) + '\n')
            except Exception as e:
                logging.error(f"[{i+1}] Processing error for {policy_no}: {e}")
                circular['content'] = f"Error: Failed to process PDF. {e}"
                f_out.write(json.dumps(circular) + '\n')

    save_manifest(manifest)
    logging.info(f"Enrichment v2 complete. Processed {processed}/{len(circulars)} circulars → {output_file}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Enrich circulars (v2) with hash-based dedupe and optional OCR")
    parser.add_argument('--input', type=str, default='output/selenium_circulars.jsonl')
    parser.add_argument('--output', type=str, default='output/circulars_with_text.jsonl')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--use_ocr', action='store_true')
    parser.add_argument('--revalidate', action='store_true', help='Download and verify PDF hash even if cached')
    parser.add_argument('--verbose', action='store_true', help='Print detailed OCR debug logs')
    args = parser.parse_args()

    enrich_circulars_with_text_v2(args.input, args.output, args.limit, args.use_ocr, args.revalidate, args.verbose)


