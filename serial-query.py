# generate_queries_v4.py
# Description: Takes a single seed query, searches SearXNG across multiple pages,
# then iteratively appends modifier terms (read from modifiers.csv) to the seed query for further searches.
# Generates a CSV file of new queries (based on result titles) and their corresponding URLs.
# Features:
# - Progressive CSV saving (appends results after each page).
# - Pause/Resume: Press Ctrl+C to pause; script saves state and can be resumed on next run.
# - Automatic Retry: If a page returns 0 results, pauses for 10 mins; if no manual retry ('r'), retries automatically.
# - Random delays, pagination, improved handling for rate limiting.
# - Common User-Agent and enhanced logging.

import requests
import json
import pandas as pd
import os
import time
import random
from tenacity import retry, stop_after_attempt, wait_exponential
import sys
import select

# --- Configuration ---
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080/search")
TOP_N_RESULTS_PER_QUERY = int(os.getenv("TOP_N_RESULTS_PER_QUERY", 6)) # Max new items to save per query
OUTPUT_CSV_FILENAME = os.getenv("OUTPUT_CSV_FILENAME", "queries_with_urls.csv")
QUERY_COLUMN_NAME = os.getenv("QUERY_COLUMN_NAME", "search_query_title")
URL_COLUMN_NAME = os.getenv("URL_COLUMN_NAME", "url")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
MAX_PAGES_TO_FETCH_PER_QUERY = int(os.getenv("MAX_PAGES_TO_FETCH_PER_QUERY", 100))
MODIFIER_CSV_FILENAME = "modifiers.csv"
AUTO_RETRY_TIMEOUT_SECONDS = 600 # 10 minutes for 0-result page pause
POST_FETCH_PARSE_DELAY_SECONDS = 2

STATE_FILE = "searxng_scraper_state.json"

# --- Timezone Fix ---
os.environ['TZ'] = 'UTC'
time.tzset()


# --- Load Modifier Terms ---
MODIFIER_TERMS = []
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    script_dir = os.getcwd()
    print(f"Warning: __file__ not defined, using current working directory for {MODIFIER_CSV_FILENAME}: {script_dir}")
modifier_csv_path = os.path.join(script_dir, MODIFIER_CSV_FILENAME)

if os.path.exists(modifier_csv_path):
    try:
        df_modifiers = pd.read_csv(modifier_csv_path, header=None)
        if not df_modifiers.empty:
            MODIFIER_TERMS = [str(term).strip() for term in df_modifiers.iloc[:, 0].tolist() if str(term).strip()]
            print(f"Successfully loaded {len(MODIFIER_TERMS)} modifier terms from {modifier_csv_path}")
        else:
            print(f"Warning: {modifier_csv_path} was found but is empty. No modifier terms loaded.")
    except pd.errors.EmptyDataError:
        print(f"Warning: {modifier_csv_path} is empty or not a valid CSV. No modifier terms loaded.")
    except Exception as e:
        print(f"Error loading modifier terms from {modifier_csv_path}: {e}")
else:
    print(f"Warning: {modifier_csv_path} not found. No modifier terms will be used.")


# --- Default Search Parameters ---
SEARCH_LANGUAGE = os.getenv("SEARCH_LANGUAGE", "en-US")
SEARCH_CATEGORIES = os.getenv("SEARCH_CATEGORIES", "general")
SEARCH_SAFESEARCH = int(os.getenv("SEARCH_SAFESEARCH", "0"))

# --- Retry Configuration (Tenacity) ---
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", 3))
RETRY_WAIT_MULTIPLIER = int(os.getenv("RETRY_WAIT_MULTIPLIER", 1))
RETRY_WAIT_MIN_SECONDS = int(os.getenv("RETRY_WAIT_MIN_SECONDS", 30))
RETRY_WAIT_MAX_SECONDS = int(os.getenv("RETRY_WAIT_MAX_SECONDS", 300))

# --- Request Delays ---
MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", 94.20))
MAX_DELAY_SECONDS = float(os.getenv("MAX_DELAY_SECONDS", 300.0))

# --- HTTP Headers ---
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# --- Global State Variables for Pause/Resume and Progressive Save ---
current_run_state_for_pause = {
    "seed_query": None,
    "current_modifier_idx": -1, # -1 for seed, 0..N-1 for modifiers
    "current_query_being_processed": None,
    "next_page_to_fetch": 1
}
# This set will store URLs that are already in the CSV to avoid duplicates
global_urls_in_csv = set()

