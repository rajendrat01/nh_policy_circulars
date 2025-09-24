#!/bin/bash
cd /home/ec2-user/nhai_policy_circulars

# Ensure Python can import modules from src when running under cron
export PYTHONPATH="/home/ec2-user/nhai_policy_circulars/src:${PYTHONPATH}"

# 1. Run the scraper (adjust the command as needed)
source nhai_circulars_env/bin/activate
/home/ec2-user/nhai_policy_circulars/nhai_circulars_env/bin/python src/selenium_nhai_scraper_v2.py

# 2. Parse HTML snapshots into JSONL (structured circulars)
/home/ec2-user/nhai_policy_circulars/nhai_circulars_env/bin/python src/parse_selenium_circulars.py

# 3. Enrich circulars with extracted text from PDFs (v2 with hash-based dedupe)
/home/ec2-user/nhai_policy_circulars/nhai_circulars_env/bin/python src/enrich_circulars_v2.py \
    --input output/selenium_circulars.jsonl \
    --output output/circulars_with_text.jsonl \
    --use_ocr --verbose

## 4. Run the standalone indexer v4
/home/ec2-user/nhai_policy_circulars/nhai_circulars_env/bin/python src/rag_indexer_v4.py index \
    --input output/circulars_with_text.jsonl

## 4. Run the standalone, robust indexer v5
       #/home/ec2-user/nhai_policy_circulars/nhai_circulars_env/bin/python src/rag_indexer_v5.py index

echo "Weekly update completed at $(date)"