# --- RECURSIVE SELENIUM SCRAPER FOR NESTED CATEGORIES (V2: Save one HTML per subcategory, all years combined) ---
# FINAL SCRAPER
# TODO: Schedule cron job to run this every week
import os
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
import time
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.service import Service as FirefoxService
import re
from bs4 import BeautifulSoup

BASE_URL = "https://library.nhai.org/CircularTree"

firefox_options = FirefoxOptions()
firefox_options.add_argument("--headless")
# Set Firefox binary for environments where Firefox isn't on PATH (e.g., cron) — only if executable
firefox_bin = os.environ.get("FIREFOX_BIN") or (
    "/home/ec2-user/nhai_policy_circulars/firefox/firefox" if os.path.exists("/home/ec2-user/nhai_policy_circulars/firefox/firefox") else None
)
if firefox_bin and os.path.isfile(firefox_bin) and os.access(firefox_bin, os.X_OK):
    firefox_options.binary_location = firefox_bin

service = FirefoxService(executable_path="/home/ec2-user/nhai_policy_circulars/geckodriver")
driver = webdriver.Firefox(
    options=firefox_options,
    service=service
)
os.makedirs("output/selenium_circulars", exist_ok=True)

def get_options(select_element):
    return [option for option in select_element.find_elements(By.TAG_NAME, 'option') if option.get_attribute('value') and option.text.strip() and 'All' not in option.text]