def update_current_run_state(seed_q, mod_idx, current_q_str, next_page):
    """Updates the global state for graceful exit."""
    current_run_state_for_pause["seed_query"] = seed_q
    current_run_state_for_pause["current_modifier_idx"] = mod_idx
    current_run_state_for_pause["current_query_being_processed"] = current_q_str
    current_run_state_for_pause["next_page_to_fetch"] = next_page

def save_state_and_exit_gracefully():
    """Saves the current operational state to a file for resumption."""
    if not current_run_state_for_pause["current_query_being_processed"]:
        print("No active processing state to save. Exiting.")
        sys.exit(0)

    state_to_save = {
        "seed_query_original": current_run_state_for_pause["seed_query"],
        "modifier_terms_file": MODIFIER_CSV_FILENAME, # For validation on resume
        "output_csv_filename": OUTPUT_CSV_FILENAME,   # For validation on resume
        "resume_modifier_idx": current_run_state_for_pause["current_modifier_idx"],
        "resume_query_string": current_run_state_for_pause["current_query_being_processed"],
        "resume_page_number": current_run_state_for_pause["next_page_to_fetch"],
        "user_message": "Script was interrupted. Re-run to resume from this point."
    }
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=4)
        print(f"\n🔄 Script state saved to {STATE_FILE}. Re-run the script to resume.")
    except IOError as e:
        print(f"\n❌ Error saving state to {STATE_FILE}: {e}")
    sys.exit(0)

def load_saved_state_if_exists():
    """Loads a previously saved state from the state file, if it exists."""
    global OUTPUT_CSV_FILENAME # Moved global declaration to the top of the function
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                saved_state = json.load(f)
            # Basic validation
            if all(k in saved_state for k in ["seed_query_original", "resume_modifier_idx", "resume_query_string", "resume_page_number"]):
                print(f"📄 Found saved state from a previous run in {STATE_FILE}.")
                if saved_state.get("modifier_terms_file") != MODIFIER_CSV_FILENAME:
                    print(f"Warning: Modifier file in state ({saved_state.get('modifier_terms_file')}) differs from current ({MODIFIER_CSV_FILENAME}).")
                if saved_state.get("output_csv_filename") != OUTPUT_CSV_FILENAME:
                    print(f"Warning: Output CSV file in state ({saved_state.get('output_csv_filename')}) differs from current ({OUTPUT_CSV_FILENAME}). Resuming will use: {saved_state.get('output_csv_filename', OUTPUT_CSV_FILENAME)}")
                    # Update global OUTPUT_CSV_FILENAME if specified in state and user confirms or by design
                    # For now, we'll use the one from state if it exists there.
                    OUTPUT_CSV_FILENAME = saved_state.get('output_csv_filename', OUTPUT_CSV_FILENAME)

                return saved_state
            else:
                print(f"Warning: State file {STATE_FILE} is incomplete. Starting fresh.")
                os.remove(STATE_FILE) # Remove invalid state file
        except json.JSONDecodeError:
            print(f"Warning: State file {STATE_FILE} is corrupted. Starting fresh.")
            os.remove(STATE_FILE) # Remove corrupted state file
        except IOError as e:
            print(f"Warning: Could not read state file {STATE_FILE}: {e}. Starting fresh.")
    return None

def load_existing_urls_from_csv():
    """Loads URLs from the output CSV into the global set to prevent duplicates."""
    if os.path.exists(OUTPUT_CSV_FILENAME):
        try:
            df_existing = pd.read_csv(OUTPUT_CSV_FILENAME)
            if URL_COLUMN_NAME in df_existing.columns:
                count = len(global_urls_in_csv)
                global_urls_in_csv.update(df_existing[URL_COLUMN_NAME].dropna().astype(str).tolist())
                print(f"Loaded {len(global_urls_in_csv) - count} unique URLs from existing {OUTPUT_CSV_FILENAME}.")
            else:
                print(f"Warning: URL column '{URL_COLUMN_NAME}' not found in {OUTPUT_CSV_FILENAME}. Cannot load existing URLs for deduplication.")
        except pd.errors.EmptyDataError:
            print(f"{OUTPUT_CSV_FILENAME} is empty. No existing URLs to load.")
        except Exception as e:
            print(f"Error reading existing CSV {OUTPUT_CSV_FILENAME}: {e}")


