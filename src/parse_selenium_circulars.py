import os
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime

def parse_circulars_from_html(html_content, category=None, sub_category=None, sub_sub_category=None, path_list=None):
    soup = BeautifulSoup(html_content, "html.parser")
    circulars = []
    seen_links = set()
    # Extract path from HTML comment if present
    comment = soup.find(string=lambda text: isinstance(text, type(soup.comment)))
    path = []
    if comment:
        m = re.search(r"Path: (.*?)-->", str(comment))
        if not m:
            m = re.search(r"Path: (.*)", str(comment))
        if m:
            path = [p.strip() for p in m.group(1).split('>')]
    # Allow override from function args
    if path_list:
        path = path_list
    # Assign category, sub_category, sub_sub_category from path if available
    category = path[0] if len(path) > 0 else (category or "")
    sub_category = path[1] if len(path) > 1 else (sub_category or "")
    sub_sub_category = path[2] if len(path) > 2 else (sub_sub_category or "")

    current_subcat = sub_category
    for tag in soup.find_all(['p', 'table']):
        # Detect subcategory change
        if tag.name == 'p':
            strong = tag.find('strong')
            if strong:
                current_subcat = strong.get_text(strip=True)
        if tag.name == 'table':
            # Parse all rows except header
            rows = tag.find_all('tr')
            if not rows or len(rows) < 2:
                continue
            header = [th.get_text(strip=True).lower() for th in rows[0].find_all(['td', 'th'])]
            for tr in rows[1:]:
                td_elems = tr.find_all('td')
                if len(td_elems) < 3:
                    continue
                sr_no = td_elems[0].get_text(strip=True)
                particulars_a = td_elems[1].find('a')
                particulars = particulars_a.get_text(strip=True) if particulars_a else td_elems[1].get_text(strip=True)
                pdf_link = particulars_a['href'] if particulars_a and particulars_a.has_attr('href') else ''
                policy_no = td_elems[2].get_text(strip=True) if len(td_elems) > 2 else ''
                # Date is usually in 4th column, but sometimes 3rd if policy_no is missing
                date_td = td_elems[3] if len(td_elems) > 3 else (td_elems[2] if len(td_elems) > 2 else None)
                date = ''
                if date_td:
                    date_a = date_td.find('a')
                    date = date_a.get_text(strip=True) if date_a else date_td.get_text(strip=True)
                # Compose direct PDF URL if relative
                if pdf_link and pdf_link.startswith('nhailibrary/Assets/Pdf/'):
                    direct_pdf_url = f"https://library.nhai.org/{pdf_link}"
                else:
                    direct_pdf_url = pdf_link
                # Avoid duplicates
                if direct_pdf_url in seen_links or not direct_pdf_url:
                    continue
                seen_links.add(direct_pdf_url)
                circular = {
                    "sr_no": sr_no,
                    "subject": particulars,
                    "policy_no": policy_no,
                    "date": date,
                    "category": category or "",
                    "sub_category": current_subcat or "",
                    "sub_sub_category": sub_sub_category or "",
                    "path": path,
                    "direct_pdf_url": direct_pdf_url,
                    "extracted_on": datetime.now().isoformat()
                }
                circulars.append(circular)
    return circulars

def parse_all_selenium_circulars(directory="output/selenium_circulars"):
    all_circulars = []
    files = [fname for fname in os.listdir(directory) if fname.endswith('.html')]
    print(f"Found {len(files)} HTML files in {directory}")
    for idx, fname in enumerate(files):
        print(f"Processing file {idx+1}/{len(files)}: {fname}")
        with open(os.path.join(directory, fname), encoding="utf-8") as f:
            html = f.read()
            # Extract path from comment
            m = re.search(r"<!-- Path: (.*?)-->", html)
            if not m:
                m = re.search(r"<!-- Path: (.*)", html)
            path = [p.strip() for p in m.group(1).split('>')] if m else []
            circulars = parse_circulars_from_html(html, path_list=path)
            print(f"  Extracted {len(circulars)} circulars from {fname}")
            all_circulars.extend(circulars)
    print(f"Total circulars extracted: {len(all_circulars)}")
    return all_circulars

def save_circulars_jsonl(circulars, out_path="output/selenium_circulars.jsonl"):
    with open(out_path, "w", encoding="utf-8") as f:
        for circ in circulars:
            f.write(json.dumps(circ, ensure_ascii=False) + "\n")
    print(f"Saved {len(circulars)} circulars to {out_path}")

if __name__ == "__main__":
    circulars = parse_all_selenium_circulars()
    save_circulars_jsonl(circulars)
