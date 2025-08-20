import requests
from bs4 import BeautifulSoup
import re
import sys
import math
import csv
import os.path
from pathlib import Path
import argparse
import time

# --- Selenium imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, InvalidSessionIdException # Import InvalidSessionIdException

print("Script started!")

# --- Cookie Handling ---
csfd_cookie = ''
if os.path.exists('csfd_cookie.txt'):
    try:
        csfd_cookie = Path('csfd_cookie.txt').read_text(encoding='utf-8').strip('\n')
        print(f"DEBUG: CSFD Cookie loaded (length: {len(csfd_cookie)}).")
    except Exception as e:
        print(f"ERROR: Could not read csfd_cookie.txt: {e}")
        csfd_cookie = ''
else:
    print("DEBUG: csfd_cookie.txt not found. Proceeding without CSFD cookie.")

imdb_cookie = ''
if os.path.exists('imdb_cookie.txt'):
    try:
        imdb_cookie = Path('imdb_cookie.txt').read_text(encoding='latin-1').replace('\n', '').strip()
        print(f"DEBUG: IMDb Cookie loaded (length: {len(imdb_cookie)}).")
    except Exception as e:
        print(f"ERROR: Could not read imdb_cookie.txt: {e}")
        imdb_cookie = ''
else:
    print("DEBUG: imdb_cookie.txt not found. Proceeding without IMDb cookie.")

# --- Request Headers (Primarily for requests.get, less so for Selenium's direct page load) ---
try:
    payload = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cookie': csfd_cookie,
    }
    print(f"DEBUG: Payload created (User-Agent: {payload['User-Agent'][:20]}...).")
except Exception as e:
    print(f"ERROR: Could not create payload: {e}")
    sys.exit(1)

# Global variables to be set after parsing arguments or prompting
user_id = None
user_name = "Unknown User"
nbsp = u'\xa0' # Non-breaking space character

# --- Selenium Helper Functions (New) ---