def append_items_to_csv(items_to_add: list, filename: str, query_col: str, url_col: str) -> int:
    """
    Appends new, unique items to the CSV file.
    Args:
        items_to_add: List of dictionaries, each with 'title' and 'url'.
        filename: Path to the CSV file.
        query_col: Name for the query/title column in CSV.
        url_col: Name for the URL column in CSV.
    Returns:
        Number of new items actually appended to the CSV.
    """
    if not items_to_add:
        return 0

    new_unique_data = []
    for item in items_to_add:
        # Ensure item is a dict and has 'url' and 'title'
        if not isinstance(item, dict) or 'url' not in item or 'title' not in item:
            print(f"Warning: Skipping invalid item for CSV: {item}")
            continue
        
        url_str = str(item['url']).strip()
        title_str = str(item['title']).strip()

        if not url_str or not title_str: # Skip if title or URL is empty after stripping
            # print(f"Debug: Skipping item with empty title or URL: Title='{title_str}', URL='{url_str}'")
            continue

        if url_str not in global_urls_in_csv:
            new_unique_data.append({query_col: title_str, url_col: url_str})
            global_urls_in_csv.add(url_str)

    if not new_unique_data:
        return 0

    df_new = pd.DataFrame(new_unique_data)
    
    # Ensure correct column order for consistent CSV, even if df_new has only one row
    df_new = df_new[[query_col, url_col]]

    file_exists = os.path.exists(filename) and os.path.getsize(filename) > 0
    try:
        df_new.to_csv(filename, mode='a', header=not file_exists, index=False, encoding='utf-8')
        # print(f"Appended {len(new_unique_data)} new items to {filename}.") # Can be verbose
        return len(new_unique_data)
    except IOError as e:
        print(f"❌ Error writing to CSV {filename}: {e}")
        # If write fails, remove successfully added URLs from global set to allow retry
        for item_written in new_unique_data:
            global_urls_in_csv.discard(item_written[url_col])
        return 0


@retry(
    stop=stop_after_attempt(RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=RETRY_WAIT_MULTIPLIER, min=RETRY_WAIT_MIN_SECONDS, max=RETRY_WAIT_MAX_SECONDS)
)
def fetch_page_from_searxng(query: str, pageno: int) -> list:
    """Fetches a single page of search results from SearXNG."""
    delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    # print(f"🕒 Waiting for {delay:.2f} seconds before querying SearXNG for page {pageno}...")
    time.sleep(delay)

    print(f"🔍 Searching SearXNG (page {pageno}) for: \"{query}\"")
    params = {
        "q": query, "format": "json", "pageno": pageno,
        "language": SEARCH_LANGUAGE, "categories": SEARCH_CATEGORIES, "safesearch": SEARCH_SAFESEARCH
    }
    
    response_results = []
    try:
        # prepared_request = requests.Request('GET', SEARXNG_URL, params=params, headers=REQUEST_HEADERS).prepare()
        # print(f"Constructed URL by script: {prepared_request.url}") # Debug
        response = requests.get(SEARXNG_URL, params=params, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
        
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            wait_msg = f"🚦 Rate limited (429) on page {pageno} for query \"{query}\"."
            if retry_after: wait_msg += f" Server suggests waiting {retry_after} seconds."
            print(wait_msg)
        
        response.raise_for_status()

        if POST_FETCH_PARSE_DELAY_SECONDS > 0:
            # print(f"🕒 Pausing for {POST_FETCH_PARSE_DELAY_SECONDS}s after fetch, before parsing JSON for page {pageno}...")
            time.sleep(POST_FETCH_PARSE_DELAY_SECONDS)

        results_json = response.json()
        response_results = results_json.get("results", [])
        
        if not response_results:
            print(f"Page {pageno} from SearXNG for query \"{query}\" returned 0 result items.")
            # print(f"  Status Code: {response.status_code}") # Debug
            # print(f"  Full JSON Response (when 0 results): {json.dumps(results_json, indent=2)}") # Debug
        # else: # Debug
            # print(f"Retrieved {len(response_results)} result items from page {pageno}.")
            
    except requests.exceptions.Timeout:
        print(f"Error: Request to SearXNG timed out for query: \"{query}\", page: {pageno}"); raise
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error for \"{query}\", page {pageno}: {http_err} (Status: {http_err.response.status_code})")
        # print(f"  Response Text (first 500 chars): {http_err.response.text[:500] if http_err.response else 'N/A'}"); # Debug
        raise
    except requests.exceptions.RequestException as e:
        print(f"Error: Network error for \"{query}\", page {pageno}: {e}"); raise
    except json.JSONDecodeError as e:
        resp_text = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else 'N/A'
        print(f"Error: JSON decode error for \"{query}\", page {pageno}. Error: {e}")
        # print(f"  Response Text (first 500 chars): {resp_text}"); # Debug
        raise
    except Exception as e:
        print(f"Unexpected error in fetch_page_from_searxng for \"{query}\", page {pageno}: {e}"); raise
    
    return response_results


