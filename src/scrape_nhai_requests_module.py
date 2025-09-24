import pandas as pd
import time
import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# --- Configuration ---
TARGET_URL = "https://library.nhai.org/circulars"
OUTPUT_FILENAME = 'nhai_circulars_final.csv'
# --- IMPORTANT: Ensure this path is correct for your system ---
GECKODRIVER_PATH = "/home/ec2-user/nhai_policy_circulars/geckodriver"

def scrape_dropdown_site():
    """
    This script uses a resilient "idempotent" loop to handle the frequent page 
    reloads (postbacks) of the target website by re-finding elements at each step.
    """
    print("--- Initializing Headless Firefox for Dropdown-based Website ---")
    firefox_options = FirefoxOptions()
    firefox_options.add_argument("--headless")
    service = FirefoxService(executable_path=GECKODRIVER_PATH)
    driver = webdriver.Firefox(options=firefox_options, service=service)
    # A longer wait time is safer for complex pages with multiple reloads
    wait = WebDriverWait(driver, 45)
    
    all_circulars_data = []

    try:
        print(f"Navigating to {TARGET_URL}...")
        driver.get(TARGET_URL)

        year_dropdown_id = "MainContent_DropDownList4"
        category_dropdown_id = "MainContent_DropDownList1"
        sub_category_dropdown_id = "MainContent_DropDownList2"
        search_button_id = "MainContent_btn_search"
        
        # Get the number of years to loop through, starting from index 1 to skip the default option
        year_dropdown = wait.until(EC.presence_of_element_located((By.ID, year_dropdown_id)))
        num_years = len(year_dropdown.find_elements(By.TAG_NAME, "option"))

        for i in range(1, num_years):
            # Re-find the year dropdown each time to ensure it's not stale
            year_dropdown = wait.until(EC.element_to_be_clickable((By.ID, year_dropdown_id)))
            year_option = year_dropdown.find_elements(By.TAG_NAME, "option")[i]
            year_text = year_option.text
            print(f"\n===== Processing Year: {year_text} =====")
            year_option.click()

            # Get the number of categories for the selected year
            category_dropdown = wait.until(EC.presence_of_element_located((By.ID, category_dropdown_id)))
            num_categories = len(category_dropdown.find_elements(By.TAG_NAME, "option"))

            for j in range(1, num_categories):
                try:
                    # Idempotent Step: Re-select the year to ensure a clean state
                    wait.until(EC.element_to_be_clickable((By.ID, year_dropdown_id))).find_elements(By.TAG_NAME, "option")[i].click()

                    # Select the category
                    category_dropdown = wait.until(EC.element_to_be_clickable((By.ID, category_dropdown_id)))
                    cat_option = category_dropdown.find_elements(By.TAG_NAME, "option")[j]
                    category_text = cat_option.text
                    print(f"  Processing Category: {category_text}")
                    cat_option.click()

                    # Get the number of sub-categories
                    sub_category_dropdown = wait.until(EC.presence_of_element_located((By.ID, sub_category_dropdown_id)))
                    num_sub_categories = len(sub_category_dropdown.find_elements(By.TAG_NAME, "option"))

                    if num_sub_categories <= 1: # If only the default option exists
                        wait.until(EC.element_to_be_clickable((By.ID, search_button_id))).click()
                        scrape_circulars_from_page(driver, wait, all_circulars_data, year_text, category_text, "N/A")
                        continue

                    for k in range(1, num_sub_categories):
                        # The "Idempotent" core: reset the state completely before the final selection
                        wait.until(EC.element_to_be_clickable((By.ID, year_dropdown_id))).find_elements(By.TAG_NAME, "option")[i].click()
                        wait.until(EC.element_to_be_clickable((By.ID, category_dropdown_id))).find_elements(By.TAG_NAME, "option")[j].click()

                        # Select the final sub-category
                        sub_category_dropdown = wait.until(EC.element_to_be_clickable((By.ID, sub_category_dropdown_id)))
                        sub_option = sub_category_dropdown.find_elements(By.TAG_NAME, "option")[k]
                        sub_category_text = sub_option.text
                        print(f"    Processing Sub-Category: {sub_category_text}")
                        sub_option.click()

                        wait.until(EC.element_to_be_clickable((By.ID, search_button_id))).click()
                        scrape_circulars_from_page(driver, wait, all_circulars_data, year_text, category_text, sub_category_text)
                except (StaleElementReferenceException, TimeoutException):
                    print(f"    Timing error occurred. Skipping one sub-category combination to maintain stability.")
                    continue

    except Exception as e:
        print(f"A critical error occurred: {e}")
        driver.save_screenshot("critical_error_screenshot.png")
        with open("page_source.html", "w", encoding="utf-8") as f: f.write(driver.page_source)
        print("Saved a screenshot and the page's HTML source for debugging.")
    finally:
        print("Closing browser.")
        driver.quit()
        
    return all_circulars_data