def recursive_scrape(level=1, path=None, value_path=None, text_path=None):
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
        if value_path and text_path:
            save_leaf_html(value_path, text_path)
        else:
            print("[DEBUG] Skipping save_leaf_html: empty value_path and text_path")
        return
    options = get_options(select_elem)
    print(f"[Level {level}] Found {len(options)} options: {[o.text.strip() for o in options]}")
    for opt_idx, option in enumerate(options):
        # Wait for overlays to be invisible before clicking dropdowns
        for selector in ['.topbar-info', '.navbar-collapse', '.col-md-9']:
            try:
                WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, selector)))
            except Exception:
                pass
        # Wait for the dropdown itself to be visible and clickable
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.ID, dropdown_id))
        )
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, dropdown_id))
        )
        select_elem = driver.find_element(By.ID, dropdown_id)
        options = get_options(select_elem)
        option = options[opt_idx]
        opt_value = option.get_attribute('value')
        opt_text = option.text.strip()
        print(f"[Level {level}] Selecting option {opt_idx}: '{opt_text}' (value: {opt_value})")
        # Wait for the option to be clickable before clicking
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, f"//select[@id='{dropdown_id}']/option[@value='{opt_value}']"))
        )
        try:
            driver.execute_script("arguments[0].scrollIntoView();", select_elem)
            # Use ActionChains to simulate real user interaction
            actions = ActionChains(driver)
            actions.move_to_element(select_elem).click().perform()
            time.sleep(0.2)
            actions.move_to_element(option).click().perform()
            time.sleep(0.2)
            # Fire change event on the dropdown itself
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_elem)
        except Exception as e:
            print(f"[WARN] ActionChains or JS change event failed for option '{opt_text}', falling back to JS value set: {e}")
            try:
                driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", select_elem, opt_value)
            except Exception as e2:
                print(f"[WARN] JS value set also failed for option '{opt_text}': {e2}")

        # Wait for the next dropdown to update, if it exists
        next_dropdown_id = f"MainContent_DropDownList{level+1}"
        try:
            old_next_options = []
            try:
                next_select_elem = driver.find_element(By.ID, next_dropdown_id)
                old_next_options = [o.get_attribute('value') for o in get_options(next_select_elem)]
            except Exception:
                pass
            def next_dropdown_changed(driver):
                try:
                    next_select_elem = driver.find_element(By.ID, next_dropdown_id)
                    new_options = [o.get_attribute('value') for o in get_options(next_select_elem)]
                    return new_options != old_next_options
                except Exception:
                    return False
            # Wait up to 5s for next dropdown to update
            WebDriverWait(driver, 5).until(next_dropdown_changed)
        except Exception:
            pass

        # Re-locate the dropdown element after DOM update to avoid stale reference
        try:
            select_elem = driver.find_element(By.ID, dropdown_id)
            actual_value = select_elem.get_attribute('value')
            if actual_value != opt_value:
                print(f"[WARN] Dropdown value mismatch: expected {opt_value}, got {actual_value}")
        except Exception as e:
            print(f"[WARN] Could not verify dropdown value for {dropdown_id}: {e}")
        time.sleep(1)
        next_dropdown_id = f"MainContent_DropDownList{level+1}"
        try:
            next_select_elem = driver.find_element(By.ID, next_dropdown_id)
            next_options = get_options(next_select_elem)
            if len(next_options) == 0:
                print(f"[Level {level+1}] Dropdown exists but has 0 options. Saving as leaf node.")
                save_leaf_html(value_path + [opt_value], text_path + [opt_text])
            elif level+1 >= 4 and is_year_dropdown(next_options):
                print(f"[Level {level+1}] Year dropdown detected. Collecting all years for {text_path + [opt_text]}")
                combined_html = ''
                for year_idx, year_option in enumerate(next_options):
                    year_value = year_option.get_attribute('value')
                    year_text = year_option.text.strip()
                    # Use JS to select year and fire change event
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                        next_select_elem, year_value
                    )
                    time.sleep(1)
                    # Click Search
                    try:
                        search_btn = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.ID, 'MainContent_btn_search'))
                        )
                        driver.execute_script("arguments[0].scrollIntoView();", search_btn)
                        # Hide overlays if needed
                        try:
                            driver.execute_script('let el = document.querySelector(".topbar-info"); if (el) { el.style.display = "none"; }')
                        except Exception:
                            pass
                        try:
                            search_btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", search_btn)
                        time.sleep(2)
                    except Exception as e:
                        print(f"[Year {year_text}] Search button not found or not clickable: {e}")
                    # Wait for loader to disappear
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.invisibility_of_element_located((By.CSS_SELECTOR, 'img[alt*="Please Wait"]'))
                        )
                    except Exception:
                        pass
                    # Wait for results to load (accordion)
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "faq_accordion"))
                        )
                        accordion = driver.find_element(By.ID, "faq_accordion")
                        try:
                            innermost = accordion.find_element(By.CSS_SELECTOR, ".multi-collapse.show")
                            html = innermost.get_attribute('outerHTML')
                        except Exception:
                            html = accordion.get_attribute('innerHTML')
                        combined_html += f"\n<!-- Year: {year_text} -->\n" + html
                    except Exception as e:
                        print(f"[Year {year_text}] Could not get results: {e}")
                save_combined_years_html(value_path + [opt_value], text_path + [opt_text], combined_html)
            else:
                recursive_scrape(level+1, path + [opt_idx], value_path + [opt_value], text_path + [opt_text])
        except Exception:
            if value_path and text_path:
                save_leaf_html(value_path + [opt_value], text_path + [opt_text])
            else:
                print("[DEBUG] Skipping save_leaf_html: empty value_path and text_path")

def is_year_dropdown(options):
    return all(opt.text.strip().isdigit() and len(opt.text.strip()) == 4 for opt in options)

def save_combined_years_html(value_path, text_path, combined_html):
    out_dir = 'output/selenium_circulars'
    os.makedirs(out_dir, exist_ok=True)
    # Use only the most specific category number, then joined names
    last_cat_num = ''
    for t in reversed(text_path):
        match = re.match(r'([\d\.]+)', t)
        if match:
            last_cat_num = match.group(1)
            break
    safe_names = [re.sub(r'[^\w\-]+', '_', t.split(' ', 1)[-1]) for t in text_path]
    filename = f"circulars_{last_cat_num}_{'_'.join(safe_names)}.html"
    out_path = os.path.join(out_dir, filename)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(combined_html)
    print(f"Saved combined years HTML: {out_path}")