def handle_zero_results_and_retry(original_query: str, current_page_num: int) -> tuple[list, bool]:
    """
    Handles 0-result scenario with a 10-minute interruptible pause for manual retry,
    or automatic retry after timeout.
    Returns: (list_of_results_if_retry_successful_else_empty, should_break_processing_this_query_boolean)
    """
    print(f"INFO: No results on page {current_page_num} for query \"{original_query}\" (initial attempt).")
    print(f"INFO: Pausing for up to {AUTO_RETRY_TIMEOUT_SECONDS} seconds ({AUTO_RETRY_TIMEOUT_SECONDS // 60} minutes).")
    print(f"ACTION: Press 'r' (then Enter) within this time to retry page {current_page_num} immediately.")
    print(f"ACTION: If 'r' is not pressed, an automatic retry will occur after the pause.")

    retry_attempt_results = []
    _should_break_processing_this_query = False
    user_interrupted_for_immediate_retry = False

    if sys.stdin.isatty(): # Only monitor for input if running in an interactive terminal
        start_pause_time = time.time()
        print("INFO: Monitoring for 'r' input...")
        while time.time() - start_pause_time < AUTO_RETRY_TIMEOUT_SECONDS:
            ready_to_read, _, _ = select.select([sys.stdin], [], [], 0.1) # Check every 100ms
            if ready_to_read:
                user_interrupt_choice = sys.stdin.readline().strip().lower()
                if user_interrupt_choice == 'r':
                    print("User pressed 'r'. Interrupting pause and retrying immediately.")
                    user_interrupted_for_immediate_retry = True
                    break
                else:
                    print(f"Input '{user_interrupt_choice}' received (not 'r'). To retry now, type 'r' and Enter. Else, wait.")
            time.sleep(0.05) # Small sleep to prevent tight loop
        
        if not user_interrupted_for_immediate_retry and (time.time() - start_pause_time >= AUTO_RETRY_TIMEOUT_SECONDS):
            print("INFO: 10-minute pause duration elapsed without 'r' interrupt.")
    else: # Not a TTY, perform full non-interruptible pause then auto-retry
        print(f"INFO: Stdin is not a TTY. Performing full {AUTO_RETRY_TIMEOUT_SECONDS // 60}-minute pause before automatic retry.")
        time.sleep(AUTO_RETRY_TIMEOUT_SECONDS)
        print("INFO: Full pause duration elapsed (stdin not a TTY).")

    # --- Logic after pause (interrupted, timed out, or non-TTY) ---
    action_reason = "user interrupt" if user_interrupted_for_immediate_retry else "automatic timeout"
    print(f"Retrying page {current_page_num} for \"{original_query}\" due to {action_reason}.")
    try:
        retry_attempt_results = fetch_page_from_searxng(original_query, current_page_num)
        if not retry_attempt_results:
            print(f"Still no results on page {current_page_num} after {action_reason} retry. Stopping collection for this query.")
            _should_break_processing_this_query = True
    except Exception as e:
        print(f"❌ Failed to fetch page {current_page_num} for \"{original_query}\" on {action_reason} retry: {e}")
        _should_break_processing_this_query = True
            
    return retry_attempt_results, _should_break_processing_this_query


