#!/usr/bin/env python3
"""
Setup script for NHAI Circular Scraper
"""

import subprocess
import sys
import os

def install_requirements():
    """Install required packages"""
    print("Installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✓ Dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Error installing dependencies: {e}")
        return False

def create_initial_baseline():
    """Create initial baseline by running the scraper once"""
    print("\nCreating initial baseline...")
    try:
        from nhai_scraper import NHAIScraper
        scraper = NHAIScraper()
        
        # Since this is the first run, all links will be considered "existing"
        success = scraper.scrape_and_check_updates()
        
        if success:
            print("✓ Initial baseline created!")
            print("  - All current circulars saved to existing_links.json")
            print("  - Future runs will detect new circulars")
            return True
        else:
            print("✗ Failed to create baseline")
            return False
            
    except Exception as e:
        print(f"✗ Error creating baseline: {e}")
        return False

def main():
    """Main setup function"""
    print("NHAI Circular Scraper Setup")
    print("=" * 40)
    
    # Install dependencies
    if not install_requirements():
        print("\nSetup failed. Please install requirements manually:")
        print("pip install -r requirements.txt")
        return False
    
    # Create initial baseline
    if not create_initial_baseline():
        print("\nWarning: Could not create initial baseline.")
        print("You can run 'python nhai_scraper.py' manually later.")
    
    print("\n" + "=" * 40)
    print("Setup completed successfully!")
    print("\nHow to use:")
    print("1. python nhai_scraper.py          - Run scraper once")
    print("2. python auto_monitor.py once     - Check for new circulars")
    print("3. python auto_monitor.py monitor  - Start continuous monitoring")
    print("\nFiles:")
    print("- existing_links.json  : Database of all circulars")
    print("- new_circulars.txt    : New circulars found")
    print("- monitor_log.txt      : Monitoring activity log")
    
    return True

if __name__ == "__main__":
    main() 