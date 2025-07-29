import requests
import re
import html
import json
import os
from datetime import datetime
from typing import Dict, List, Set
import time

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
        
        self.existing_links_file = "existing_links.json"
        self.new_links_file = "new_circulars.txt"
    
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
            with open("latest_nhai_page.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("Raw HTML saved to latest_nhai_page.html")
            
            # Try to extract links using multiple patterns
            print("Extracting links from HTML...")
            current_links = self.extract_links_from_html(html_content)
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
        print("- latest_nhai_page.html (raw HTML)")
        print("- existing_links.json (all circulars database)")
        print("- new_circulars.txt (new circulars only)")
    
    return success

if __name__ == "__main__":
    main() 