def get_all_search_results_for_query(
    query_str: str, 
    seed_query_for_state: str,
    current_modifier_idx_for_state: int,
    start_page: int = 1
    ) -> int:
    """
    Fetches results for a single query, handles pagination, progressive saving, and 0-result retries.
    Updates global state for pause/resume.
    Returns: Total number of NEW items added to CSV for this query.
    """
    items_added_for_this_query = 0
    page_number = start_page
    
    print(f"\nFetching up to {TOP_N_RESULTS_PER_QUERY} new items, across max {MAX_PAGES_TO_FETCH_PER_QUERY} pages for query: \"{query_str}\" (starting page {page_number})")

    while items_added_for_this_query < TOP_N_RESULTS_PER_QUERY and page_number <= MAX_PAGES_TO_FETCH_PER_QUERY:
        update_current_run_state(seed_query_for_state, current_modifier_idx_for_state, query_str, page_number)
        
        current_page_api_results = []
        should_break_loop_for_query = False
        try:
            current_page_api_results = fetch_page_from_searxng(query_str, page_number)
        except Exception: # Tenacity already handled retries for network/HTTP errors
            print(f"❌ Persistent failure fetching page {page_number} for query \"{query_str}\". Stopping for this query.")
            should_break_loop_for_query = True

        if not should_break_loop_for_query and not current_page_api_results:
            # This means fetch was successful (no exception) but returned 0 results.
            current_page_api_results, should_break_loop_for_query = handle_zero_results_and_retry(query_str, page_number)

        if should_break_loop_for_query:
            break # Break from the while loop (pages) for this specific query

        if current_page_api_results:
            # Process results from this page
            title_url_pairs_from_page = []
            for result in current_page_api_results:
                title = result.get("title")
                url = result.get("url")
                if title and url: # Both must exist
                    title_url_pairs_from_page.append({"title": str(title).strip(), "url": str(url).strip()})
            
            if title_url_pairs_from_page:
                newly_saved_count_this_page = append_items_to_csv(
                    title_url_pairs_from_page, 
                    OUTPUT_CSV_FILENAME, 
                    QUERY_COLUMN_NAME, 
                    URL_COLUMN_NAME
                )
                items_added_for_this_query += newly_saved_count_this_page
                if newly_saved_count_this_page > 0:
                    print(f"Saved {newly_saved_count_this_page} new items from page {page_number} for \"{query_str}\". Total for this query: {items_added_for_this_query}.")

                if items_added_for_this_query >= TOP_N_RESULTS_PER_QUERY:
                    print(f"Collected {items_added_for_this_query} new items, reaching target of {TOP_N_RESULTS_PER_QUERY} for \"{query_str}\".")
                    break # Break from while loop (pages) as per-query limit reached
        else: # No results from page even after potential retry, and not broken by exception
            # This case should be covered by handle_zero_results_and_retry setting should_break_loop_for_query
            # If it gets here, it means no results and no explicit break, which is unlikely.
            print(f"No results to process from page {page_number} for \"{query_str}\".")
            # If handle_zero_results_and_retry decided not to break, we might continue to next page if conditions allow.
            # However, it usually breaks if retries also yield no results.

        page_number += 1
        if page_number > MAX_PAGES_TO_FETCH_PER_QUERY:
            print(f"Reached maximum page limit ({MAX_PAGES_TO_FETCH_PER_QUERY}) for query \"{query_str}\".")
            break
            
    print(f"Finished fetching for \"{query_str}\". Total new items added to CSV for this query: {items_added_for_this_query}.")
    return items_added_for_this_query