def get_driver(driver_path="chromedriver.exe"):
    """Initializes and returns a new Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run Chrome in headless mode (no GUI)
    chrome_options.add_argument("--disable-gpu") # Recommended for headless on Windows
    chrome_options.add_argument("--no-sandbox") # Recommended for Linux/Docker
    chrome_options.add_argument("--disable-dev-shm-usage") # Overcome limited resource problems
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging']) # Suppress DevTools logs
    # To suppress the WebGL depreciation error message (as seen in your traceback):
    chrome_options.add_argument("--enable-unsafe-swiftshader") # Opt-in to software WebGL, might suppress error.
    
    try:
        service = Service(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        # Add implicit wait for general element availability
        driver.implicitly_wait(10) 
        print("DEBUG: ChromeDriver successfully initialized.")
        return driver
    except WebDriverException as e:
        print(f"CRITICAL ERROR: Could not start ChromeDriver. Make sure '{driver_path}' is in the script directory and matches your Chrome browser version. Error: {e}")
        return None # Indicate a fatal error in driver initialization

def login_csfd(driver, username, password_ignored=None): # password_ignored for consistency, not used in actual login
    """
    Logs into CSFD using the provided cookie or a fresh login if cookie is invalid.
    This function is primarily a placeholder. Current script relies on requests cookie
    for main page fetching, and Selenium for detail pages.
    If Selenium browser session requires active login, implement it here.
    """
    print("DEBUG: Assuming CSFD cookie from payload is sufficient for initial access.")
    return True # Assume success for now. Real login would go here if needed.


# --- Helper Functions ---

# Function to get detailed movie info (Director, Country, Overall Rating, Actors) using Selenium
def get_movie_detail_info(movie_id, driver): # Removed driver_path, as driver is passed in
    """
    Fetches detailed movie information using Selenium.
    Returns:
        dict: Movie details if successful.
        "REINITIALIZE_DRIVER": If InvalidSessionIdException occurs, signaling caller to re-init driver.
        None: If general timeout or other unhandled errors occur after retries.
    """
    link = f"https://www.csfd.cz/film/{movie_id}/prehled/"
    print(f"\nAttempting to fetch movie detail for ID {movie_id} using Selenium from: {link}")
    
    retries = 3 # Retries for general loading issues (TimeoutException, NoSuchElementException)
    for attempt in range(retries):
        try:
            driver.get(link)

            # --- Handle Cookie Consent Pop-up (CSFD often has one) ---
            try:
                consent_button = WebDriverWait(driver, 5).until( # Shorter wait for consent, if it's there, it's quick
                    EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")) # This is the ID from your script
                )
                consent_button.click()
                print("DEBUG: Clicked consent button.")
                time.sleep(1) # Give it a moment to dismiss
            except TimeoutException:
                # print("DEBUG: No consent button found within timeout (normal if already consented).")
                pass 
            except NoSuchElementException:
                # print("DEBUG: Consent button element not found (normal if already consented).")
                pass
            except InvalidSessionIdException as e:
                # Catch this specifically if it happens during consent button click
                print(f"ERROR: Invalid Selenium session while trying to click consent button for movie ID {movie_id}. Browser crashed/disconnected. {e}")
                return "REINITIALIZE_DRIVER" # Signal re-initialization
            except Exception as e:
                print(f"DEBUG: An unexpected error occurred while trying to click consent button for movie ID {movie_id}: {e}")

            # --- Wait for the main 'creators' block to ensure content is loaded ---
            # Using try-except for the main wait as well, to catch issues there
            try:
                WebDriverWait(driver, 15).until( # Reduced timeout from 20 to 15, should be enough.
                    EC.presence_of_element_located((By.ID, "creators"))
                )
                print(f"DEBUG: 'creators' block found for movie ID {movie_id}, indicating main content loaded.")
            except TimeoutException:
                print(f"ERROR: Timeout waiting for 'creators' block for movie ID {movie_id}. Page might not have loaded correctly.")
                raise TimeoutException # Re-raise to trigger retry
            except InvalidSessionIdException as e:
                print(f"ERROR: Invalid Selenium session waiting for creators block for movie ID {movie_id}. Browser crashed/disconnected. {e}")
                return "REINITIALIZE_DRIVER"


            page_source = driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            countries = "N/A"
            directors = "N/A"
            overall_rating = "N/A"
            actor1 = "N/A"
            actor2 = "N/A"

            # --- Country of Origin (from div class="origin") ---
            origin_div = soup.find('div', class_='origin')
            if origin_div:
                country_links = origin_div.find_all('a', href=re.compile(r'/zeme/'))
                if country_links:
                    countries = ", ".join([c.get_text(strip=True) for c in country_links])
                else:
                    # Fallback for plain text countries if no links
                    origin_text = origin_div.get_text(separator=' ', strip=True)
                    match = re.match(r'(.+?)\s*/\s*\d{4}', origin_text)
                    if match:
                        countries = match.group(1).strip()
                    elif ' / ' in origin_text:
                        countries = origin_text.split(' / ')[0].strip()
                    elif re.match(r'^[A-Za-z\s]+, \d{4}', origin_text):
                        countries = origin_text.split(',')[0].strip()

            # --- Directors (from div id="creators" > h4 'Režie:') ---
            creators_div = soup.find('div', id='creators')
            if creators_div:
                director_h4 = creators_div.find('h4', string='Režie:')
                if director_h4:
                    parent_div_of_h4 = director_h4.find_parent('div')
                    if parent_div_of_h4:
                        director_tags = parent_div_of_h4.find_all('a', href=re.compile(r'/tvurce/'))
                        if director_tags:
                            directors = ", ".join([d.get_text(strip=True) for d in director_tags])

            # --- Overall Rating (from div class="film-rating-average") ---
            rating_div = soup.find('div', class_='film-rating-average')
            if rating_div:
                overall_rating = rating_div.get_text(strip=True)

            # --- First two actors (from div id="creators" > h4 'Hrají:') ---
            if creators_div: # Re-use the already found creators_div
                actor_h4 = creators_div.find('h4', string='Hrají:')
                if actor_h4:
                    parent_div_of_h4 = actor_h4.find_parent('div')
                    if parent_div_of_h4:
                        actor_tags = parent_div_of_h4.find_all('a', href=re.compile(r'/tvurce/'))
                        actor_tags = [tag for tag in actor_tags if tag.get_text(strip=True) != 'více'] # Filter 'více' link
                        
                        if len(actor_tags) > 0:
                            actor1 = actor_tags[0].get_text(strip=True)
                        if len(actor_tags) > 1:
                            actor2 = actor_tags[1].get_text(strip=True)

            return {
                "countries": countries,
                "directors": directors,
                "overall_rating": overall_rating,
                "actor1": actor1,
                "actor2": actor2
            }

        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error loading movie detail for ID {movie_id} on attempt {attempt + 1}: {e}. Retrying...")
            time.sleep(2 * (attempt + 1))
        except InvalidSessionIdException as e:
            print(f"ERROR: Invalid Selenium session for ID {movie_id}. Browser crashed/disconnected. {e}")
            return "REINITIALIZE_DRIVER" # Signal to the caller that the driver needs re-initialization
        except Exception as e:
            print(f"An unexpected error occurred fetching detail for ID {movie_id} on attempt {attempt + 1}: {e}. Retrying...")
            time.sleep(2 * (attempt + 1))

    print(f"Failed to fetch movie details for ID {movie_id} after {retries} attempts.")
    return None # Return None if all general retries fail


def get_csfd_ratings():
    global user_id
    rating_url = f'https://www.csfd.cz/uzivatel/{user_id}/hodnoceni/'
    print(f"Attempting to fetch ratings from: {rating_url}")
    grab = requests.get(rating_url, headers=payload)
    print(f"Ratings page HTTP Status Code: {grab.status_code}")
    
    if grab.status_code != 200:
        print(f"Error: Failed to access ratings page. Status code: {grab.status_code}. Make sure your CSFD cookie is valid for user ID {user_id}.")
        return

    soup = BeautifulSoup(grab.text, 'html.parser')
    
    header_box = soup.find('header', {'class':'box-header'})
    if not header_box:
        print("DEBUG: Could not find <header class='box-header'> on the ratings page. Exiting ratings scrape.")
        return

    pages_str_tag = header_box.find('h2')
    if not pages_str_tag:
        print("DEBUG: Could not find <h2> tag inside <header class='box-header'> on the ratings page. Exiting ratings scrape.")
        return
    
    pages_str = pages_str_tag.text.strip()
    print(f"DEBUG: Raw text from ratings page header h2: '{pages_str}'")

    match = re.search(r'\((\d[\d\s]*)\)', pages_str)
    if not match:
        match = re.search(r'(\d+)', pages_str)
    
    if match:
        raw_pages_count = re.sub(r'\s+', '', match.group(1))
        try:
            pages = int(raw_pages_count)
        except ValueError:
            print(f"DEBUG: Failed to convert '{raw_pages_count}' to integer. Exiting ratings scrape.")
            return
    else:
        print("DEBUG: Regex failed to find a numerical count in the header string.")
        print(f"DEBUG: String for regex: '{pages_str}'")
        print("Could not determine total number of ratings pages. Check if user has any ratings or if CSFD HTML changed.")
        return

    num_pages = math.ceil(pages / 50)
    print(f"Total ratings found: {pages}. Will process {num_pages} pages.")
    
    # Define fieldnames explicitly for the CSV header
    fieldnames = ['csfd_id', 'title', 'year', 'countries', 'directors', 'overall_rating', 'actor1', 'actor2', 'date', 'rating']

    # --- Resume Logic: Read already processed movie IDs ---
    processed_movie_ids = set()
    csv_file_path = "csfd_ratings.csv"
    file_exists = os.path.exists(csv_file_path)
    
    if file_exists and os.path.getsize(csv_file_path) > 0: # Check if file exists AND is not empty
        try:
            with open(csv_file_path, "r", encoding="utf-8", newline='') as f_check:
                reader_check = csv.DictReader(f_check, delimiter=';')
                # Check if header matches expected fieldnames
                if reader_check.fieldnames and reader_check.fieldnames != fieldnames:
                    print("WARNING: CSV header mismatch for ratings. Existing file header:", reader_check.fieldnames)
                    print("Expected header:", fieldnames)
                    print("This might indicate a problem with the file structure. Consider deleting and restarting if data integrity is a concern.")
                    # If you want to force overwrite on header mismatch, uncomment next line:
                    # file_exists = False 
                
                # Only read if the header is compatible or if we're ignoring header mismatch for reading
                if reader_check.fieldnames and 'csfd_id' in reader_check.fieldnames:
                    for row in reader_check:
                        if row.get('csfd_id'): # Ensure 'csfd_id' key exists and has a value
                            processed_movie_ids.add(row['csfd_id'])
                else:
                    print(f"WARNING: '{csv_file_path}' has no 'csfd_id' column or is malformed. Cannot resume from it.")
                    file_exists = False # Treat as if file doesn't exist to write new header
            print(f"DEBUG: Resuming. Found {len(processed_movie_ids)} already processed movie IDs in '{csv_file_path}'.")
        except Exception as e:
            print(f"ERROR: Could not read existing '{csv_file_path}' for resuming. Starting fresh. Error: {e}")
            file_exists = False
    else:
        print(f"DEBUG: '{csv_file_path}' not found or is empty. Starting fresh.")
        file_exists = False # Ensure header is written if file is new or empty

    driver = None # Initialize driver outside the loop to manage its lifecycle
    driver_path = "chromedriver.exe" # Define driver_path here

    try:
        driver = get_driver(driver_path)
        if not driver: # If driver initialization failed
            print("Failed to initialize Selenium driver. Cannot proceed with ratings scraping.")
            return

        with open(csv_file_path, "a" if file_exists else "w", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            if not file_exists: # Write header only if file didn't exist or was empty/malformed
                writer.writeheader()
                print(f"Wrote header to new CSV file '{csv_file_path}'.")

            for i in range(1, num_pages + 1): # Always iterate through all pages, skipping individual movies later
                urls = f'https://www.csfd.cz/uzivatel/{user_id}/hodnoceni/?page={i}'
                print(f"Fetching ratings page {i}/{num_pages} from {urls}")
                try:
                    grab = requests.get(urls, headers=payload)
                    grab.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                except requests.exceptions.RequestException as e:
                    print(f"ERROR: Could not fetch ratings page {i} from CSFD: {e}. Skipping this page.")
                    continue

                soup = BeautifulSoup(grab.text, 'html.parser')
                
                movies_on_page = soup.find_all('div', {'class':'tab-content user-tab-rating'})
                if not movies_on_page:
                    print(f"WARNING: No movie rating content found on page {i}. HTML structure might have changed or page is empty.")
                    continue

                for div in movies_on_page:
                    for ratings_tr in div.find_all('tr'):
                        a_tag = ratings_tr.find('a', {'class':'film-title-name'})
                        if not a_tag:
                            continue

                        name = a_tag.text.strip()
                        href = a_tag['href']
                        # Ensure csfd_id extraction is robust
                        csfd_id_match = re.search(r'/film/(\d+)-', href)
                        csfd_id = csfd_id_match.group(1) if csfd_id_match else None

                        if not csfd_id:
                            print(f"WARNING: Could not extract CSFD ID from URL: {href}. Skipping this movie.")
                            continue

                        if csfd_id in processed_movie_ids:
                            print(f"DEBUG: Skipping already processed movie ID {csfd_id}: {name}")
                            continue

                        year_tag = ratings_tr.find('span', {'class':'info'})
                        year = year_tag.text.replace('(', '').replace(')', '').strip() if year_tag else "N/A"
                        
                        date_tag = ratings_tr.find('td', {'class':'date-only'})
                        date = date_tag.text.replace('\n', '').replace('\t', '').strip() if date_tag else "N/A"
                        
                        stars = str(ratings_tr.find('span', {'class':'star-rating'}))
                        stars_help = stars.split('span class=\"stars ')[1].split('\">')[0] if 'span class="stars' in stars else ''
                        
                        rating = '0'
                        if stars_help == 'stars-5': rating = '100'
                        elif stars_help == 'stars-4': rating = '80'
                        elif stars_help == 'stars-3': rating = '60'
                        elif stars_help == 'stars-2': rating = '40'
                        elif stars_help == 'stars-1': rating = '20'

                        # --- Robust Movie Detail Fetch with Driver Re-initialization ---
                        movie_details = None
                        re_init_attempts_movie = 3 # Max attempts to re-initialize driver for *this specific movie's details*
                        for attempt_re_init in range(re_init_attempts_movie):
                            movie_details = get_movie_detail_info(csfd_id, driver) # Pass driver
                            
                            if movie_details == "REINITIALIZE_DRIVER":
                                print(f"Driver session invalidated for ID {csfd_id}. Attempting re-initialization {attempt_re_init + 1}/{re_init_attempts_movie}...")
                                if driver: # Ensure driver is quit before re-initializing
                                    try:
                                        driver.quit()
                                        print("DEBUG: Old driver session quit.")
                                    except WebDriverException as e:
                                        print(f"WARNING: Error quitting old driver during re-initialization: {e}")
                                driver = get_driver(driver_path) # Get a new driver
                                if not driver:
                                    print(f"CRITICAL ERROR: Failed to re-initialize driver after multiple attempts for ID {csfd_id}. Skipping movie and trying next.")
                                    movie_details = None # Set to None to skip writing
                                    break # Break from re-init loop
                                time.sleep(1) # Small delay before retrying current movie
                                continue # Go to next detail_attempt loop iteration for the current movie
                            elif movie_details is not None:
                                break # Details successfully fetched, break from inner retry loop
                            else: # movie_details is None (general failure after retries in get_movie_detail_info)
                                print(f"Failed to get movie details for ID {csfd_id} after all attempts (including re-initialization). Skipping this movie.")
                                break # Break from inner retry loop and skip this movie

                        if movie_details is None: # If movie_details is still None after all re-initialization attempts
                            print(f"WARNING: Skipping movie ID {csfd_id} ('{name}') due to persistent failure in fetching details.")
                            # Optionally, write a row with just ID and status for tracking failures
                            # writer.writerow({'csfd_id': csfd_id, 'title': name, 'status': 'detail_fetch_failed'})
                            continue # Skip writing this movie

                        row_data = {
                            'csfd_id': csfd_id,
                            'title': name,
                            'year': year,
                            'countries': movie_details.get('countries', 'N/A'),
                            'directors': movie_details.get('directors', 'N/A'),
                            'overall_rating': movie_details.get('overall_rating', 'N/A'),
                            'actor1': movie_details.get('actor1', 'N/A'),
                            'actor2': movie_details.get('actor2', 'N/A'),
                            'date': date,
                            'rating': rating
                        }
                        
                        try:
                            writer.writerow(row_data)
                            f.flush() # Flush to OS buffer
                            os.fsync(f.fileno()) # Force write to disk (important for resume robustness)
                            processed_movie_ids.add(csfd_id) # Add to processed set
                            print(f"Successfully wrote data for movie ID {csfd_id}: {name}")
                        except Exception as write_err:
                            print(f"ERROR: Failed to write row for movie ID {csfd_id} to CSV: {write_err}")

                        time.sleep(0.5) # Delay after fetching movie details (Selenium part)

                time.sleep(1.5) # Delay between pages of ratings
    finally:
        if driver:
            try:
                driver.quit()
                print("DEBUG: Selenium driver quit.")
            except WebDriverException as e:
                print(f"WARNING: Error quitting driver at end of ratings function: {e}")

    try:
        num_lines_csfd = sum(1 for line in open(csv_file_path, encoding="utf-8")) - 1
        print(32 * "-")
        print(f"Found {num_lines_csfd} ratings")
        print(32 * "=")
    except Exception as e:
        print(f"ERROR: Could not count lines in '{csv_file_path}': {e}")
        print(32 * "=")
    
def get_csfd_reviews():
    global user_id
    review_url = f'https://www.csfd.cz/uzivatel/{user_id}/recenze/'
    print(f"Attempting to fetch reviews from: {review_url}")
    grab = requests.get(review_url, headers=payload)
    print(f"Reviews page HTTP Status Code: {grab.status_code}")

    if grab.status_code != 200:
        print(f"Error: Failed to access reviews page. Status code: {grab.status_code}. Make sure your CSFD cookie is valid for user ID {user_id}.")
        return

    soup = BeautifulSoup(grab.text, 'html.parser')
    
    pages_str_tag = soup.find('header', {'class':'box-header'})
    if not pages_str_tag:
        print("DEBUG: Could not find <header class='box-header'> on the reviews page. Exiting reviews scrape.")
        return

    pages_str_h2 = pages_str_tag.find('h2')
    if not pages_str_h2:
        print("DEBUG: Could not find <h2> tag inside <header class='box-header'> on the reviews page. Exiting reviews scrape.")
        return
    
    pages_str = pages_str_h2.text.strip()
    print(f"DEBUG: Raw text from reviews page header h2: '{pages_str}'")

    match = re.search(r'\((\d[\d\s]*)\)', pages_str)
    if not match:
        match = re.search(r'(\d+)', pages_str)

    if match:
        raw_pages_count = re.sub(r'\s+', '', match.group(1))
        try:
            pages = int(raw_pages_count)
        except ValueError:
            print(f"DEBUG: Failed to convert '{raw_pages_count}' to integer. Exiting reviews scrape.")
            return
    else:
        print("DEBUG: Regex failed to find a numerical count in the header string.")
        print(f"DEBUG: String for regex: '{pages_str}'")
        print("Could not determine total number of review pages. Check if user has any reviews or if CSFD HTML changed.")
        return

    num_pages = math.ceil(pages / 10) # 10 reviews per page
    print(f"Total reviews found: {pages}. Will process {num_pages} pages.")

    # Define fieldnames explicitly for the CSV header
    fieldnames = ['csfd_id', 'title', 'year', 'countries', 'directors', 'overall_rating', 'actor1', 'actor2', 'date', 'rating', 'review']

    # --- Resume Logic: Read already processed movie IDs for reviews ---
    processed_movie_ids = set()
    csv_file_path = "csfd_reviews.csv"
    file_exists = os.path.exists(csv_file_path)
    
    if file_exists and os.path.getsize(csv_file_path) > 0: # Check if file exists AND is not empty
        try:
            with open(csv_file_path, "r", encoding="utf-8", newline='') as f_check:
                reader_check = csv.DictReader(f_check, delimiter=';')
                # Check if header matches expected fieldnames
                if reader_check.fieldnames and reader_check.fieldnames != fieldnames:
                    print("WARNING: CSV header mismatch for reviews. Existing file header:", reader_check.fieldnames)
                    print("Expected header:", fieldnames)
                    print("This might indicate a problem with the file structure. Consider deleting and restarting if data integrity is a concern.")
                    # If you want to force overwrite on header mismatch, uncomment next line:
                    # file_exists = False 
                
                if reader_check.fieldnames and 'csfd_id' in reader_check.fieldnames:
                    for row in reader_check:
                        if row.get('csfd_id'):
                            processed_movie_ids.add(row['csfd_id'])
                else:
                    print(f"WARNING: '{csv_file_path}' has no 'csfd_id' column or is malformed. Cannot resume from it.")
                    file_exists = False
            print(f"DEBUG: Resuming reviews. Found {len(processed_movie_ids)} already processed movie IDs in '{csv_file_path}'.")
        except Exception as e:
            print(f"ERROR: Could not read existing '{csv_file_path}' for resuming reviews. Starting fresh. Error: {e}")
            file_exists = False
    else:
        print(f"DEBUG: '{csv_file_path}' not found or is empty. Starting fresh.")
        file_exists = False # Ensure header is written if file is new or empty
    
    driver = None # Initialize driver outside the loop to manage its lifecycle
    driver_path = "chromedriver.exe" # Define driver_path here

    try:
        driver = get_driver(driver_path)
        if not driver:
            print("Failed to initialize Selenium driver. Cannot proceed with reviews scraping.")
            return

        with open(csv_file_path, "a" if file_exists else "w", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            if not file_exists: # Write header only if file didn't exist or was empty/malformed
                writer.writeheader()
                print(f"Wrote header to new CSV file '{csv_file_path}'.")

            for i in range(1, num_pages + 1):
                urls = f'https://www.csfd.cz/uzivatel/{user_id}/recenze/?page={i}'
                print(f"Fetching reviews page {i}/{num_pages} from {urls}")
                try:
                    grab = requests.get(urls, headers=payload)
                    grab.raise_for_status()
                except requests.exceptions.RequestException as e:
                    print(f"ERROR: Could not fetch reviews page {i} from CSFD: {e}. Skipping this page.")
                    continue

                soup = BeautifulSoup(grab.text, 'html.parser')
                
                reviews_on_page = soup.find_all('div', {'class':'tab-content'})
                if not reviews_on_page:
                    print(f"WARNING: No review content found on page {i}. HTML structure might have changed or page is empty.")
                    continue

                for div in reviews_on_page:
                    for reviews_div in div.find_all('div', {'class':'article-content article-content-justify'}):
                        a_tag = reviews_div.find('a', {'class':'film-title-name'})
                        if not a_tag:
                            continue

                        name = a_tag.text.strip()
                        href = a_tag['href']
                        # Ensure csfd_id extraction is robust
                        csfd_id_match = re.search(r'/film/(\d+)-', href)
                        csfd_id = csfd_id_match.group(1) if csfd_id_match else None

                        if not csfd_id:
                            print(f"WARNING: Could not extract CSFD ID from URL: {href}. Skipping this review.")
                            continue

                        if csfd_id in processed_movie_ids:
                            print(f"DEBUG: Skipping already processed review for movie ID {csfd_id}: {name}")
                            continue

                        year_tag = reviews_div.find('span', {'class':'info'})
                        year = year_tag.text.replace('(', '').replace(')', '').strip() if year_tag else "N/A"
                        
                        date_tag = reviews_div.find('time')
                        date = date_tag.text.strip() if date_tag else "N/A"
                        
                        review_text_tag = reviews_div.find('div', {'class':'user-reviews-text'})
                        review = review_text_tag.get_text(separator=' ', strip=True).replace(';', ',') if review_text_tag else "" # Use get_text to handle nested tags
                        
                        rating = 'n/a'
                        try:
                            stars_tag = reviews_div.find('span', {'class':'star-rating'})
                            if stars_tag:
                                stars_class = stars_tag.get('class', [])
                                stars_help = next((s.replace('stars-', '') for s in stars_class if 'stars-' in s), None)
                                
                                if stars_help == '5': rating = '100'
                                elif stars_help == '4': rating = '80'
                                elif stars_help == '3': rating = '60'
                                elif stars_help == '2': rating = '40'
                                elif stars_help == '1': rating = '20'
                        except Exception:
                            pass

                        # --- Robust Movie Detail Fetch with Driver Re-initialization ---
                        movie_details = None
                        re_init_attempts_movie = 3 # Max attempts to re-initialize driver for this movie
                        for attempt_re_init in range(re_init_attempts_movie):
                            movie_details = get_movie_detail_info(csfd_id, driver) # Pass driver
                            
                            if movie_details == "REINITIALIZE_DRIVER":
                                print(f"Driver session invalidated for ID {csfd_id}. Attempting re-initialization {attempt_re_init + 1}/{re_init_attempts_movie}...")
                                if driver:
                                    try:
                                        driver.quit()
                                        print("DEBUG: Old driver session quit.")
                                    except WebDriverException as e:
                                        print(f"WARNING: Error quitting old driver during re-initialization: {e}")
                                driver = get_driver(driver_path) # Get a new driver
                                if not driver:
                                    print(f"CRITICAL ERROR: Failed to re-initialize driver after multiple attempts for ID {csfd_id}. Skipping movie and trying next.")
                                    movie_details = None
                                    break
                                time.sleep(1)
                                continue
                            elif movie_details is not None:
                                break
                            else:
                                print(f"Failed to get movie details for ID {csfd_id} after all attempts (including re-initialization). Skipping this movie.")
                                break

                        if movie_details is None:
                            print(f"WARNING: Skipping movie ID {csfd_id} ('{name}') due to persistent failure in fetching details for review.")
                            continue

                        row_data = {
                            'csfd_id': csfd_id,
                            'title': name,
                            'year': year,
                            'countries': movie_details.get('countries', 'N/A'),
                            'directors': movie_details.get('directors', 'N/A'),
                            'overall_rating': movie_details.get('overall_rating', 'N/A'),
                            'actor1': movie_details.get('actor1', 'N/A'),
                            'actor2': movie_details.get('actor2', 'N/A'),
                            'date': date,
                            'rating': rating,
                            'review': review
                        }
                        
                        try:
                            writer.writerow(row_data)
                            f.flush()
                            os.fsync(f.fileno())
                            processed_movie_ids.add(csfd_id)
                            print(f"Successfully wrote review data for movie ID {csfd_id}: {name}")
                        except Exception as write_err:
                            print(f"ERROR: Failed to write review row for movie ID {csfd_id} to CSV: {write_err}")

                        time.sleep(0.5)
                time.sleep(1.5) # Delay between pages of reviews
    finally:
        if driver:
            try:
                driver.quit()
                print("DEBUG: Selenium driver quit.")
            except WebDriverException as e:
                print(f"WARNING: Error quitting driver at end of reviews function: {e}")

    try:
        num_lines_csfd = sum(1 for line in open(csv_file_path, encoding="utf-8")) - 1
        print(32 * "-")
        print(f"Found {num_lines_csfd} reviews")
        print(32 * "=")
    except Exception as e:
        print(f"ERROR: Could not count lines in '{csv_file_path}': {e}")
        print(32 * "=")

def get_imdb_links():
    # Adjusted to load existing links for resuming
    imdb_links_file = 'csfd_imdb_links.csv'
    no_imdb_links_file = 'csfd_no_imdb_link.csv'

    existing_imdb_ids = set()
    file_exists = os.path.exists(imdb_links_file) and os.path.getsize(imdb_links_file) > 0
    if file_exists:
        try:
            with open(imdb_links_file, "r", encoding="utf-8", newline='') as f_check:
                reader_check = csv.DictReader(f_check, delimiter=',')
                if reader_check.fieldnames and 'csfd_id' in reader_check.fieldnames:
                    for row in reader_check:
                        if row.get('csfd_id'):
                            existing_imdb_ids.add(row['csfd_id'])
            print(f"DEBUG: Resuming IMDb link extraction. Found {len(existing_imdb_ids)} already processed IMDb links.")
        except Exception as e:
            print(f"ERROR: Could not read existing '{imdb_links_file}' for resuming. Starting fresh. Error: {e}")
            file_exists = False
    else:
        print(f"DEBUG: '{imdb_links_file}' not found or empty. Starting fresh for IMDb links.")
        file_exists = False

    if not os.path.exists('csfd_ratings.csv'):
        print("Error: 'csfd_ratings.csv' not found. Please run option 1 first.")
        return

    # Load all CSFD IDs from ratings file that need IMDb links
    all_csfd_ids_from_ratings = set()
    try:
        with open('csfd_ratings.csv', encoding="utf8", newline='') as movies_file:
            reader = csv.reader(movies_file, delimiter=';')
            header = next(reader, None) # Skip header
            if header: # Check if header exists and 'csfd_id' is in it
                csfd_id_index = header.index('csfd_id') if 'csfd_id' in header else -1
            else:
                csfd_id_index = 0 # Assume first column if no header or header missing 'csfd_id'
            
            if csfd_id_index != -1:
                for row in reader:
                    if row and len(row) > csfd_id_index:
                        all_csfd_ids_from_ratings.add(row[csfd_id_index])
            else:
                print("WARNING: 'csfd_ratings.csv' does not seem to contain 'csfd_id' column for linking.")
                return # Cannot proceed without IDs
    except Exception as e:
        print(f"ERROR: Could not read 'csfd_ratings.csv': {e}. Cannot proceed with IMDb linking.")
        return

    # Filter out already processed IDs
    links_to_process = sorted(list(all_csfd_ids_from_ratings - existing_imdb_ids), key=int)
    print(f"Found {len(links_to_process)} CSFD IDs to process for IMDb links.")
            
    # Open files for appending or writing new header
    imdb_link_fieldnames = ['csfd_id', 'imdb_id', 'csfd_rating']
    no_imdb_link_fieldnames = ['csfd_id', 'reason', 'csfd_rating']

    with open(imdb_links_file, "a" if file_exists else "w", encoding="utf-8", newline='') as f_imdb_links, \
         open(no_imdb_links_file, "a" if file_exists else "w", encoding="utf-8", newline='') as f_no_imdb_links:
        
        imdb_link_writer = csv.writer(f_imdb_links, delimiter=',')
        no_imdb_link_writer = csv.writer(f_no_imdb_links, delimiter=',')

        if not file_exists: # Write headers if starting fresh
            imdb_link_writer.writerow(imdb_link_fieldnames)
            no_imdb_link_writer.writerow(no_imdb_link_fieldnames)
            print(f"Created new CSV files '{imdb_links_file}' and '{no_imdb_links_file}' with headers.")

        for csfd_id in links_to_process:
            urls = f'https://www.csfd.cz/film/{csfd_id}'
            print(f"Fetching IMDb link for CSFD ID: {csfd_id} from {urls}")
            try:
                grab = requests.get(urls, headers=payload)
                grab.raise_for_status() # Raise HTTPError for bad responses
            except requests.exceptions.RequestException as e:
                print(f"ERROR: Could not fetch CSFD page for IMDb link extraction for ID {csfd_id}: {e}. Skipping.")
                no_imdb_link_writer.writerow([csfd_id, f"CSFD page fetch error: {e}", "N/A"])
                f_no_imdb_links.flush()
                os.fsync(f_no_imdb_links.fileno())
                time.sleep(2) # Still pause to avoid hammering
                continue

            soup = BeautifulSoup(grab.text, 'html.parser')

            imdb_link = None
            csfd_rating = "N/A"
            
            try:
                rating_element = soup.select_one('a[href="#close-dropdown"]')
                if rating_element and 'data-rating' in rating_element.attrs:
                    csfd_rating = rating_element['data-rating']

                imdb_link_tag = soup.select_one('a.button.button-big.button-imdb')
                if imdb_link_tag and 'href' in imdb_link_tag.attrs:
                    imdb_link = imdb_link_tag['href']
            except Exception as e:
                print(f"WARNING: Error parsing IMDb link/rating for ID {csfd_id}: {e}")
                # Don't skip, try to write what we have
                pass

            if imdb_link:
                try:
                    imdb_id_match = re.search(r'/title/(tt\d+)/', imdb_link)
                    imdb_id = imdb_id_match.group(1) if imdb_id_match else None
                    if imdb_id:
                        imdb_link_writer.writerow([csfd_id, imdb_id, csfd_rating])
                        f_imdb_links.flush()
                        os.fsync(f_imdb_links.fileno())
                        print(f"Found IMDb link for {csfd_id}: {imdb_id}")
                    else:
                        no_imdb_link_writer.writerow([csfd_id, "IMDb ID parsing error (regex mismatch)", csfd_rating])
                        f_no_imdb_links.flush()
                        os.fsync(f_no_imdb_links.fileno())
                        print(f"WARNING: IMDb link found but ID parsing failed for {csfd_id}: {imdb_link}")

                except IndexError: # Original error for split logic
                    no_imdb_link_writer.writerow([csfd_id, "IMDb ID parsing error (split logic)", csfd_rating])
                    f_no_imdb_links.flush()
                    os.fsync(f_no_imdb_links.fileno())
                    print(f"WARNING: IMDb ID parsing error (IndexError) for {csfd_id}")
                except Exception as e:
                    no_imdb_link_writer.writerow([csfd_id, f"IMDb ID parsing unexpected error: {e}", csfd_rating])
                    f_no_imdb_links.flush()
                    os.fsync(f_no_imdb_links.fileno())
                    print(f"WARNING: Unexpected error during IMDb ID processing for {csfd_id}: {e}")

            else:
                no_imdb_link_writer.writerow([csfd_id, "No IMDb link found on page", csfd_rating])
                f_no_imdb_links.flush()
                os.fsync(f_no_imdb_links.fileno())
                print(f"No IMDb link found for {csfd_id}")
                
            time.sleep(2) # Delay after each link check

    # Final counts (re-read files for accurate count)
    try:
        num_lines_imdb = sum(1 for line in open(imdb_links_file, encoding="utf-8")) - 1
    except Exception: num_lines_imdb = 0 # Handle if file is empty or missing header
    try:
        num_lines_imdb_fl = sum(1 for line in open(no_imdb_links_file, encoding="utf-8")) - 1
    except Exception: num_lines_imdb_fl = 0

    print(32 * "-")
    print(f"Found {num_lines_imdb} IMDb links")
    print(f"Did not find {num_lines_imdb_fl} IMDb links")
    print(32 * "=")        

def rate_imdb():
    # Resume logic for IMDb rating
    imdb_fail_file = 'imdb_fail.csv'
    rated_imdb_ids = set() # To track successfully rated IDs

    # If imdb_fail.csv exists from a previous run, read it to avoid double-processing failures
    if os.path.exists(imdb_fail_file) and os.path.getsize(imdb_fail_file) > 0:
        try:
            with open(imdb_fail_file, "r", encoding="utf-8", newline='') as f_fail_check:
                reader_fail = csv.DictReader(f_fail_check)
                if reader_fail.fieldnames and 'imdb_id' in reader_fail.fieldnames:
                    for row in reader_fail:
                        # Only skip if the error was not a temporary one like rate limit
                        if row.get('imdb_id') and "Rate limit exceeded" not in row.get('error_message', ''):
                            rated_imdb_ids.add(row['imdb_id'])
            print(f"DEBUG: Found {len(rated_imdb_ids)} IMDb IDs previously failed to rate (excluding rate limits).")
        except Exception as e:
            print(f"ERROR: Could not read existing '{imdb_fail_file}' for resume. Error: {e}")

    if not os.path.exists('csfd_imdb_links.csv'):
        print("Error: 'csfd_imdb_links.csv' not found. Please run option 3 first.")
        return
    if not imdb_cookie:
        print("Error: 'imdb_cookie.txt' not found or empty. Cannot rate on IMDb.")
        return

    films_to_rate_initial = []
    with open('csfd_imdb_links.csv', encoding="utf8", newline='') as imdb_file:
        reader = csv.reader(imdb_file)
        next(reader, None) # Skip header
        for row in reader:
            if row and len(row) >= 2: # Ensure at least csfd_id and imdb_id
                # Filter out those already successfully processed or permanently failed
                if row[1] not in rated_imdb_ids: # imdb_id is at index 1
                    films_to_rate_initial.append(row)

    print(f"Found {len(films_to_rate_initial)} films to attempt rating on IMDb.")

    # Always start a new imdb_fail.csv to collect failures from this run
    f = open(imdb_fail_file, "w+", encoding="utf-8", newline='')
    fail_writer = csv.writer(f)
    fail_writer.writerow(['csfd_id', 'imdb_id', 'csfd_rating', 'error_message'])

    suc = 0
    
    for film_data in films_to_rate_initial:
        if len(film_data) < 3:
            print(f"Skipping malformed row: {film_data}")
            fail_writer.writerow([film_data[0] if len(film_data) > 0 else "N/A", film_data[1] if len(film_data) > 1 else "N/A", film_data[2] if len(film_data) > 2 else "N/A", "Malformed row skipped"])
            f.flush()
            os.fsync(f.fileno())
            continue

        csfd_id = film_data[0]
        imdb_id = film_data[1]
        csfd_rating_str = film_data[2]

        try:
            csfd_int = int(csfd_rating_str)
            rating_imdb = int(csfd_int / 10)
        except ValueError:
            fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, "Invalid CSFD rating value"])
            f.flush()
            os.fsync(f.fileno())
            continue

        req_body = {        
            'query': 'mutation UpdateTitleRating($rating: Int!, $titleId: ID!) { rateTitle(input: {rating: $rating, titleId: $titleId}) { rating { value __typename } __typename }}',
            'operationName': 'UpdateTitleRating',
            'variables': {
                'rating': rating_imdb,
                'titleId': imdb_id # Assuming imdb_id is already 'ttXXXXXXX' format here
            }
        }
        headers = {
            "content-type": "application/json",
            "cookie": imdb_cookie
        }

        print(f"Attempting to rate IMDb ID {imdb_id} (CSFD ID {csfd_id}) with {rating_imdb} stars.")
        try:
            resp = requests.post("https://api.graphql.imdb.com/", json=req_body, headers=headers)
            resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            json_resp = resp.json()
            
            if 'errors' in json_resp and len(json_resp['errors']) > 0:
                first_error_msg = json_resp['errors'][0]['message']
                if 'Authentication' in first_error_msg:
                    print(f"Invalid IMDb cookie. Please update imdb_cookie.txt.")
                    fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, "IMDb cookie invalid"])
                    f.flush()
                    os.fsync(f.fileno())
                    sys.exit(1)
                else:
                    fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, first_error_msg])
                    f.flush()
                    os.fsync(f.fileno())
            else:
                suc += 1
                print(f"Successfully rated {imdb_id}.")
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP Status: {http_err.response.status_code}"
            if http_err.response.status_code == 429:
                error_msg += " (Rate limit exceeded)"
                print(f"Rate limit hit. Waiting 60 seconds. {http_err}")
                time.sleep(60) # Increased wait for rate limit
            fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, error_msg])
            f.flush()
            os.fsync(f.fileno())
            if http_err.response.status_code >= 500:
                print(f"Server error {http_err.response.status_code}. Stopping IMDb rating process.")
                break # Stop processing on severe server errors
            continue # Continue to next film on other HTTP errors
        except Exception as e:
            error_msg = f"Unexpected request error: {e}"
            fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, error_msg])
            f.flush()
            os.fsync(f.fileno())
            print(f"ERROR: Unexpected error during IMDb rating for {imdb_id}: {e}")
            continue # Continue to next film

        time.sleep(2)

    f.close()
    
    # Recalculate counts based on written files
    num_total_initial = len(films_to_rate_initial)
    try:
        num_lines_imdb_fl = sum(1 for line in open(imdb_fail_file, encoding="utf-8")) - 1
    except Exception: num_lines_imdb_fl = 0

    print(32 * "-")
    print(f"Total films attempted this run: {num_total_initial}")
    print(f"Rated successfully this run: {suc} films")
    print(f"Failed to rate this run: {num_lines_imdb_fl} films (see {imdb_fail_file})")
    print(32 * "=")        

def rate_fail_imdb():
    # Logic for retrying failed IMDb ratings, now uses imdb_fail.csv for input
    # and writes to imdb_fail_retry.csv for remaining failures.
    # It will clear imdb_fail_retry.csv on each run.

    input_fail_file = 'imdb_fail.csv'
    output_fail_file = 'imdb_fail_retry.csv'

    if not os.path.exists(input_fail_file):
        print(f"Error: '{input_fail_file}' not found. No previous failures to retry.")
        return
    if not imdb_cookie:
        print("Error: 'imdb_cookie.txt' not found or empty. Cannot rate on IMDb.")
        return

    films_to_retry = []
    with open(input_fail_file, encoding="utf8", newline='') as imdb_fail_file:
        reader = csv.reader(imdb_fail_file)
        next(reader, None) # Skip header
        for row in reader:
            if row:
                films_to_retry.append(row)

    print(f"Found {len(films_to_retry)} films to attempt retry rating on IMDb.")

    # Always start a new imdb_fail_retry.csv
    f = open(output_fail_file, "w+", encoding="utf-8", newline='')
    retry_fail_writer = csv.writer(f)
    retry_fail_writer.writerow(['csfd_id', 'imdb_id', 'csfd_rating', 'error_message'])

    suc = 0
    
    for film_data in films_to_retry:
        if len(film_data) < 3:
            print(f"Skipping malformed row in retry: {film_data}")
            retry_fail_writer.writerow([film_data[0] if len(film_data) > 0 else "N/A", film_data[1] if len(film_data) > 1 else "N/A", film_data[2] if len(film_data) > 2 else "N/A", "Malformed row skipped (retry)"])
            f.flush()
            os.fsync(f.fileno())
            continue

        csfd_id = film_data[0]
        imdb_id = film_data[1]
        csfd_rating_str = film_data[2]

        try:
            csfd_int = int(csfd_rating_str)
            rating_imdb = int(csfd_int / 10)
        except ValueError:
            retry_fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, "Invalid CSFD rating value (retry)"])
            f.flush()
            os.fsync(f.fileno())
            continue

        req_body = {        
            'query': 'mutation UpdateTitleRating($rating: Int!, $titleId: ID!) { rateTitle(input: {rating: $rating, titleId: $titleId}) { rating { value __typename } __typename }}',
            'operationName': 'UpdateTitleRating',
            'variables': {
                'rating': rating_imdb,
                'titleId': imdb_id
            }
        }
        headers = {
            "content-type": "application/json",
            "cookie": imdb_cookie
        }

        print(f"Attempting to retry IMDb ID {imdb_id} (CSFD ID {csfd_id}) with {rating_imdb} stars.")
        try:
            resp = requests.post("https://api.graphql.imdb.com/", json=req_body, headers=headers)
            resp.raise_for_status()
            json_resp = resp.json()
            
            if 'errors' in json_resp and len(json_resp['errors']) > 0:
                first_error_msg = json_resp['errors'][0]['message']
                if 'Authentication' in first_error_msg:
                    print(f"Invalid IMDb cookie during retry. Please update imdb_cookie.txt.")
                    retry_fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, "IMDb cookie invalid (retry)"])
                    f.flush()
                    os.fsync(f.fileno())
                    sys.exit(1)
                else:
                    retry_fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, first_error_msg])
                    f.flush()
                    os.fsync(f.fileno())
            else:
                suc += 1
                print(f"Successfully rated {imdb_id} on retry.")
        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP Status: {http_err.response.status_code}"
            if http_err.response.status_code == 429:
                error_msg += " (Rate limit exceeded during retry)"
                print(f"Rate limit hit during retry. Waiting 60 seconds. {http_err}")
                time.sleep(60)
            retry_fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, error_msg])
            f.flush()
            os.fsync(f.fileno())
            if http_err.response.status_code >= 500:
                print(f"Server error {http_err.response.status_code}. Stopping retry process.")
                break
            continue
        except Exception as e:
            error_msg = f"Unexpected request error during retry: {e}"
            retry_fail_writer.writerow([csfd_id, imdb_id, csfd_rating_str, error_msg])
            f.flush()
            os.fsync(f.fileno())
            print(f"ERROR: Unexpected error during IMDb rating retry for {imdb_id}: {e}")
            continue

        time.sleep(2)

    f.close()
    
    try:
        num_lines_failed_retry = sum(1 for line in open(output_fail_file, encoding="utf-8")) - 1
    except Exception: num_lines_failed_retry = 0

    print(32 * "-")
    print(f"Attempted to retry {len(films_to_retry)} failed films.")
    print(f"Successfully rated {suc} films on retry.")
    print(f"Still failed to rate {num_lines_failed_retry} films (see {output_fail_file})")
    print(32 * "=")        

def csfd_cookie_validity():
    csfd_nastaveni = f'https://www.csfd.cz/soukrome/nastaveni/'
    grab = requests.get(csfd_nastaveni, headers=payload)
    soup = BeautifulSoup(grab.text, 'html.parser')
    
    nastaveni_cz = 'Nastavení - Účet'
    nastaveni_sk = 'Nastavenie - Účet'
    
    page_title_tag = soup.find('title')
    
    if page_title_tag and (nastaveni_cz in page_title_tag.string or nastaveni_sk in page_title_tag.string):
        print('CSFD cookie is valid.')
    else:
        print('CSFD cookie is invalid or expired. Please update csfd_cookie.txt.')
    
    print(32 * "=")

def print_menu():
    global user_name, user_id
    print('User:', user_name, '\nID:     ', user_id)
    print(32 * "-")
    print('1. Download ratings as .csv (with year, country, director, overall rating, actors)')
    print('2. Download reviews as .csv (with year, country, director, overall rating, actors)')
    print('3. Download IMDb IDs as .csv (after running #1)')
    print('4. Rate on IMDb (after running #3, requires IMDb cookie)')
    print('5. Retry failed IMDb ratings (uses imdb_fail.csv)')
    print('9. Check CSFD cookie validity')
    print('0. Exit')
    print(32 * '-')
    
# --- Main Execution Block ---
def main():
    global user_id, user_name
    parser = argparse.ArgumentParser(description='Download CSFD data and optionally rate on IMDb.')
    parser.add_argument('--user', type=int, help='Your CSFD User ID (e.g., 2542). Required for download options.')
    parser.add_argument('--reviews', action='store_true', help='Download user reviews.')
    parser.add_argument('--ratings', action='store_true', help='Download user ratings.')
    parser.add_argument('--imdb_links', action='store_true', help='Download IMDb IDs (requires --ratings).')
    parser.add_argument('--rate_imdb', action='store_true', help='Rate movies on IMDb (requires --imdb_links and IMDb cookie).')
    parser.add_argument('--rate_fail_imdb', action='store_true', help='Retry failed IMDb ratings from imdb_fail.csv.')
    parser.add_argument('--check_cookie', action='store_true', help='Check CSFD cookie validity.')
    parser.add_argument('--menu', action='store_true', help='Display the interactive menu. Overrides other options if present.')

    args = parser.parse_args()

    # --- Handle User ID ---
    if not args.user and not args.menu:
        user_id_input = input("Please enter your CSFD User ID: ")
        try:
            user_id = int(user_id_input)
        except ValueError:
            print("Invalid User ID. Please enter a number.")
            sys.exit(1)
    elif args.user:
        user_id = args.user

    if user_id is not None:
        try:
            user_url = f'https://www.csfd.cz/uzivatel/{user_id}'
            grab_user = requests.get(user_url, headers=payload)
            soup_user = BeautifulSoup(grab_user.text, 'html.parser')
            user_name_tag = soup_user.find('title')
            if user_name_tag and "csfd.cz" in user_name_tag.string:
                user_name = user_name_tag.string.split(' |')[0].strip()
            else:
                print(f"Warning: Could not get user name for ID {user_id}. Check ID or cookie. It might be a 404.")
                user_name = "Unknown User (ID: " + str(user_id) + ")"
        except Exception as e:
            print(f"Error fetching user name for ID {user_id}: {e}")
            user_name = "Unknown User (ID: " + str(user_id) + ")"
    else:
        user_name = "N/A (No User ID Provided)"

    # --- Execute based on arguments ---
    if args.menu:
        loop = True
        while loop:
            print_menu()
            choice = input("Select an option [1-9, 0 to exit]: ")
            
            if choice == '1':
                if user_id is None: print("Error: Please provide a User ID to download ratings."); continue
                get_csfd_ratings()
            elif choice == '2':
                if user_id is None: print("Error: Please provide a User ID to download reviews."); continue
                get_csfd_reviews()
            elif choice == '3':
                get_imdb_links()
            elif choice == '4':
                rate_imdb()
            elif choice == '5':
                rate_fail_imdb()
            elif choice == '9':
                csfd_cookie_validity()
            elif choice == '0':
                print("Exiting.")
                loop = False
            else:
                print("Invalid choice. Please try again.")
    else:
        if args.ratings:
            if user_id is None: print("Error: User ID is required for ratings download. Use --user <ID>."); sys.exit(1)
            get_csfd_ratings()
        elif args.reviews:
            if user_id is None: print("Error: User ID is required for reviews download. Use --user <ID>."); sys.exit(1)
            get_csfd_reviews()
        elif args.imdb_links:
            get_imdb_links()
        elif args.rate_imdb:
            rate_imdb()
        elif args.rate_fail_imdb:
            rate_fail_imdb()
        elif args.check_cookie:
            csfd_cookie_validity()
        else:
            print("No action specified. Use --help for options or --menu for interactive mode.")

if __name__ == '__main__':
    main()