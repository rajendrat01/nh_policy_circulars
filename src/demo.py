#!/usr/bin/env python3
"""
NHAI Circular Scraper Demo
Demonstrates the main functionality of the scraper system
"""

import os
import json
from nhai_scraper import NHAIScraper

def demo_scraper_functionality():
    """Demonstrate the scraper functionality"""
    print("=" * 60)
    print("NHAI CIRCULAR SCRAPER DEMONSTRATION")
    print("=" * 60)
    
    scraper = NHAIScraper()
    
    print("\n1. TESTING CONNECTION TO NHAI WEBSITE")
    print("-" * 40)
    try:
        # Test basic connectivity
        html_content = scraper.fetch_webpage(f"{scraper.base_url}/Circulars")
        print("✓ Successfully connected to NHAI website")
        print(f"✓ Downloaded {len(html_content)} characters of HTML")
        
        # Test extraction
        links = scraper.extract_links_from_html(html_content)
        print(f"✓ Successfully extracted {len(links)} circular links")
        
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False
    
    print("\n2. SAMPLE OF EXTRACTED CIRCULARS")
    print("-" * 40)
    for i, circular in enumerate(links[:5], 1):
        print(f"{i}. Policy No: {circular['policy_no']}")
        print(f"   Subject: {circular['subject'][:80]}...")
        print(f"   Date: {circular['date']}")
        print()
    
    print("\n3. DATA STORAGE DEMONSTRATION")
    print("-" * 40)
    
    # Save data
    scraper.save_all_links(links)
    print(f"✓ Saved {len(links)} circulars to existing_links.json")
    
    # Verify file size
    if os.path.exists("existing_links.json"):
        file_size = os.path.getsize("existing_links.json") / 1024  # KB
        print(f"✓ Database file size: {file_size:.1f} KB")
    
    print("\n4. NEW CIRCULAR DETECTION")
    print("-" * 40)
    
    # Simulate finding new circulars by checking latest data
    new_circulars = scraper.find_new_circulars(links)
    if new_circulars:
        print(f"✓ Found {len(new_circulars)} new circulars")
        scraper.save_new_circulars(new_circulars)
    else:
        print("✓ No new circulars found (database is up to date)")
    
    print("\n5. STATISTICAL SUMMARY")
    print("-" * 40)
    
    # Analyze the data
    policy_categories = {}
    dates_found = 0
    
    for circular in links:
        # Count policy categories
        policy_no = circular['policy_no']
        if '.' in policy_no:
            category = policy_no.split('.')[0]
            policy_categories[category] = policy_categories.get(category, 0) + 1
        
        # Count dates
        if circular['date'] != 'N/A' and circular['date'].strip():
            dates_found += 1
    
    print(f"✓ Total circulars in database: {len(links)}")
    print(f"✓ Circulars with dates: {dates_found}")
    print(f"✓ Policy categories found: {len(policy_categories)}")
    
    print("\nTop 5 Policy Categories:")
    sorted_categories = sorted(policy_categories.items(), key=lambda x: x[1], reverse=True)
    for category, count in sorted_categories[:5]:
        print(f"  Category {category}: {count} circulars")
    
    print("\n6. USAGE EXAMPLES")
    print("-" * 40)
    print("To monitor for new circulars:")
    print("  python auto_monitor.py once         # Check once")
    print("  python auto_monitor.py monitor 6    # Monitor every 6 hours")
    print()
    print("To run scraper manually:")
    print("  python nhai_scraper.py              # Extract all circulars")
    print()
    print("Files created:")
    print("  - existing_links.json   # Complete database")
    print("  - new_circulars.txt     # New circulars found")
    print("  - latest_nhai_page.html # Raw website data")
    print("  - monitor_log.txt       # Activity logs")
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    
    return True

def show_help():
    """Show usage help"""
    print("\nNHAI Circular Scraper Demo")
    print("Usage: python demo.py")
    print("\nThis demo will:")
    print("1. Test connection to NHAI website")
    print("2. Extract and display sample circular data")
    print("3. Demonstrate data storage and retrieval")
    print("4. Show new circular detection")
    print("5. Provide statistical analysis")
    print("6. Display usage examples")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] in ['help', '-h', '--help']:
        show_help()
    else:
        try:
            demo_scraper_functionality()
        except KeyboardInterrupt:
            print("\nDemo interrupted by user")
        except Exception as e:
            print(f"\nDemo failed with error: {e}")
            print("Please check your internet connection and try again.") 