# --- Main Orchestration ---
def main():
    print("--- Query Generation Utility (v4 - Pause/Resume, Progressive Save, Auto-Retry) ---")
    
    initial_seed_query = ""
    resume_details = {
        "modifier_idx": -1, # -1 for seed, 0..N-1 for modifiers
        "page_number": 1
    }
    
    # Load existing URLs from CSV if it exists, for deduplication
    load_existing_urls_from_csv() # Populates global_urls_in_csv

    saved_state = load_saved_state_if_exists()
    if saved_state:
        print(f"  Resuming from: Query='{saved_state['resume_query_string']}', Page={saved_state['resume_page_number']}")
        user_choice = input("Do you want to resume this previous session? (y/n): ").strip().lower()
        if user_choice == 'y':
            initial_seed_query = saved_state['seed_query_original']
            # The query string itself is not directly used for resuming loop, modifier_idx is key
            resume_details["modifier_idx"] = saved_state['resume_modifier_idx']
            resume_details["page_number"] = saved_state['resume_page_number']
            # Ensure the output CSV filename from state is used if different
            # global OUTPUT_CSV_FILENAME # This is already handled by load_saved_state_if_exists
            # OUTPUT_CSV_FILENAME = saved_state.get("output_csv_filename", OUTPUT_CSV_FILENAME) # Also handled
            print(f"Resuming. Output will be to: {OUTPUT_CSV_FILENAME}")
             # Re-load existing URLs if OUTPUT_CSV_FILENAME changed and might not have been loaded initially
            if saved_state.get("output_csv_filename") != os.getenv("OUTPUT_CSV_FILENAME", "queries_with_urls.csv"):
                global_urls_in_csv.clear() # Clear previously loaded (possibly from default CSV name)
                load_existing_urls_from_csv() # Load from the state-defined CSV name

        else:
            print("Starting a fresh session.")
            try:
                os.remove(STATE_FILE) # Clean up state file if not resuming
                print(f"Removed {STATE_FILE}.")
            except OSError as e:
                print(f"Could not remove {STATE_FILE}: {e}")
            # Fall through to get new seed query
    
    if not initial_seed_query: # If not resuming or chose not to
        initial_seed_query = input("Enter initial seed query: ").strip()
        if not initial_seed_query:
            print("No seed query provided. Exiting.")
            return
        # For a fresh start, ensure resume_details are for starting from scratch
        resume_details["modifier_idx"] = -1 
        resume_details["page_number"] = 1


    # Prepare list of all queries to process
    queries_to_process = [{"query_str": initial_seed_query, "modifier_idx": -1, "is_seed": True}]
    if MODIFIER_TERMS:
        for i, term in enumerate(MODIFIER_TERMS):
            queries_to_process.append({
                "query_str": f"{initial_seed_query} {term.strip()}",
                "modifier_idx": i,
                "is_seed": False
            })

    total_items_saved_this_run = 0
    
    # Determine starting point in the queries_to_process list
    start_processing_idx = 0
    if resume_details["modifier_idx"] == -1: # Resuming seed or starting fresh seed
        start_processing_idx = 0
    else: # Resuming a modifier query
        # Find the query that corresponds to resume_details["modifier_idx"]
        for i, q_detail in enumerate(queries_to_process):
            if not q_detail["is_seed"] and q_detail["modifier_idx"] == resume_details["modifier_idx"]:
                start_processing_idx = i
                break
        else: # Should not happen if state is valid
            print(f"Warning: Could not find modifier index {resume_details['modifier_idx']} to resume. Starting from seed.")
            start_processing_idx = 0
            resume_details["page_number"] = 1 # Reset page if query not found

    # Main processing loop
    for i in range(start_processing_idx, len(queries_to_process)):
        query_detail = queries_to_process[i]
        current_query_str = query_detail["query_str"]
        current_mod_idx = query_detail["modifier_idx"]
        
        page_to_start_fetching_from = 1
        if i == start_processing_idx : # This is the first query we process in this session (either fresh or resumed)
            page_to_start_fetching_from = resume_details["page_number"]

        print(f"\n--- Processing query {i+1-start_processing_idx}/{len(queries_to_process)-start_processing_idx}: \"{current_query_str}\" ---")
        
        try:
            items_added = get_all_search_results_for_query(
                query_str=current_query_str,
                seed_query_for_state=initial_seed_query,
                current_modifier_idx_for_state=current_mod_idx,
                start_page=page_to_start_fetching_from
            )
            total_items_saved_this_run += items_added
            
            # If this query completed successfully, next one starts from page 1.
            # State for pause/interrupt is handled by update_current_run_state *during* get_all_search_results.
            # If we complete a query, the state for the *next* query (if interrupted before it starts)
            # should reflect starting that next query from page 1.
            if i + 1 < len(queries_to_process):
                next_q_detail = queries_to_process[i+1]
                update_current_run_state(initial_seed_query, next_q_detail["modifier_idx"], next_q_detail["query_str"], 1)
            else: # All queries done
                update_current_run_state(initial_seed_query, current_mod_idx, current_query_str, MAX_PAGES_TO_FETCH_PER_QUERY + 1) # Mark as done

        except Exception as e: # Catch any unexpected errors from query processing
            print(f"\n❌ Unexpected error processing query \"{current_query_str}\": {e}")
            print("Attempting to save state before exiting due to this error.")
            save_state_and_exit_gracefully() # Save current state and exit
            return # Exit main

    print(f"\n--- All processing complete ---")
    print(f"Total new items saved to {OUTPUT_CSV_FILENAME} in this run: {total_items_saved_this_run}")
    print(f"Total unique items in {OUTPUT_CSV_FILENAME} (including previous runs): {len(global_urls_in_csv)}")

    # Clean up state file if run completed successfully
    if os.path.exists(STATE_FILE):
        try:
            print(f"Run completed. Removing state file: {STATE_FILE}")
            os.remove(STATE_FILE)
        except OSError as e:
            print(f"Could not remove state file {STATE_FILE}: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🚫 Ctrl+C detected by user. Saving state and exiting...")
        save_state_and_exit_gracefully()
    except Exception as e:
        print(f"\n💥 An unexpected critical error occurred in main: {e}")
        # traceback.print_exc() # Uncomment for debugging
        print("Attempting to save state if possible...")
        save_state_and_exit_gracefully()


