#!/usr/bin/env python3
"""
NHAI Circular Auto Monitor
Automatically checks for new NHAI circulars at scheduled intervals
"""

import schedule
import time
import sys
import os
from datetime import datetime
from nhai_scraper import NHAIScraper

class NHAIMonitor:
    def __init__(self):
        self.scraper = NHAIScraper()
        self.log_file = "output/monitor_log.txt"
        
        # Ensure output directory exists
        os.makedirs("output", exist_ok=True)
    
    def log_message(self, message: str):
        """Log message with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        
        # Also write to log file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    
    def run_check(self):
        """Run a single check for new circulars"""
        self.log_message("Starting scheduled NHAI circular check...")
        
        try:
            success = self.scraper.scrape_and_check_updates()
            
            if success:
                # Check if any new circulars were found
                if os.path.exists("output/new_circulars.txt"):
                    with open("output/new_circulars.txt", "r", encoding="utf-8") as f:
                        content = f.read()
                        if "Total New Circulars: 0" not in content:
                            self.log_message("✓ NEW CIRCULARS DETECTED! Check output/new_circulars.txt")
                        else:
                            self.log_message("✓ Check completed - No new circulars")
                else:
                    self.log_message("✓ Check completed - No new circulars")
            else:
                self.log_message("✗ Check failed - See error details above")
                
        except Exception as e:
            self.log_message(f"✗ Error during check: {e}")
    
    def start_monitoring(self, interval_hours: int = 6):
        """Start continuous monitoring"""
        self.log_message(f"Starting NHAI circular monitoring (checking every {interval_hours} hours)")
        
        # Schedule the job
        schedule.every(interval_hours).hours.do(self.run_check)
        
        # Run once immediately
        self.run_check()
        
        # Keep the script running
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute for scheduled jobs
        except KeyboardInterrupt:
            self.log_message("Monitoring stopped by user")

def main():
    """Main function with command line options"""
    monitor = NHAIMonitor()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "once":
            # Run once and exit
            print("Running one-time check...")
            monitor.run_check()
            
        elif command == "monitor":
            # Get interval from command line or use default
            interval = 6  # Default 6 hours
            if len(sys.argv) > 2:
                try:
                    interval = int(sys.argv[2])
                except ValueError:
                    print("Invalid interval, using default 6 hours")
            
            monitor.start_monitoring(interval)
            
        elif command == "help":
            print_help()
            
        else:
            print(f"Unknown command: {command}")
            print_help()
    else:
        # Interactive mode
        print("\nNHAI Circular Auto Monitor")
        print("=" * 40)
        print("1. Run once - Check for new circulars now")
        print("2. Start monitoring - Continuous monitoring")
        print("3. Help - Show usage information")
        print()
        
        choice = input("Enter your choice (1/2/3): ").strip()
        
        if choice == "1":
            monitor.run_check()
        elif choice == "2":
            try:
                interval = int(input("Enter check interval in hours (default 6): ") or "6")
            except ValueError:
                interval = 6
            monitor.start_monitoring(interval)
        elif choice == "3":
            print_help()
        else:
            print("Invalid choice")

def print_help():
    """Print usage help"""
    print("\nNHAI Circular Auto Monitor - Usage:")
    print("=" * 40)
    print("python auto_monitor.py once                - Run single check")
    print("python auto_monitor.py monitor [hours]     - Start monitoring (default: 6 hours)")
    print("python auto_monitor.py help                - Show this help")
    print()
    print("Interactive mode: python auto_monitor.py")
    print()
    print("Files created:")
    print("- output/monitor_log.txt     : Monitoring activity log")
    print("- output/new_circulars.txt   : New circulars found")
    print("- output/existing_links.json : Complete circulars database")
    print("- output/latest_nhai_page.html : Latest downloaded webpage")

if __name__ == "__main__":
    main() 