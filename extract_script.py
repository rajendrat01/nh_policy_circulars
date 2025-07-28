import re
import html

def extract_all_links():
    """Extract all PDF links with subjects from the HTML file"""
    
    # Read the HTML file
    with open('Links.txt', 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Pattern to match table rows with PDF links
    # Looking for: <td>number</td><td><a href="...pdf">subject</a></td><td>policy</td><td>date</td>
    pattern = r'<tr><td>([^<]+)</td><td><a href="(nhailibrary/Assets/Pdf/[^"]+\.pdf)" target="_blank">([^<]+)</a></td><td>([^<]*)</td><td><a href="[^"]*" title="[^"]*" target="_blank">([^<]+)</a></td></tr>'
    
    matches = re.findall(pattern, content, re.DOTALL)
    
    links_data = []
    for match in matches:
        sr_no = match[0].strip()
        link_path = match[1].strip()
        subject = html.unescape(match[2].strip())
        policy_no = match[3].strip()
        date = match[4].strip()
        
        links_data.append({
            'sr_no': sr_no,
            'subject': subject,
            'policy_no': policy_no,
            'date': date,
            'link': link_path
        })
    
    return links_data

def write_extracted_links(links_data):
    """Write all extracted links to a file"""
    
    with open('complete_extracted_links.txt', 'w', encoding='utf-8') as file:
        file.write("NHAI Policy Circulars - COMPLETE EXTRACTION\n")
        file.write("=" * 50 + "\n\n")
        file.write(f"Total Links Found: {len(links_data)}\n")
        file.write("Base URL: https://nhailibrary.nhai.gov.in/\n\n")
        
        # Group by category (extract from sr_no pattern)
        categories = {}
        for link in links_data:
            # Extract category from serial number (e.g., "1.1.37" -> "1")
            parts = link['sr_no'].split('.')
            if len(parts) >= 1:
                main_cat = parts[0]
                if main_cat not in categories:
                    categories[main_cat] = []
                categories[main_cat].append(link)
        
        # Define category names
        category_names = {
            '1': 'ADMINISTRATION',
            '2': 'DISPUTE RESOLUTION & LEGAL MATTERS',
            '3': 'FINANCE & ACCOUNTS',
            '4': 'ADVERTISEMENT/MEDIA RELATION/INAUGURATION',
            '5': 'VIGILANCE',
            '6': 'GUIDELINES RELATED TO IT APPLICATIONS',
            '7': 'PRE-CONSTRUCTION',
            '8': 'PUBLIC PRIVATE PARTNERSHIP',
            '9': 'PUBLIC FUNDED',
            '10': 'CONSULTANCY',
            '11': 'STANDARD DOCUMENTS',
            '12': 'ROAD SAFETY',
            '13': 'TECHNOLOGY INDUCTION CELL',
            '14': 'ACCESS PERMISSION',
            '15': 'QUALITY ASSURANCE',
            '16': 'CRITERIA FOR ASSESSMENT',
            '17': 'COMMERCIAL OPERATIONS',
            '18': 'MISCELLANEOUS GUIDELINES'
        }
        
        # Write links organized by category
        for cat_num in sorted(categories.keys(), key=lambda x: int(x) if x.isdigit() else 999):
            cat_name = category_names.get(cat_num, f'CATEGORY {cat_num}')
            file.write(f"\n{cat_num}. {cat_name}\n")
            file.write("=" * len(f"{cat_num}. {cat_name}") + "\n\n")
            
            for link in sorted(categories[cat_num], key=lambda x: x['sr_no']):
                file.write(f"Sr.No: {link['sr_no']}\n")
                file.write(f"Subject: {link['subject']}\n")
                file.write(f"Policy No: {link['policy_no']}\n")
                file.write(f"Date: {link['date']}\n")
                file.write(f"Link: https://nhailibrary.nhai.gov.in/{link['link']}\n")
                file.write("-" * 80 + "\n\n")

if __name__ == "__main__":
    print("Extracting all links from HTML file...")
    links_data = extract_all_links()
    print(f"Found {len(links_data)} links")
    
    print("Writing to complete_extracted_links.txt...")
    write_extracted_links(links_data)
    print("Extraction complete!") 