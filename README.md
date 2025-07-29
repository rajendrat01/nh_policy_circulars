# NHAI Circular Scraper

Automated web scraper to monitor and extract new circulars from the National Highways Authority of India (NHAI) website at [library.nhai.org](https://library.nhai.org).

## Features

- ✅ **Automatic HTML Fetching**: Downloads HTML content directly from library.nhai.org
- ✅ **Link Extraction**: Extracts all PDF circular links with metadata (subject, policy number, date)
- ✅ **New Circular Detection**: Compares with existing database to identify new circulars
- ✅ **Scheduled Monitoring**: Continuous monitoring with customizable intervals
- ✅ **Comprehensive Logging**: Activity logs for monitoring and debugging
- ✅ **Multiple Output Formats**: JSON database and readable text reports

## Project Structure

```
nhai_policy_circulars/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── setup.py                  # Setup script
├── .gitignore               # Git ignore rules
├── src/                     # Source code
│   ├── nhai_scraper.py      # Main scraper script
│   ├── auto_monitor.py      # Automated monitoring script
│   └── demo.py              # Demo/testing script
├── data/                    # Input data files
│   └── extracted_links.txt  # Original extracted links reference
├── output/                  # Generated output files
│   ├── existing_links.json  # Complete database of circulars
│   ├── new_circulars.txt    # Latest new circulars found
│   └── latest_nhai_page.html # Downloaded HTML from NHAI website
└── nhai_circulars_env/      # Python virtual environment
```

## Quick Start

### 1. Setup
```bash
python setup.py
```
This will:
- Install all required dependencies
- Create initial baseline of existing circulars
- Set up the monitoring system

### 2. Run Once
```bash
python src/nhai_scraper.py
```
Fetches latest circulars and checks for new ones.

### 3. Start Monitoring
```bash
python src/auto_monitor.py monitor
```
Starts continuous monitoring (default: checks every 6 hours).

## Detailed Usage

### Manual Scraping
```bash
# Run scraper once
python src/nhai_scraper.py

# Check results
cat output/new_circulars.txt  # New circulars found
cat output/existing_links.json  # Complete database
```

### Automated Monitoring
```bash
# Run once and exit
python src/auto_monitor.py once

# Monitor every 6 hours (default)
python src/auto_monitor.py monitor

# Monitor every 2 hours
python src/auto_monitor.py monitor 2

# Interactive mode
python src/auto_monitor.py
```

### Command Line Options
```bash
python src/auto_monitor.py help    # Show all options
```

## Files Created

| File | Description | Location |
|------|-------------|----------|
| `output/existing_links.json` | Complete database of all circulars (JSON format) | Generated |
| `output/new_circulars.txt` | New circulars found in latest check | Generated |
| `output/latest_nhai_page.html` | Raw HTML downloaded from website | Generated |
| `monitor_log.txt` | Activity log for automated monitoring | Generated |
| `data/extracted_links.txt` | Original manual extraction results | Reference data |

### Output Format

### New Circulars (`output/new_circulars.txt`)
```
NEW NHAI CIRCULARS FOUND - 2025-01-11 10:30:15
============================================================

Total New Circulars: 3

1. Subject: Revision of Delegation of Powers -reg.
   Policy No: 1.1.37/2025
   Date: 07.07.2025
   Link: https://library.nhai.org/nhailibrary/Assets/Pdf/1.1.37.pdf
   Direct PDF: nhailibrary/Assets/Pdf/1.1.37.pdf
--------------------------------------------------
```

### Database (`output/existing_links.json`)
```json
[
  {
    "sr_no": "1",
    "subject": "Revision of Delegation of Powers -reg.",
    "policy_no": "1.1.37/2025",
    "date": "07.07.2025",
    "link_path": "nhailibrary/Assets/Pdf/1.1.37.pdf",
    "full_url": "https://library.nhai.org/nhailibrary/Assets/Pdf/1.1.37.pdf",
    "extracted_on": "2025-01-11T10:30:15.123456"
  }
]
```

## How It Works

1. **Fetches HTML**: Downloads the latest HTML from library.nhai.org
2. **Parses Content**: Uses regex to extract circular information from HTML tables
3. **Compares Data**: Checks against existing database to find new circulars
4. **Saves Results**: Updates database and creates reports for new circulars
5. **Schedules Checks**: Automatically repeats at specified intervals

## Categories Monitored

The scraper monitors all NHAI circular categories including:

- **Administration** (Delegation of Powers, Personnel Matters, etc.)
- **Finance & Accounts** (Budget, Payments, Audit, etc.)
- **Technical** (Construction, Maintenance, Quality Control, etc.)
- **Dispute Resolution** (Conciliation, Arbitration, DRB, etc.)
- **Legal Matters** (Land Acquisition, Contracts, etc.)
- **Environment & Safety** (Environmental Clearance, Safety Protocols, etc.)
- **Toll Operations** (Collection, Systems, Policies, etc.)
- **And 11 more categories...**

## Error Handling

- **Network Issues**: Automatic retry with exponential backoff
- **Parsing Errors**: Graceful handling with detailed error messages  
- **File Corruption**: Safe file operations with error recovery
- **Monitoring Failures**: Continues monitoring despite individual failures

## Requirements

- Python 3.7+
- Internet connection
- Dependencies (auto-installed by setup.py):
  - requests
  - beautifulsoup4
  - lxml
  - schedule

## Installation

### Method 1: Automatic Setup
```bash
python setup.py
```

### Method 2: Manual Setup
```bash
pip install -r requirements.txt
python src/nhai_scraper.py  # Create initial baseline
```

## Scheduling Options

### Windows Task Scheduler
Create a scheduled task to run:
```cmd
python D:\path\to\project\src\auto_monitor.py once
```

### Linux Cron
```bash
# Check every 6 hours
0 */6 * * * cd /path/to/project && python src/auto_monitor.py once

# Check daily at 9 AM
0 9 * * * cd /path/to/project && python src/auto_monitor.py once
```

### Keep Monitoring Active
```bash
# Run continuously (will restart on system reboot)
python src/auto_monitor.py monitor 6
```

## Troubleshooting

### Common Issues

1. **"No module named 'requests'"**
   ```bash
   pip install -r requirements.txt
   ```

2. **"Connection Error"**
   - Check internet connection
   - Try again later (website may be temporarily down)

3. **"No new circulars detected"**
   - This is normal - means no new circulars since last check
   - Check `output/existing_links.json` to see all circulars in database

4. **"Permission denied writing files"**
   - Run from a directory where you have write permissions
   - Ensure the `output/` directory exists and is writable

### Debug Mode
Add debug logging by modifying the scraper:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

To extend or modify the scraper:

1. **Add new extraction patterns**: Modify `extract_links_from_html()` in `src/nhai_scraper.py`
2. **Change monitoring intervals**: Modify `src/auto_monitor.py`
3. **Add notifications**: Extend `save_new_circulars()` to send emails/SMS
4. **Export formats**: Add CSV/Excel export options

## License

This project is for educational and monitoring purposes. Please respect the NHAI website's terms of service and implement appropriate rate limiting.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the log files (`monitor_log.txt`)
3. Ensure all dependencies are installed correctly

---

**Last Updated**: July 2025  
**Version**: 2.0.0 