def scrape_circulars_from_page(driver, wait, data_list, year, cat, sub_cat):
    """
    Waits for accordion headers, clicks each one to expand it,
    and then scrapes the visible content.
    """
    try:
        accordion_headers_selector = "#faq_accordion .accordion-header"
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, accordion_headers_selector)))
        
        header_elements = driver.find_elements(By.CSS_SELECTOR, accordion_headers_selector)
        num_headers = len(header_elements)
        print(f"      Found {num_headers} circular headers. Expanding each one...")

        for i in range(num_headers):
            try:
                # Re-find all headers in each loop to prevent staleness
                headers = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, accordion_headers_selector)))
                header_button = headers[i].find_element(By.TAG_NAME, "button")
                subject = header_button.text
                
                header_button.click()
                
                content_id = header_button.get_attribute('data-bs-target')
                content_body = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, f"{content_id}.show")))
                
                soup = BeautifulSoup(content_body.get_attribute('innerHTML'), 'lxml')
                
                details = soup.find_all('p')
                circular_no = details[0].strong.next_sibling.strip() if len(details) > 0 and details[0].strong else "N/A"
                circular_date = details[1].strong.next_sibling.strip() if len(details) > 1 and details[1].strong else "N/A"
                pdf_link_tag = soup.find('a', href=True)
                pdf_link = "https://library.nhai.org" + pdf_link_tag['href'] if pdf_link_tag and pdf_link_tag['href'].startswith('/') else (pdf_link_tag['href'] if pdf_link_tag else "N/A")

                data_list.append({
                    'Year': year, 'Category': cat, 'Sub Category': sub_cat, 'Subject': subject,
                    'Circular No': circular_no, 'Circular Date': circular_date, 'PDF Link': pdf_link
                })
                
                # Collapse the item again to keep the page state clean and predictable
                headers[i].find_element(By.TAG_NAME, "button").click()
                time.sleep(0.5)

            except Exception:
                # If a single circular fails to expand or parse, log it and move on
                print(f"      Could not process a circular item. It might be a timing issue.")
                driver.refresh() # Refresh the page to recover from a bad state
                break # Exit the inner loop and move to the next sub-category

    except TimeoutException:
        print("      No circular headers found for this selection.")
    except Exception as e:
        print(f"      An error occurred while scraping results: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    all_circulars = scrape_dropdown_site()
    
    if all_circulars:
        print(f"\n--- Scraping Complete ---")
        # Use multiple columns to define a unique circular, as numbers can be repeated
        df = pd.DataFrame(all_circulars).drop_duplicates(subset=['Circular No', 'Subject', 'Circular Date'])
        print(f"Found a total of {len(df)} unique circulars.")
        # Reorder columns for better readability
        df = df[['Year', 'Category', 'Sub Category', 'Subject', 'Circular No', 'Circular Date', 'PDF Link']]
        df.to_csv(OUTPUT_FILENAME, index=False, encoding='utf-8-sig')
        print(f"Successfully saved data to '{os.path.abspath(OUTPUT_FILENAME)}'")
    else:
        print("\nScraping finished, but no circulars were found.")