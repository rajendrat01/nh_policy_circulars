
# --- RECURSIVE SELENIUM SCRAPER FOR NESTED CATEGORIES ---

import os
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
import time
from selenium.webdriver.firefox.service import Service as FirefoxService
import time
import hashlib
import os
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://library.nhai.org/CircularTree"

firefox_options = FirefoxOptions()
firefox_options.add_argument("--headless")
from selenium.webdriver.firefox.service import Service as FirefoxService
service = FirefoxService(executable_path="/home/ec2-user/nhai_policy_circulars/geckodriver")
driver = webdriver.Firefox(
    options=firefox_options,
    service=service
)
os.makedirs("output/selenium_circulars", exist_ok=True)

def get_options(select_element):
    return [option for option in select_element.find_elements(By.TAG_NAME, 'option') if option.get_attribute('value') and option.text.strip() and 'All' not in option.text]

def recursive_scrape(level=1, path=None, value_path=None, text_path=None):
    """
    Recursively traverse dropdowns. At each level, select each option, then check for a further dropdown.
    If no further dropdown, save the HTML for this leaf node.
    """
    if path is None:
        path = []
    if value_path is None:
        value_path = []
    if text_path is None:
        text_path = []

    wait = WebDriverWait(driver, 20)
    dropdown_id = f"MainContent_DropDownList{level}"
    try:
        select_elem = wait.until(EC.presence_of_element_located((By.ID, dropdown_id)))
    except Exception:
        # No further dropdown at this level: this is a leaf node
        if value_path and text_path:
            save_leaf_html(value_path, text_path)
        else:
            print("[DEBUG] Skipping save_leaf_html: empty value_path and text_path")
        return

    options = get_options(select_elem)
    print(f"[Level {level}] Found {len(options)} options: {[o.text.strip() for o in options]}")
    for opt_idx, option in enumerate(options):
        # Re-fetch dropdown and options each time to avoid staleness
        select_elem = driver.find_element(By.ID, dropdown_id)
        options = get_options(select_elem)
        option = options[opt_idx]
        opt_value = option.get_attribute('value')
        opt_text = option.text.strip()
        print(f"[Level {level}] Selecting option {opt_idx}: '{opt_text}' (value: {opt_value})")
        option.click()
        time.sleep(2)  # Wait for content to load

        # Check if there is a further dropdown at the next level
        next_dropdown_id = f"MainContent_DropDownList{level+1}"
        try:
            next_select_elem = driver.find_element(By.ID, next_dropdown_id)
            next_options = get_options(next_select_elem)
            if len(next_options) == 0:
                # Dropdown exists but has no options: treat as leaf
                print(f"[Level {level+1}] Dropdown exists but has 0 options. Saving as leaf node.")
                save_leaf_html(value_path + [opt_value], text_path + [opt_text])
            elif level+1 >= 4 and is_year_dropdown(next_options):
                # If next dropdown is a year dropdown, save a separate HTML for each year (previous working logic)
                print(f"[Level {level+1}] Year dropdown detected. Saving each year separately for {text_path + [opt_text]}")
                for year_idx, year_option in enumerate(next_options):
                    year_value = year_option.get_attribute('value')
                    year_text = year_option.text.strip()
                    year_option.click()
                    time.sleep(1)
                    # Wait for the Search button to be present and clickable
                    search_btn = None
                    try:
                        search_btn = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.ID, 'MainContent_btnSearch'))
                        )
                    except Exception:
                        # Try to find by button text as fallback
                        try:
                            buttons = driver.find_elements(By.TAG_NAME, 'button')
                            for btn in buttons:
                                if 'search' in btn.text.lower():
                                    search_btn = btn
                                    break
                        except Exception:
                            pass
                    if search_btn:
                        try:
                            driver.execute_script("arguments[0].scrollIntoView();", search_btn)
                            search_btn.click()
                            time.sleep(2)
                        except Exception as e:
                            print(f"[Year {year_text}] Search button present but not clickable: {e}")
                    else:
                        print(f"[Year {year_text}] Search button not found by ID or text.")
                    # Save HTML for this year
                    save_leaf_html(value_path + [opt_value, year_value], text_path + [opt_text, year_text])
            else:
                # If found and has options, recurse to next level
                recursive_scrape(level+1, path + [opt_idx], value_path + [opt_value], text_path + [opt_text])
        except Exception:
            # If not found, this is a leaf node for this path, so save
            save_leaf_html(value_path + [opt_value], text_path + [opt_text])

def is_year_dropdown(options):
    # Heuristic: all options are 4-digit years
    return all(opt.text.strip().isdigit() and len(opt.text.strip()) == 4 for opt in options)




# --- Deduplication state ---
seen_hashes = set()

def save_leaf_html(value_path, text_path):
    global seen_hashes
    wait = WebDriverWait(driver, 10)
    try:
        # Click the 'Search' button to filter the table for the selected year/category/subcategory
        try:
            search_btn = driver.find_element(By.ID, "MainContent_btn_search")
            search_btn.click()
            time.sleep(2)  # Wait for table to update
        except Exception as e:
            print(f"Warning: Could not click search button for path {' > '.join(text_path)}: {e}")
        wait.until(EC.presence_of_element_located((By.ID, "faq_accordion")))
        accordion = driver.find_element(By.ID, "faq_accordion")
        # Try to get the innermost visible .multi-collapse.show (if any)
        try:
            innermost = accordion.find_element(By.CSS_SELECTOR, ".multi-collapse.show")
            html = innermost.get_attribute('outerHTML')
        except Exception:
            html = accordion.get_attribute('innerHTML')
        # Deduplication: hash the HTML content
        html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if html_hash in seen_hashes:
            print(f"Duplicate content for path {' > '.join(text_path)}; skipping save.")
            return
        seen_hashes.add(html_hash)
        # Build filename reflecting the full path, including readable category/subcategory names
        def sanitize(text):
            return (
                text.replace(' ', '_')
                    .replace('/', '_')
                    .replace('(', '')
                    .replace(')', '')
                    .replace('.', '_')
                    .replace('&', 'and')
                    .replace(',', '')
                    .replace('?', '')
                    .replace('=', '')
                    .replace("'", '')
                    .replace('"', '')
            )
        fname = "output/selenium_circulars/circulars"
        for i, (v, t) in enumerate(zip(value_path, text_path)):
            fname += f"_lvl{i+1}-{v}_{sanitize(t)[:40]}"  # limit to 40 chars per part
        fname += ".html"
        print(f"[DEBUG] Saving file: {fname}")
        print(f"[DEBUG] value_path: {value_path}")
        print(f"[DEBUG] text_path: {text_path}")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"<!-- Path: {' > '.join(text_path)} -->\n")
            f.write(html)
        print(f"Saved: {fname}")
    except Exception as e:
        print(f"Failed to save for path {' > '.join(text_path)}: {e}")

def main():
    driver.get(BASE_URL)
    time.sleep(5)
    driver.save_screenshot("output/selenium_debug.png")
    recursive_scrape(level=1, path=[], value_path=[], text_path=[])

if __name__ == "__main__":
    main()
    driver.quit()
