## NHAI Circulars: End-to-End Processing Pipeline

This document explains how circulars flow from the NHAI site into searchable indexes with OCR support.

### Overview diagram

```
[Selenium (HTML snapshots)]
      |
      v
[Parse HTML -> JSONL (structured circulars)]
      |
      v
[Enrich PDFs -> Text (pypdf + optional OCR)]
      |
      v
[Index v4  (Chroma vector DB + Whoosh BM25)]
      |
      v
[Search / Query]
```

### Prerequisites
- Python 3.9+
- Firefox and geckodriver (geckodriver path is set in `src/selenium_nhai_scraper_v2.py`)
- Install base deps:
  - `pip install -r requirements.txt`
- For RAG + OCR and v4 indexer:
  - `pip install -r requirements-rag.txt`
  - Optional OCR extras: `easyocr`, `PyMuPDF`, `pillow`
  - Optional Gemini OCR: set `GEMINI_API_KEY` in environment

### 1) Scrape HTML snapshots (Selenium)
- Script: `src/selenium_nhai_scraper_v2.py`
- What it does:
  - Opens `https://library.nhai.org/CircularTree` and recursively iterates dropdowns: main category → subcategory → sub-subcategory → year.
  - Handles overlays and uses JS fallback clicks to ensure reliable selection.
  - For year dropdowns, aggregates results across all years into a single saved HTML per subcategory (to reduce files).
  - Saves the visible accordion HTML (plus a comment with the full path) for downstream parsing.
- Inputs: live site (read-only).
- Outputs: HTML files under `output/selenium_circulars/`, e.g. `circulars_1.1_Administration_Delegation_of_Powers.html`.
- Key logic: functions `recursive_scrape`, `save_leaf_html`, and `save_combined_years_html`.
- Run:
```bash
source nhai_circulars_env/bin/activate
python src/selenium_nhai_scraper_v2.py
```

### 2) Parse HTML into structured circulars (JSONL)
- Script: `src/parse_selenium_circulars.py`
- What it does:
  - Loads each HTML snapshot, extracts the path (category → subcategory) from the embedded comment.
  - Scans tables to extract rows with: serial no, subject (and link), policy number, date.
  - Normalizes direct PDF links to the full `https://library.nhai.org/nhailibrary/Assets/Pdf/...` form and deduplicates by URL.
- Inputs: `output/selenium_circulars/*.html`.
- Output: `output/selenium_circulars.jsonl` (one circular per line, with metadata and `direct_pdf_url`).
- Key logic: `parse_circulars_from_html`, `parse_all_selenium_circulars`, `save_circulars_jsonl`.
- Run:
```bash
source nhai_circulars_env/bin/activate
python src/parse_selenium_circulars.py
```

### 3) Enrich circulars with text (PDF extraction + OCR)
- Script: `src/enrich_circulars.py`
- What it does:
  - For each circular, downloads the PDF (via `direct_pdf_url`).
  - Primary text extraction with `pypdf` in `_extract_text_regular()`.
  - If extracted text is empty and `--use_ocr` is set: performs per‑page OCR with Gemini (`gemini_ocr.py`), falling back to EasyOCR if Gemini fails.
  - Writes back the original metadata plus a new `content` field with the extracted text.
- Inputs: `output/selenium_circulars.jsonl`.
- Output: `output/circulars_with_text.jsonl`.
- Environment: optional `GEMINI_API_KEY` (if using Gemini OCR). Optional OCR deps: EasyOCR, PyMuPDF, pillow.
- Run:
```bash
source nhai_circulars_env/bin/activate
# Without OCR (faster)
python src/enrich_circulars.py --input output/selenium_circulars.jsonl --output output/circulars_with_text.jsonl
# With OCR fallback
python src/enrich_circulars.py --input output/selenium_circulars.jsonl --output output/circulars_with_text.jsonl --use_ocr
```

### 4) Index with RAG v4 (Chroma + Whoosh hybrid)
- Script: `src/rag_indexer_v4.py`
- What it does:
  - Standalone indexer that ingests the text-enriched JSONL file.
  - Splits `content` using a Markdown-aware header splitter + recursive chunking.
  - Incrementally indexes chunks to Chroma (`output/chroma_db_v4`) using HF embeddings.
  - Skips already-indexed content using `(policy_no, content_hash)` comparisons.
  - Rebuilds a Whoosh BM25 index for keyword search over the same content/metadata.
