import requests
import re
import html
import json
import os
from datetime import datetime
from typing import Dict, List, Set
import time
from bs4 import BeautifulSoup

def parse_category_tree(tree_text: str):
    categories = {}
    current_cat = None
    
    for line in tree_text.splitlines():
        line = line.strip()
        if not line or line.startswith("Search For All Latest Updated Circulars"):
            continue
        
        # Match pattern like: '1.2.1 Facilities/entitlement (Deputatinist)+'
        m = re.match(r"(\d+(?:\.\d+)*)(?:\s+)(.+)\+", line)
        if m:
            code = m.group(1)
            title = m.group(2).strip()

            parts = code.split('.')
            if len(parts) == 1:
                # Top-level category
                current_cat = code
                categories[current_cat] = {
                    "title": title,
                    "sub_categories": {}
                }
            else:
                # Sub-category (or deeper) under current top-level category
                if current_cat:
                    categories[current_cat]["sub_categories"][code] = title

    return categories


# def scrape_category_tree_from_live(url: str):
#     response = requests.get(url, verify=False)
#     response.raise_for_status()
#     soup = BeautifulSoup(response.text, "html.parser")
    
#     # Find the element(s) containing the tree text (Example assumes it's in a <div> or <pre>)
#     # You need to inspect the real live HTML for exact selector
#     tree_container = soup.find("div", id="treeContainer")  # Update selector as per page
#     if not tree_container:
#         print("not tree_container")
#         # fallback: full text extraction or another selector
#         tree_container = soup.find("pre") or soup.body

#     tree_text = tree_container.get_text(separator="\n", strip=True)

#     print("Extracted category tree text sample:")
#     print(tree_text[:500])  # print first 500 chars for inspection

#     # Parse the extracted tree text with your existing parser
#     category_tree = parse_category_tree(tree_text)
#     return category_tree

def scrape_categories_from_live(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    categories = {}
    select = soup.find("select", id="MainContent_DropDownList1")
    if select:
        options = select.find_all("option")
        for opt in options:
            val = opt.get("value")
            text = opt.get_text(strip=True)
            if val and val.isdigit():
                categories[val] = text
    return categories


def get_form_data(soup: BeautifulSoup) -> Dict[str, str]:
    """Extracts hidden ASP.NET form fields needed for postbacks."""
    form_data = {}
    for input_tag in soup.find_all("input", type="hidden"):
        if input_tag.get("name"):
            form_data[input_tag.get("name")] = input_tag.get("value", "")
    return form_data


def save_category_tree(tree: dict, filepath: str):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)

def load_category_tree(filepath: str):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