def save_leaf_html(value_path, text_path):
    wait = WebDriverWait(driver, 10)
    try:
        try:
            # Wait for overlays to be invisible before clicking search
            for selector in ['.topbar-info', '.navbar-collapse', '.col-md-9']:
                try:
                    WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, selector)))
                except Exception:
                    pass
            # Print all selected dropdown values for debugging
            print("[DEBUG] Selected dropdown values before search:")
            for lvl in range(1, 5):
                try:
                    sel = driver.find_element(By.ID, f"MainContent_DropDownList{lvl}")
                    val = sel.get_attribute('value')
                    txt = sel.find_element(By.XPATH, f".//option[@value='{val}']").text
                    print(f"  Level {lvl}: value={val}, text={txt}")
                except Exception:
                    break
            # Always select 'All Year' in the year dropdown if present, using JS to bypass overlays
            year_dropdown_id = "MainContent_DropDownList4"
            try:
                year_select = driver.find_element(By.ID, year_dropdown_id)
                year_options = year_select.find_elements(By.TAG_NAME, 'option')
                if year_options:
                    all_year_value = year_options[0].get_attribute('value')
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                        year_select, all_year_value
                    )
                    print(f"[DEBUG] JS-selected 'All Year' in year dropdown: value={all_year_value}")
                    time.sleep(1)
            except Exception as e:
                print(f"[DEBUG] Could not JS-select 'All Year' in year dropdown: {e}")

            search_btn = driver.find_element(By.ID, "MainContent_btn_search")
            driver.execute_script("arguments[0].scrollIntoView();", search_btn)
            # Hide/remove overlay before clicking search
            try:
                driver.execute_script('let el = document.querySelector(".topbar-info"); if (el) { el.style.display = "none"; }')
            except Exception as e:
                print(f"[DEBUG] Could not hide .topbar-info overlay: {e}")
            # Take a screenshot before saving HTML for debugging
            #screenshot_path = f"output/selenium_circulars/debug_{'_'.join([str(x) for x in value_path])}.png"
            #driver.save_screenshot(screenshot_path)
            #print(f"[DEBUG] Screenshot saved: {screenshot_path}")
            # Get current results HTML before clicking search
            try:
                old_results = driver.find_element(By.ID, "faq_accordion").get_attribute('innerHTML')
            except Exception:
                old_results = None
            # Try normal click, fallback to JS click if intercepted
            try:
                search_btn.click()
            except Exception as e:
                print(f"[DEBUG] Normal click on search_btn failed, trying JS click: {e}")
                try:
                    driver.execute_script("arguments[0].click();", search_btn)
                except Exception as e2:
                    print(f"[DEBUG] JS click on search_btn also failed: {e2}")
            # Wait for loader to disappear (max 20s)
            try:
                WebDriverWait(driver, 20).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, 'img[alt*="Please Wait"]'))
                )
                print("[DEBUG] Loader disappeared, results should be loaded.")
            except Exception as e:
                print(f"[DEBUG] Loader did not disappear in time: {e}")
            # Wait for results to change (max 15s)
            def results_changed(driver):
                try:
                    new_results = driver.find_element(By.ID, "faq_accordion").get_attribute('innerHTML')
                    return new_results != old_results
                except Exception:
                    return False
            WebDriverWait(driver, 15).until(results_changed)
        except Exception as e:
            print(f"Warning: Could not click search button or wait for results for path {' > '.join(text_path)}: {e}")
        wait.until(EC.presence_of_element_located((By.ID, "faq_accordion")))
        accordion = driver.find_element(By.ID, "faq_accordion")
        try:
            innermost = accordion.find_element(By.CSS_SELECTOR, ".multi-collapse.show")
            html = innermost.get_attribute('outerHTML')
        except Exception:
            html = accordion.get_attribute('innerHTML')
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
        # Use only the most specific category number, then joined names
        last_cat_num = ''
        for t in reversed(text_path):
            match = re.match(r'([\d\.]+)', t)
            if match:
                last_cat_num = match.group(1)
                break
        safe_names = [sanitize(t.split(' ', 1)[-1])[:40] for t in text_path]
        fname = f"output/selenium_circulars/circulars_{last_cat_num}_{'_'.join(safe_names)}.html"
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