- Input: `output/circulars_with_text.jsonl`.
- Outputs:
  - `output/chroma_db_v4/` (vector DB)
  - `output/whoosh_index/` (BM25 keyword index)
- Key logic: `NHAIRAGIndexerV4.index_circulars`, `_load_indexed_docs`, `build_whoosh_index`.
- Run:
```bash
source nhai_circulars_env/bin/activate
PYTHONPATH=$(pwd)/src python src/rag_indexer_v4.py index --input output/circulars_with_text.jsonl
```

### 5) Query (two options)
- RAG v4 hybrid search (programmatic): `NHAIRAGIndexerV4.search_circulars()`
- RAG v1 CLI/Interactive (existing): `query_circulars.py` uses `src/rag_indexer.py` (Chroma-only) if you prefer the simpler stack.

### 6) Weekly automation (cron)
- Wrapper: `src/weekly_update.sh`
- Suggested flow under cron:
  1. Run Selenium v2 scraper to refresh snapshots
  2. Parse to JSONL
  3. Enrich PDFs to text (optionally with OCR)
  4. Index with v4
- Example cron (Sundays at 02:00):
```
0 2 * * 0 /home/ec2-user/nhai_policy_circulars/src/weekly_update.sh >> /home/ec2-user/nhai_policy_circulars/logs/cron.log 2>&1
```

### Notes and troubleshooting
- Firefox/geckodriver: ensure `geckodriver` exists and Firefox is installed or accessible; `selenium_nhai_scraper_v2.py` will use an env var `FIREFOX_BIN` if provided.
- OCR deps: install EasyOCR, PyMuPDF, pillow if using OCR; set `GEMINI_API_KEY` for Gemini OCR.
- Large runs: indexing can be long; consider running in screen/tmux or with a scheduler.

### Golden path (copy-paste)
This sequence runs the whole pipeline end-to-end.

```bash
cd /home/ec2-user/nhai_policy_circulars
python -m venv nhai_circulars_env
source nhai_circulars_env/bin/activate
pip install -r requirements.txt
pip install -r requirements-rag.txt

# 1) Selenium scrape → HTML snapshots
python src/selenium_nhai_scraper_v2.py

# 2) Parse snapshots → JSONL
python src/parse_selenium_circulars.py

# 3) Enrich PDFs → Text (optional OCR)
python src/enrich_circulars.py --input output/selenium_circulars.jsonl --output output/circulars_with_text.jsonl --use_ocr

# 4) Index v4 (Chroma + Whoosh)
PYTHONPATH=$(pwd)/src python src/rag_indexer_v4.py index --input output/circulars_with_text.jsonl
```

### File map (key inputs/outputs)
- `output/selenium_circulars/` : raw HTML snapshots per subcategory
- `output/selenium_circulars.jsonl` : parsed circular metadata (PDF links, policy no, date, categories)
- `output/circulars_with_text.jsonl` : enriched circulars with `content` text
- `output/chroma_db_v4/` : Chroma vector store (v4 index)
- `output/whoosh_index/` : Whoosh BM25 keyword index

### Validation checks
- HTML snapshots present:
  - `ls -1 output/selenium_circulars | head`
- Parsed count looks reasonable:
  - `wc -l output/selenium_circulars.jsonl`
- Enriched JSONL has content:
  - `head -n 1 output/circulars_with_text.jsonl | jq '.'` (or open and ensure `content` is non-empty)
- Chroma v4 directory not empty:
  - `du -sh output/chroma_db_v4 || true`

### Troubleshooting (common)
- Element click intercepted / overlays on Selenium:
  - Script already hides top bar and uses JS click fallback; rerun if transient.
- Firefox not found under cron:
  - Ensure Firefox is installed; optionally export `FIREFOX_BIN` to the real binary.
- Gemini OCR not used:
  - Ensure `GEMINI_API_KEY` is set; otherwise extraction will rely on pypdf and EasyOCR.
- v4 import errors in cron:
  - Export `PYTHONPATH=/home/ec2-user/nhai_policy_circulars/src` in the job.

### Performance tips
- Enrichment with OCR is slow; run without `--use_ocr` for faster builds when testing.
- v4 indexing batches documents; expect minutes for thousands of chunks.
- Prefer weekly cron for full refresh; keep ad-hoc tests to a subset.

### Glossary
- Enrich: Download each circular PDF and attach extracted `content` text to its metadata.
- v4 Indexer: Hybrid index with Chroma vectors and Whoosh BM25, markdown-aware chunking.
- JSONL: One JSON object per line; easy to stream and process incrementally.