class NHAIScraper:
    def __init__(self):
        self.base_url = "https://library.nhai.org"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        # Handle SSL certificate issues that some government websites have
        self.session.verify = False
        # Disable SSL warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        self.existing_links_file = "output/existing_links.json"
        self.new_links_file = "output/new_circulars.txt"

        self.category_tree_file = "output/category_tree.json"
        
        self.category_tree = {}

        # Ensure output directory exists
        os.makedirs("output", exist_ok=True)

    

    def update_category_tree(self):
        tree = load_category_tree(self.category_tree_file)
        if tree:
            print("Loaded category tree from file.")
            self.category_tree = tree
        else:
            print("Fetching category tree from live site...")
            tree = scrape_category_tree_from_live(f"{self.base_url}/CircularTree")
            save_category_tree(tree, self.category_tree_file)
            self.category_tree = tree
            print("Category tree saved locally.")

    def load_category_tree_from_text(self, tree_text):
        self.category_tree = parse_category_tree(tree_text)

    def find_category_for_policy_no(self, policy_no: str):
        # Return category and sub_category based on prefix matching policy_no
        
        # Extract numeric prefix from policy_no for matching
        # Assume policy_no starts with something like '1.2.1' or '7.1', otherwise fallback
        match = re.match(r"(\d+(?:\.\d+)*)", policy_no)
        if not match:
            return ("Unknown", "Unknown")
        prefix = match.group(1)
        
        # Check top-level categories first
        top_level = prefix.split('.')[0]
        if top_level in self.category_tree:
            cat_title = self.category_tree[top_level]["title"]
            # Try subcategories match by prefix
            for sub_code, sub_title in self.category_tree[top_level]["sub_categories"].items():
                if prefix.startswith(sub_code):
                    return (cat_title, sub_title)
            # No sub-category match fallback
            return (cat_title, "General")
        else:
            return ("Unknown", "Unknown")
    
    def fetch_webpage(self, url: str, max_retries: int = 3) -> str:
        """Fetch webpage content with retry mechanism"""
        for attempt in range(max_retries):
            try:
                print(f"Fetching {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.exceptions.RequestException as e:
                print(f"Error fetching {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait before retry
                else:
                    raise
    
    def extract_links_from_html(self, html_content: str) -> List[Dict]:
        """Extract all PDF links with metadata from HTML content"""
        # Updated pattern for the actual NHAI Circulars page structure
        # <tr><td>policy_no</td><td><a href='Circulars.aspx?_d_id=nhailibrary/Assets/Pdf/file.pdf'>subject</a></td><td>date</td></tr>
        pattern = r"<tr><td[^>]*>([^<]+)</td><td[^>]*><a\s+href='Circulars\.aspx\?_d_id=(nhailibrary/Assets/Pdf/[^']+\.pdf)'>([^<]+)</a></td><td[^>]*>([^<]*)</td>"
        
        matches = re.findall(pattern, html_content, re.DOTALL)
        print(f"Primary pattern found {len(matches)} matches")
        
        links_data = []
        seen_links = set()  # To avoid duplicates
        
        for match in matches:
            policy_no = match[0].strip()
            link_path = match[1].strip()
            subject = html.unescape(match[2].strip())
            date = match[3].strip() if match[3].strip() else 'N/A'
            
            # Skip duplicates
            if link_path in seen_links:
                continue
            seen_links.add(link_path)
            
            # Create full URL - note the NHAI link structure
            full_url = f"{self.base_url}/Circulars.aspx?_d_id={link_path}"
            direct_pdf_url = f"{self.base_url}/{link_path}"
            
            link_info = {
                'sr_no': str(len(links_data) + 1),
                'subject': subject,
                'policy_no': policy_no,
                'date': date,
                'link_path': link_path,
                'full_url': full_url,  # Link to the circular page
                'direct_pdf_url': direct_pdf_url,  # Direct link to PDF
                'extracted_on': datetime.now().isoformat()
            }
            links_data.append(link_info)
        
        return links_data 

    def extract_links_with_categories(self, html_content: str) -> List[Dict]:
        soup = BeautifulSoup(html_content, "html.parser")
        links_data = []
        seen_links = set()
        
        # Extract circular table rows assuming table structure like before
        # You can adjust based on actual HTML
        rows = soup.find_all("tr")
        for tr in rows:
            td_elems = tr.find_all("td")
            if len(td_elems) < 3:
                continue
            
            policy_no = td_elems[0].get_text(strip=True)
            a_tag = td_elems[1].find("a")
            if not a_tag:
                continue
            subject = a_tag.get_text(strip=True)
            href = a_tag.get("href")
            date = td_elems[2].get_text(strip=True) or "N/A"
            
            link_path_match = re.search(r"_d_id=(nhailibrary/Assets/Pdf/[^']+\.pdf)", href)
            if not link_path_match:
                continue
            link_path = link_path_match.group(1)
            
            if link_path in seen_links:
                continue
            seen_links.add(link_path)
            
            category, sub_category = self.find_category_for_policy_no(policy_no)
            
            full_url = f"{self.base_url}/Circulars.aspx?_d_id={link_path}"
            direct_pdf_url = f"{self.base_url}/{link_path}"
            
            link_info = {
                "sr_no": str(len(links_data) + 1),
                "category": category,
                "sub_category": sub_category,
                "subject": subject,
                "policy_no": policy_no,
                "date": date,
                "link_path": link_path,
                "full_url": full_url,
                "direct_pdf_url": direct_pdf_url,
                "extracted_on": datetime.now().isoformat()
            }
            links_data.append(link_info)
        
        return links_data

    def extract_links_with_categories_old(self, html_content: str) -> List[Dict]:
        """Extract all PDF links with metadata AND category/sub-category from HTML content."""
        soup = BeautifulSoup(html_content, "html.parser")
        
        links_data = []
        seen_links = set()
        
        # Assuming categories are represented in 'div' or 'li' elements with class='category' etc.
        # This is a generic placeholder; inspect actual site HTML and adjust selectors accordingly.
        
        # Example: iterate over each category block
        for category_div in soup.find_all(class_="category"):
            category_name = category_div.find(class_="category-title").get_text(strip=True) if category_div.find(class_="category-title") else "N/A"
            
            # Find all sub-category blocks inside this category
            sub_categories = category_div.find_all(class_="sub-category")
            
            if not sub_categories:
                # No sub-category, parse circulars directly under category_div
                circular_rows = category_div.find_all("tr")
                sub_category_name = "N/A"
            else:
                # Parse circulars per each sub-category
                for sub_cat_div in sub_categories:
                    sub_category_name = sub_cat_div.find(class_="sub-category-title").get_text(strip=True) if sub_cat_div.find(class_="sub-category-title") else "N/A"
                    circular_rows = sub_cat_div.find_all("tr")
                    
                    for tr in circular_rows:
                        td_elems = tr.find_all("td")
                        if len(td_elems) < 3:
                            continue
                        
                        policy_no = td_elems[0].get_text(strip=True)
                        a_tag = td_elems[1].find("a")
                        if not a_tag:
                            continue
                        subject = a_tag.get_text(strip=True)
                        href = a_tag.get("href")
                        date = td_elems[2].get_text(strip=True) or "N/A"
                        
                        link_path_match = re.search(r"_d_id=(nhailibrary/Assets/Pdf/[^']+\.pdf)", href)
                        if not link_path_match:
                            continue
                        link_path = link_path_match.group(1)
                        
                        if link_path in seen_links:
                            continue
                        seen_links.add(link_path)
                        
                        full_url = f"{self.base_url}/Circulars.aspx?_d_id={link_path}"
                        direct_pdf_url = f"{self.base_url}/{link_path}"
                        
                        link_info = {
                            "sr_no": str(len(links_data) + 1),
                            "category": category_name,
                            "sub_category": sub_category_name,
                            "subject": subject,
                            "policy_no": policy_no,
                            "date": date,
                            "link_path": link_path,
                            "full_url": full_url,
                            "direct_pdf_url": direct_pdf_url,
                            "extracted_on": datetime.now().isoformat()
                        }
                        links_data.append(link_info)
                continue
            
            # If no sub-categories, parse rows directly from category_div
            for tr in circular_rows:
                td_elems = tr.find_all("td")
                if len(td_elems) < 3:
                    continue
                
                policy_no = td_elems.get_text(strip=True)
                a_tag = td_elems[1].find("a")
                if not a_tag:
                    continue
                subject = a_tag.get_text(strip=True)
                href = a_tag.get("href")
                date = td_elems[2].get_text(strip=True) or "N/A"
                
                link_path_match = re.search(r"_d_id=(nhailibrary/Assets/Pdf/[^']+\.pdf)", href)
                if not link_path_match:
                    continue
                link_path = link_path_match.group(1)
                
                if link_path in seen_links:
                    continue
                seen_links.add(link_path)
                
                full_url = f"{self.base_url}/Circulars.aspx?_d_id={link_path}"
                direct_pdf_url = f"{self.base_url}/{link_path}"
                
                link_info = {
                    "sr_no": str(len(links_data) + 1),
                    "category": category_name,
                    "sub_category": "N/A",
                    "subject": subject,
                    "policy_no": policy_no,
                    "date": date,
                    "link_path": link_path,
                    "full_url": full_url,
                    "direct_pdf_url": direct_pdf_url,
                    "extracted_on": datetime.now().isoformat()
                }
                links_data.append(link_info)
        
        return links_data

    
    def load_existing_links(self) -> Set[str]:
        """Load existing links from file"""
        if os.path.exists(self.existing_links_file):
            try:
                with open(self.existing_links_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(item['link_path'] for item in data)
            except (json.JSONDecodeError, KeyError):
                print("Error reading existing links file, starting fresh")
                return set()
        return set()
    
    def save_all_links(self, links_data: List[Dict]):
        """Save all links to JSON file"""
        with open(self.existing_links_file, 'w', encoding='utf-8') as f:
            json.dump(links_data, f, indent=2, ensure_ascii=False)
    
    def find_new_circulars(self, current_links: List[Dict]) -> List[Dict]:
        """Compare current links with existing ones to find new circulars"""
        existing_link_paths = self.load_existing_links()
        
        new_circulars = []
        for link in current_links:
            if link['link_path'] not in existing_link_paths:
                new_circulars.append(link)
        
        return new_circulars
    
    def save_new_circulars(self, new_circulars: List[Dict]):
        """Save new circulars to text file"""
        if not new_circulars:
            print("No new circulars found!")
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(self.new_links_file, 'w', encoding='utf-8') as f:
            f.write(f"NEW NHAI CIRCULARS FOUND - {timestamp}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total New Circulars: {len(new_circulars)}\n\n")
            
            for i, circular in enumerate(new_circulars, 1):
                f.write(f"{i}. Subject: {circular['subject']}\n")
                f.write(f"   Policy No: {circular['policy_no']}\n")
                f.write(f"   Date: {circular['date']}\n")
                f.write(f"   Circular Page: {circular['full_url']}\n")
                f.write(f"   Direct PDF: {circular.get('direct_pdf_url', circular.get('full_url'))}\n")
                f.write(f"   File Path: {circular['link_path']}\n")
                f.write("-" * 50 + "\n")
        
        print(f"Found {len(new_circulars)} new circulars! Details saved to {self.new_links_file}")
    
    def scrape_and_check_updates(self):
        """Main method to scrape website and check for updates"""
        try:
            print("Starting NHAI circular scraper...")
            
            # Load or update category tree first
            self.update_category_tree()
            
            # Try multiple endpoints to get circular data
            html_content = None
            endpoints_to_try = [
                f"{self.base_url}/CircularTree",
                f"{self.base_url}/Circulars", 
                self.base_url,
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    print(f"Trying endpoint: {endpoint}")
                    html_content = self.fetch_webpage(endpoint)
                    
                    # Quick check if this endpoint has circular data
                    if 'nhailibrary/Assets/Pdf/' in html_content:
                        print(f"✓ Found circular data at: {endpoint}")
                        break
                    else:
                        print(f"  No circular data found at this endpoint")
                        
                except Exception as e:
                    print(f"  Failed to fetch {endpoint}: {e}")
                    continue
            
            if not html_content:
                print("Could not fetch data from any endpoint")
                return False
            
            # Save the raw HTML for reference
            with open("output/latest_nhai_page.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("Raw HTML saved to output/latest_nhai_page.html")

            # Try to extract links using multiple patterns
            print("Extracting links from HTML...")
            # current_links = self.extract_links_from_html(html_content)
            current_links = self.extract_links_with_categories(html_content)
            print(f"Total links found with primary pattern: {len(current_links)}")
            
            # If no links found, try alternative extraction methods
            if len(current_links) == 0:
                print("Trying alternative extraction patterns...")
                current_links = self.extract_links_alternative(html_content)
                print(f"Total links found with alternative patterns: {len(current_links)}")
            
            # Find new circulars
            print("Checking for new circulars...")
            new_circulars = self.find_new_circulars(current_links)
            
            # Save results
            self.save_all_links(current_links)
            self.save_new_circulars(new_circulars)
            
            # Print summary
            print(f"\nScraping completed successfully!")
            print(f"Total circulars: {len(current_links)}")
            print(f"New circulars: {len(new_circulars)}")
            
            if new_circulars:
                print("\nNew circulars found:")
                for circular in new_circulars[:5]:  # Show first 5
                    print(f"- {circular['subject'][:80]}...")
                if len(new_circulars) > 5:
                    print(f"  ... and {len(new_circulars) - 5} more")
            
        except Exception as e:
            print(f"Error during scraping: {e}")
            return False
        
        return True
    
    def extract_links_alternative(self, html_content: str) -> List[Dict]:
        """Alternative extraction methods for different HTML structures"""
        links_data = []
        seen_links = set()  # To avoid duplicates
        
        # Pattern 1: Direct PDF links with any surrounding structure
        pattern1 = r'href="(nhailibrary/Assets/Pdf/[^"]+\.pdf)"[^>]*>([^<]+)</a>'
        matches1 = re.findall(pattern1, html_content, re.DOTALL)
        
        print(f"Pattern 1 found {len(matches1)} matches")
        for match in matches1:
            link_path = match[0].strip()
            subject = html.unescape(match[1].strip())
            
            if link_path in seen_links:
                continue
            seen_links.add(link_path)
            
            link_info = {
                'sr_no': str(len(links_data) + 1),
                'subject': subject,
                'policy_no': 'N/A',
                'date': 'N/A',
                'link_path': link_path,
                'full_url': f"{self.base_url}/{link_path}",
                'direct_pdf_url': f"{self.base_url}/{link_path}",
                'extracted_on': datetime.now().isoformat()
            }
            links_data.append(link_info)
        
        # Pattern 2: Look for any PDF references (only if no matches from pattern 1)
        if len(links_data) == 0:
            pattern2 = r'(nhailibrary/Assets/Pdf/[^"\s]+\.pdf)'
            matches2 = re.findall(pattern2, html_content)
            
            print(f"Pattern 2 found {len(matches2)} PDF references")
            for match in matches2:
                link_path = match.strip().rstrip('"')
                
                if link_path in seen_links:
                    continue
                seen_links.add(link_path)
                
                link_info = {
                    'sr_no': str(len(links_data) + 1),
                    'subject': f'Circular from {link_path.split("/")[-1]}',
                    'policy_no': 'N/A',
                    'date': 'N/A', 
                    'link_path': link_path,
                    'full_url': f"{self.base_url}/{link_path}",
                    'direct_pdf_url': f"{self.base_url}/{link_path}",
                    'extracted_on': datetime.now().isoformat()
                }
                links_data.append(link_info)
        
        return links_data
    
    def get_new_circular_links_only(self) -> List[str]:
        """Return only the links of new circulars for easy access"""
        if not os.path.exists(self.new_links_file):
            return []
        
        # Read from JSON if new circulars were found
        existing_links = self.load_existing_links()
        html_content = self.fetch_webpage(self.base_url)
        current_links = self.extract_links_from_html(html_content)
        new_circulars = self.find_new_circulars(current_links)
        
        return [circular['full_url'] for circular in new_circulars]


    def _extract_circulars_from_soup(self, soup: BeautifulSoup, category: str, sub_category: str, seen_links: Set[str]) -> List[Dict]:
        """
        Uses the original extract_links_from_html logic to extract circulars, then attaches category/sub-category.
        """
        html_content = str(soup)
        circulars = self.extract_links_from_html(html_content)
        result = []
        for circ in circulars:
            link_path = circ['link_path']
            if link_path in seen_links:
                continue
            seen_links.add(link_path)
            circ['category'] = category
            circ['sub_category'] = sub_category
            result.append(circ)
        return result

    def scrape_all_circulars_dynamically(self) -> List[Dict]:
        """
        Scrapes all circulars by dynamically interacting with the ASP.NET form,
        iterating through categories and sub-categories.
        """
        all_circulars = []
        seen_links = set()
        
        # 1. Initial GET request
        print("Fetching initial page to get categories and form state...")
        initial_response = self.session.get(f"{self.base_url}/CircularTree")
        soup = BeautifulSoup(initial_response.text, "html.parser")
        
        # 2. Extract initial categories and form data
        initial_form_data = get_form_data(soup)
        categories = scrape_categories_from_live(initial_response.text)
        
        print(f"Found {len(categories)} main categories. Now iterating through them...")

        # 3. Loop through each main category
        for cat_id, cat_name in categories.items():
            print(f"\n--- Processing Category: {cat_name} ---")
            
            # Prepare POST data to select this category
            post_data = initial_form_data.copy()
            post_data.update({
                'ctl00$MainContent$DropDownList1': cat_id,
                '__EVENTTARGET': 'ctl00$MainContent$DropDownList1', # The control that triggered the postback
            })
            
            # 4. Make the POST request
            time.sleep(2) # Be polite to the server
            cat_response = self.session.post(f"{self.base_url}/CircularTree", data=post_data)
            cat_soup = BeautifulSoup(cat_response.text, "html.parser")

            # 5. Extract sub-categories from the response
            sub_categories = {}
            subcat_select = cat_soup.find("select", id="MainContent_DropDownList2")
            if subcat_select:
                for opt in subcat_select.find_all("option"):
                    if opt.get("value"):
                        sub_categories[opt.get("value")] = opt.text.strip()

            if not sub_categories:
                print("  No sub-categories found. Checking for circulars directly...")
                # (Add logic to parse circulars here if they appear without sub-cat selection)
                continue

            # 6. Loop through each sub-category
            for subcat_id, subcat_name in sub_categories.items():
                print(f"  -- Processing Sub-category: {subcat_name} --")
                # Get the latest form state from the previous response
                subcat_form_data = get_form_data(cat_soup)
                post_data_subcat = subcat_form_data.copy()
                post_data_subcat.update({
                    'ctl00$MainContent$DropDownList1': cat_id,
                    'ctl00$MainContent$DropDownList2': subcat_id,
                    '__EVENTTARGET': 'ctl00$MainContent$DropDownList2',
                })
                time.sleep(1)
                subcat_response = self.session.post(f"{self.base_url}/CircularTree", data=post_data_subcat)
                # Save the POST response HTML for inspection
                debug_filename = f"output/debug_{cat_id}_{subcat_id}.html"
                with open(debug_filename, "w", encoding="utf-8") as f:
                    f.write(subcat_response.text)
                print(f"    Saved POST response HTML to {debug_filename}")
                final_soup = BeautifulSoup(subcat_response.text, "html.parser")
                # 7. Extract circulars from this final response page
                circulars_found = self._extract_circulars_from_soup(final_soup, cat_name, subcat_name, seen_links)
                if circulars_found:
                    print(f"    Found {len(circulars_found)} circulars.")
                    all_circulars.extend(circulars_found)

        return all_circulars

    def scrape_and_check_updates(self):
        """Main method to run the dynamic scraper and check for updates."""
        try:
            print("Starting NHAI circular scraper with dynamic category handling...")
            
            # Run the new dynamic scraper
            current_links = self.scrape_all_circulars_dynamically()
            print(f"\nTotal circulars found across all categories: {len(current_links)}")

            # Find and save new circulars
            new_circulars = self.find_new_circulars(current_links)
            
            self.save_all_links(current_links)
            self.save_new_circulars(new_circulars)
            
            # ... (rest of your summary printing logic) ...
            
        except Exception as e:
            print(f"An error occurred during dynamic scraping: {e}")
            return False
        return True

def main():
    """Main function to run the scraper"""
    scraper = NHAIScraper()
    
    print("NHAI Circular Scraper")
    print("=" * 30)
    print("1. This will fetch the latest circulars from library.nhai.org")
    print("2. Compare with existing data to find new circulars")
    print("3. Save new circulars to separate file")
    print()
    
    # Run the scraper
    success = scraper.scrape_and_check_updates()
    
    
    if success:
        print("\nFiles created/updated:")
        print("- output/latest_nhai_page.html (raw HTML)")
        print("- output/existing_links.json (all circulars database)")
        print("- output/new_circulars.txt (new circulars only)")
    
    return success

if __name__ == "__main__":
    main() 