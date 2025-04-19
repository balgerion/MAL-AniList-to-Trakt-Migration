# -*- coding: utf-8 -*-
import requests
import time
import json
import datetime
import os
import math
import unicodedata # Needed for title normalization
from tqdm import tqdm

# --- Configuration ---
# Paste your Trakt API credentials here
TRAKT_CLIENT_ID = "YOUR_TRAKT_CLIENT_ID"
TRAKT_CLIENT_SECRET = "YOUR_TRAKT_CLIENT_SECRET"
ANILIST_USERNAME = "YOUR_ANILIST_USERNAME" # Replace with your AniList username

# File to store Trakt tokens (will be created automatically)
TOKEN_FILE = "trakt_tokens.json"

# --- Constants ---
ANILIST_API_URL = "https://graphql.anilist.co"
TRAKT_API_URL = "https://api.trakt.tv"
TRAKT_HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": TRAKT_CLIENT_ID,
}
# Number of items to send to Trakt in one batch
BATCH_SIZE = 50
# Delay between API calls (history or ratings)
API_CALL_DELAY = 1.5 # seconds

# --- Helper Functions ---

def load_tokens():
    """Loads Trakt tokens from the token file."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load token file: {e}. Need to re-authenticate.")
            return None
    return None

def save_tokens(tokens):
    """Saves Trakt tokens to the token file."""
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(tokens, f)
        # print(f"Tokens saved to {TOKEN_FILE}") # Less verbose
    except IOError as e:
        print(f"Error: Could not save tokens to {TOKEN_FILE}: {e}")


def get_trakt_device_code():
    """Gets a device code for Trakt authentication."""
    url = f"{TRAKT_API_URL}/oauth/device/code"
    payload = {"client_id": TRAKT_CLIENT_ID}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("Error: Timeout getting Trakt device code.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error getting Trakt device code: {e}")
        if response is not None: print(f"Response content: {response.text}")
        return None

def poll_trakt_token(device_code_info):
    """Polls Trakt to exchange the device code for an access token."""
    url = f"{TRAKT_API_URL}/oauth/device/token"
    payload = {
        "client_id": TRAKT_CLIENT_ID,
        "client_secret": TRAKT_CLIENT_SECRET,
        "code": device_code_info["device_code"],
    }
    interval = device_code_info["interval"]
    expires_in = device_code_info["expires_in"]
    start_time = time.time()

    print("Polling for Trakt authorization...")
    while time.time() - start_time < expires_in:
        time.sleep(interval)
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print("Authentication successful!")
                tokens = response.json()
                tokens['created_at'] = time.time()
                return tokens
            elif response.status_code == 400: continue # Waiting for user
            elif response.status_code in [404, 410]: print("Error: Device code expired."); return None
            elif response.status_code == 409: print("Error: Device code already used."); return None
            elif response.status_code == 418: print("Error: User denied authorization."); return None
            elif response.status_code == 429: print("Warning: Rate limited by Trakt during auth. Waiting longer..."); time.sleep(interval * 2)
            else: response.raise_for_status() # Raise for other unexpected errors
        except requests.exceptions.Timeout:
            print("Warning: Timeout polling for Trakt token.") # Continue polling
        except requests.exceptions.RequestException as e:
            print(f"Error polling for Trakt token: {e}")
            time.sleep(5) # Wait a bit longer after general network errors

    print("Error: Authentication timed out.")
    return None

def refresh_trakt_token(refresh_token):
    """Refreshes the Trakt access token."""
    print("Refreshing Trakt token...")
    url = f"{TRAKT_API_URL}/oauth/token"
    payload = {
        "refresh_token": refresh_token,
        "client_id": TRAKT_CLIENT_ID,
        "client_secret": TRAKT_CLIENT_SECRET,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "grant_type": "refresh_token",
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        tokens = response.json()
        tokens['created_at'] = time.time()
        print("Token refreshed successfully.")
        return tokens
    except requests.exceptions.Timeout:
        print("Error: Timeout refreshing Trakt token.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error refreshing Trakt token: {e}")
        if response is not None: print(f"Response content: {response.text}")
        return None

def get_trakt_access_token():
    """Handles the entire Trakt authentication process (load, auth, refresh)."""
    tokens = load_tokens()
    if tokens:
        # Check if token is expired (Trakt tokens last 3 months = ~7,776,000 seconds)
        # Use a buffer (e.g., 1 day = 86400 seconds)
        if time.time() < tokens.get('created_at', 0) + tokens.get('expires_in', 0) - 86400:
            # print("Using existing Trakt token.") # Less verbose
            return tokens.get('access_token')
        elif 'refresh_token' in tokens:
            print("Trakt token expired, attempting refresh...")
            new_tokens = refresh_trakt_token(tokens['refresh_token'])
            if new_tokens:
                save_tokens(new_tokens)
                return new_tokens.get('access_token')
            else: print("Token refresh failed. Need to re-authenticate.")
        else: print("Token expired and no refresh token found. Need to re-authenticate.")

    print("\n--- Trakt Authentication Required ---")
    device_code_info = get_trakt_device_code()
    if not device_code_info: return None
    print(f"1. Go to: {device_code_info.get('verification_url', 'URL missing')}")
    print(f"2. Enter code: {device_code_info.get('user_code', 'CODE missing')} (Expires in {device_code_info.get('expires_in', 'N/A')}s)")
    print("3. Authorize the application on Trakt.tv.")
    print("-------------------------------------\n")
    new_tokens = poll_trakt_token(device_code_info)
    if new_tokens:
        save_tokens(new_tokens)
        return new_tokens.get('access_token')
    else:
        print("Trakt authentication failed.")
        return None

def get_anilist_data(username):
    """Fetches all COMPLETED and CURRENT anime for a given AniList user."""
    all_entries = []
    page = 1
    has_next_page = True
    # Ensure score format is correct
    query = """
    query ($username: String, $page: Int, $perPage: Int, $type: MediaType) {
        Page (page: $page, perPage: $perPage) {
            pageInfo { hasNextPage }
            mediaList (userName: $username, type: $type, status_in: [COMPLETED, CURRENT]) {
                status score(format: POINT_100) progress
                startedAt { year month day } completedAt { year month day } updatedAt
                media {
                    idMal id title { romaji english native }
                    format type startDate { year }
                }
            }
        }
    }"""
    variables = {"username": username, "perPage": 50, "type": "ANIME"}
    print(f"Fetching ANIME list for user '{username}' from AniList...")
    while has_next_page:
        variables["page"] = page
        try:
            response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables}, timeout=20)
            response.raise_for_status()
            data = response.json()
            if "errors" in data and data["errors"]: # Check if errors list is not empty
                print(f"AniList API Error: {data['errors']}")
                return None
            page_data = data.get('data', {}).get('Page', {})
            if not page_data: # Handle case where Page might be null
                 print(f"Warning: No page data received from AniList for page {page}. Stopping.")
                 break
            media_list = page_data.get('mediaList', [])
            # Ensure media type is ANIME even if query filter fails somehow
            anime_list = [e for e in media_list if e.get('media', {}).get('type') == 'ANIME']
            all_entries.extend(anime_list)
            has_next_page = page_data.get('pageInfo', {}).get('hasNextPage', False)
            if has_next_page: print(f"Fetched page {page}..."); page += 1; time.sleep(0.8) # Slightly increased delay
            else: print(f"Fetched page {page}. No more pages.")
        except requests.exceptions.Timeout:
            print(f"Error: Timeout fetching page {page} from AniList. Retrying once...")
            time.sleep(5) # Wait before retry
            try: # Simple retry
                 response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables}, timeout=30)
                 response.raise_for_status()
                 # Process response same as above...
                 data = response.json()
                 if "errors" in data and data["errors"]: print(f"AniList API Error on retry: {data['errors']}"); return None
                 page_data = data.get('data', {}).get('Page', {})
                 if not page_data: print(f"Warning: No page data received on retry page {page}. Stopping."); break
                 media_list = page_data.get('mediaList', [])
                 anime_list = [e for e in media_list if e.get('media', {}).get('type') == 'ANIME']
                 all_entries.extend(anime_list)
                 has_next_page = page_data.get('pageInfo', {}).get('hasNextPage', False)
                 if has_next_page: print(f"Fetched page {page} (after retry)..."); page += 1; time.sleep(0.8)
                 else: print(f"Fetched page {page} (after retry). No more pages.")
            except Exception as e_retry:
                 print(f"Error fetching page {page} from AniList even after retry: {e_retry}")
                 return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching page {page} from AniList: {e}")
            if response is not None: print(f"Status: {response.status_code}, Text: {response.text[:200]}")
            return None
        except json.JSONDecodeError:
            print(f"Error decoding AniList response page {page}. Content: {response.text[:200]}")
            return None
    print(f"Found {len(all_entries)} anime entries on AniList.")
    return all_entries

# --- CORRECTED search_trakt ---
def search_trakt(title_romaji, title_english, anilist_mal_id, year, media_format, access_token):
    """Searches Trakt for a show or movie using title and year.
    NOTE: Direct MAL ID URL lookup is not supported by Trakt API, relying on title search."""
    search_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    trakt_type = None
    if media_format in ["TV", "OVA", "ONA", "SPECIAL", "TV_SHORT"]: trakt_type = "show"
    elif media_format == "MOVIE": trakt_type = "movie"
    else: return None # Skip unsupported formats

    display_title = title_english or title_romaji # For logging

    # --- Title Search Only ---
    search_titles = [t for t in [title_english, title_romaji] if t and t.strip()] # Ensure non-empty titles
    if not search_titles:
        # Don't write to tqdm here, let main loop handle skipping
        # tqdm.write(f"Skipping AniList entry MAL:{anilist_mal_id}: No usable title found.")
        return None

    for title in search_titles:
        # Basic normalization: remove diacritics (accents)
        try:
            nfkd_form = unicodedata.normalize('NFKD', title)
            normalized_title = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
            if not normalized_title.strip(): continue # Skip if normalization resulted in empty string
        except Exception:
            normalized_title = title # Fallback if normalization fails

        # Limit search query length if necessary (Trakt might have limits)
        query = requests.utils.quote(normalized_title[:100].encode('utf-8')) # Ensure proper encoding for URL

        search_url = f"{TRAKT_API_URL}/search/{trakt_type}?query={query}"
        if year:
             search_url += f"&years={year}" # Year filter is important

        try:
            # Use a reasonable delay between title searches to avoid hitting limits implicitly
            time.sleep(0.4)
            response = requests.get(search_url, headers=search_headers, timeout=15)

            if response.status_code == 404:
                 continue # Not found by this specific title variation, try the next one

            response.raise_for_status() # Handle other errors (401, 429, 5xx)
            results = response.json()

            if results:
                # Return the first result. Accuracy depends solely on Trakt's title/year search relevance.
                # Consider adding fuzzy matching score check here in the future if needed.
                return results[0] # Take first result

        except requests.exceptions.Timeout:
            tqdm.write(f"Warning: Timeout searching Trakt by title: '{normalized_title}'")
        except requests.exceptions.RequestException as e:
             # Don't flood warnings for 404, but log others
             if response is None or response.status_code != 404:
                status_code = response.status_code if response else 'N/A'
                error_text = response.text[:150] if response else "No response text"
                tqdm.write(f"Warning: Trakt title search failed ('{normalized_title}', Type: {trakt_type}): {e} - Status: {status_code}")
        except json.JSONDecodeError:
             tqdm.write(f"Warning: Error decoding Trakt title search response for '{normalized_title}'. Content: {response.text[:150]}")
        except Exception as e: # Catch unexpected errors during processing
            tqdm.write(f"Unexpected error during title search for '{title}': {e}")

    # If loop finishes without returning a result
    return None


def format_watched_at(anilist_date):
    """Converts AniList date dict to ISO 8601 string (UTC) or returns None."""
    if not anilist_date or not all(k in anilist_date and anilist_date[k] is not None for k in ['year', 'month', 'day']):
        return None
    try:
        # Ensure year is within reasonable bounds if needed (e.g., > 1900)
        if anilist_date['year'] < 1900: return None
        dt = datetime.datetime(anilist_date['year'], anilist_date['month'], anilist_date['day'])
        # Format as UTC ISO 8601 with Z suffix
        return dt.replace(tzinfo=datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (ValueError, TypeError): return None # Handle invalid dates (e.g., Feb 30)

def convert_score_to_rating(anilist_score):
    """Converts AniList 0-100 score to Trakt 1-10 rating. Skips 0 score."""
    if anilist_score is None or anilist_score <= 0: return None
    # Round to nearest integer for rating
    rating = round(float(anilist_score) / 10.0)
    return max(1, min(10, rating)) # Clamp to 1-10

def _send_trakt_sync_batch(endpoint, payload_key, items, access_token):
    """Generic function to send a batch to a Trakt sync endpoint."""
    if not items: return True, 0 # Success, 0 items sent
    url = f"{TRAKT_API_URL}/{endpoint}"
    auth_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    payload = {"shows": [], "movies": []}
    item_count = 0

    for item in items:
        # Prepare entry based on whether it's for history or ratings
        entry = {}
        if endpoint == "sync/history":
             entry = {"watched_at": item["watched_at"], "ids": item["trakt_ids"]}
        elif endpoint == "sync/ratings":
             # Ensure rating is int
             entry = {"rated_at": item["rated_at"], "rating": int(item["rating"]), "ids": item["trakt_ids"]}
        else:
             print(f"Error: Unknown endpoint '{endpoint}' in _send_trakt_sync_batch")
             return False, 0

        if item["type"] == "show": payload["shows"].append(entry); item_count += 1
        elif item["type"] == "movie": payload["movies"].append(entry); item_count +=1

    if not payload["shows"] and not payload["movies"]: return True, 0 # Nothing valid to send

    try:
        response = requests.post(url, headers=auth_headers, json=payload, timeout=30) # Increased timeout for sync
        response_data = {}
        try:
            response_data = response.json() # Try to get response data even if error occurs
        except json.JSONDecodeError:
             pass # Ignore if response body isn't valid JSON on error

        response.raise_for_status() # Check for HTTP errors AFTER getting data
        # print(f"DEBUG: Trakt {endpoint} response: {response_data}") # Optional debug
        # Could refine item_count based on response_data['added'] if needed, but approx count is ok
        return True, item_count
    except requests.exceptions.Timeout:
        print(f"\nError: Timeout adding {payload_key.upper()} batch to Trakt ({endpoint})")
        return False, 0
    except requests.exceptions.RequestException as e:
        error_content = response.text if response is not None else "No response"
        print(f"\nError adding {payload_key.upper()} batch to Trakt ({endpoint}): {e}")
        print(f"Response status: {response.status_code if response else 'N/A'}, Content sample: {error_content[:500]}") # Limit error length
        if response is not None and response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 15)) # Default retry slightly higher
            print(f"Rate limited. Waiting {retry_after}s before retrying {payload_key.upper()}...")
            time.sleep(retry_after)
            # Retry ONCE
            try:
                response = requests.post(url, headers=auth_headers, json=payload, timeout=45) # Longer timeout on retry
                response.raise_for_status()
                print("Retry successful.")
                return True, item_count # Return success on retry
            except Exception as e2:
                 error_content_retry = response.text if response is not None else "No response"
                 print(f"Error on retry adding {payload_key.upper()} batch: {e2}")
                 print(f"Retry Response: {response.status_code if response else 'N/A'} {error_content_retry[:500]}")
                 return False, 0 # Failed even after retry
        return False, 0 # General failure
    except json.JSONDecodeError: # Should be caught above, but as fallback
        print(f"Error decoding Trakt {payload_key} response. Content: {response.text[:500]}")
        return False, 0

def add_to_trakt_history(items_to_add, access_token):
    """Adds batch to Trakt watched history. Returns success bool, count added."""
    return _send_trakt_sync_batch("sync/history", "history", items_to_add, access_token)

def add_to_trakt_ratings(items_to_rate, access_token):
    """Adds batch to Trakt ratings. Returns success bool, count added."""
    return _send_trakt_sync_batch("sync/ratings", "ratings", items_to_rate, access_token)


def _get_trakt_sync_ids(endpoint, access_token):
    """Fetches all Trakt IDs for a given sync endpoint (watched or ratings)."""
    ids = set()
    # Trakt sync endpoints don't typically paginate, but might have implicit limits.
    # If lists are huge (>1000 items), pagination might be needed for other endpoints.
    url = f"{TRAKT_API_URL}/{endpoint}"
    auth_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=auth_headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        for item in data:
            item_type = 'show' if 'show' in item else 'movie' if 'movie' in item else None
            # Ensure IDs exist before trying to access them
            ids_obj = item.get(item_type, {}).get('ids', {})
            if item_type and ids_obj and ids_obj.get('trakt'):
                trakt_id = ids_obj['trakt']
                ids.add(f"{item_type}_{trakt_id}") # e.g., "show_123"
        return ids
    except requests.exceptions.Timeout:
        print(f"Error: Timeout fetching existing Trakt data from {endpoint}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching existing Trakt data from {endpoint}: {e}")
        if response is not None: print(f"Status: {response.status_code}, Text: {response.text[:500]}")
        return None # Indicate failure
    except json.JSONDecodeError:
        print(f"Error decoding Trakt response from {endpoint}. Content: {response.text[:500]}")
        return None

def get_trakt_watched_ids(access_token):
    """Fetches all watched show and movie Trakt IDs."""
    print("Fetching existing watched history from Trakt...")
    watched_show_ids = _get_trakt_sync_ids("sync/watched/shows", access_token)
    time.sleep(API_CALL_DELAY)
    watched_movie_ids = _get_trakt_sync_ids("sync/watched/movies", access_token)
    if watched_show_ids is None or watched_movie_ids is None: return None
    all_watched_ids = watched_show_ids.union(watched_movie_ids)
    print(f"Found {len(all_watched_ids)} existing watched items on Trakt.")
    return all_watched_ids

def get_trakt_rated_ids(access_token):
    """Fetches all rated show and movie Trakt IDs."""
    print("Fetching existing ratings from Trakt...")
    rated_show_ids = _get_trakt_sync_ids("sync/ratings/shows", access_token)
    time.sleep(API_CALL_DELAY)
    rated_movie_ids = _get_trakt_sync_ids("sync/ratings/movies", access_token)
    if rated_show_ids is None or rated_movie_ids is None: return None
    all_rated_ids = rated_show_ids.union(rated_movie_ids)
    print(f"Found {len(all_rated_ids)} existing rated items on Trakt.")
    return all_rated_ids

# --- Stylish Print Function ---
def print_boxed_attribution():
    """Prints the attribution in a simple box."""
    name = "Made by Nikoloz Taturashvili"
    width = len(name) + 4 # Adjust padding
    print("\n" + " " * 4 + "┌" + "─" * width + "┐")
    print(" " * 4 + "│" + " " * width + "│")
    print(" " * 4 + "│" + name.center(width) + "│")
    print(" " * 4 + "│" + " " * width + "│")
    print(" " * 4 + "└" + "─" * width + "┘")


# --- Main Execution ---
if __name__ == "__main__":
    # Basic config check
    if "YOUR_TRAKT_CLIENT_ID" in TRAKT_CLIENT_ID or "YOUR_TRAKT_CLIENT_SECRET" in TRAKT_CLIENT_SECRET or "YOUR_ANILIST_USERNAME" in ANILIST_USERNAME:
        print("Error: Please update TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET, and ANILIST_USERNAME in the script.")
        exit(1)

    print("--- AniList to Trakt Migration Script ---")

    # 1. Authenticate with Trakt
    access_token = get_trakt_access_token()
    if not access_token:
        print("Exiting due to Trakt authentication failure.")
        exit(1)
    # print("Trakt authentication successful.") # Less verbose

    # 2. Fetch Existing Trakt Data
    existing_watched_ids = get_trakt_watched_ids(access_token)
    if existing_watched_ids is None:
        print("Exiting due to failure fetching existing Trakt watched history.")
        exit(1)
    time.sleep(API_CALL_DELAY)

    existing_rated_ids = get_trakt_rated_ids(access_token)
    if existing_rated_ids is None:
        print("Exiting due to failure fetching existing Trakt ratings.")
        exit(1)
    time.sleep(API_CALL_DELAY)

    # 3. Fetch AniList Data
    anilist_entries = get_anilist_data(ANILIST_USERNAME)
    if anilist_entries is None:
        print("Exiting due to failure fetching AniList data.")
        exit(1)

    # Filter for COMPLETED anime (primary target for migration)
    completed_anime = [
        e for e in anilist_entries
        if e.get('status') == 'COMPLETED' and e.get('media', {}).get('type') == 'ANIME'
    ]

    if not completed_anime:
        print("No completed anime found on AniList profile to process.")
        exit(0)

    print(f"\nFound {len(completed_anime)} completed AniList anime to process.")
    print("Will skip items already marked as watched or rated on Trakt.")
    print("Will attempt to rate each Trakt show/movie ID only once per run.")

    # --- Initialize counters and batches ---
    trakt_history_batch = []
    trakt_ratings_batch = []
    rated_trakt_ids_this_run = set() # Tracks Trakt IDs rated *in this execution*
    skipped_not_found = 0
    skipped_already_watched = 0
    skipped_already_rated = 0
    skipped_rated_this_run = 0 # Count ratings skipped due to being rated earlier *in this run*
    history_prepared_count = 0
    ratings_prepared_count = 0
    total_history_synced = 0 # Approximate count based on successful batches
    total_ratings_synced = 0 # Approximate count based on successful batches
    failed_history_batches = 0
    failed_ratings_batches = 0

    print("\nSearching Trakt (using title/year), checking for duplicates, and preparing batches...")
    # --- Main Processing Loop ---
    for entry in tqdm(completed_anime, desc="Processing AniList Entries"):
        media = entry.get('media', {})
        if not media: continue # Skip entry if media block is missing

        # Extract data from AniList entry
        title_romaji = media.get('title', {}).get('romaji')
        title_english = media.get('title', {}).get('english')
        anilist_mal_id = media.get('idMal') # Keep for logging/potential future use
        anilist_id = media.get('id') # For logging if title is missing
        year = media.get('startDate', {}).get('year')
        media_format = media.get('format')
        anilist_score = entry.get('score')
        display_title = title_english or title_romaji or f"AniList ID: {anilist_id}"

        # Search on Trakt (using corrected title-only search)
        trakt_match = search_trakt(title_romaji, title_english, anilist_mal_id, year, media_format, access_token)

        if trakt_match:
            trakt_ids = None
            item_type = None
            specific_trakt_id = None
            item_data = None # Store show/movie data block

            if 'show' in trakt_match:
                item_type = "show"
                item_data = trakt_match.get('show')
            elif 'movie' in trakt_match:
                item_type = "movie"
                item_data = trakt_match.get('movie')

            if item_data:
                 trakt_ids = item_data.get('ids')

            # Ensure we have the necessary IDs
            if trakt_ids and item_type and trakt_ids.get('trakt'):
                specific_trakt_id = trakt_ids['trakt']
                trakt_composite_id = f"{item_type}_{specific_trakt_id}"

                # --- History Check ---
                if trakt_composite_id in existing_watched_ids:
                    skipped_already_watched += 1
                else:
                    # Prepare History Item
                    watched_at = format_watched_at(entry.get('completedAt'))
                    # Fallback timestamp MUST be in correct ISO 8601 UTC format
                    watched_at_fallback = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                    trakt_history_batch.append({
                        "type": item_type, "trakt_ids": trakt_ids,
                        "watched_at": watched_at or watched_at_fallback, "title": display_title
                    })
                    history_prepared_count += 1

                # --- Rating Check ---
                trakt_rating = convert_score_to_rating(anilist_score)
                if trakt_rating is not None: # Only proceed if there's a valid score from AniList
                    if trakt_composite_id in existing_rated_ids:
                        skipped_already_rated += 1
                    elif trakt_composite_id in rated_trakt_ids_this_run: # Check if rated earlier *in this run*
                        skipped_rated_this_run += 1
                    else:
                        # Add to rating batch AND mark as rated for this run
                        rated_at = format_watched_at(entry.get('completedAt')) or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                        trakt_ratings_batch.append({
                            "type": item_type, "trakt_ids": trakt_ids,
                            "rating": trakt_rating, "rated_at": rated_at, "title": display_title
                        })
                        ratings_prepared_count += 1
                        rated_trakt_ids_this_run.add(trakt_composite_id) # Mark as handled for rating this run
                # No else needed: if no score, or already rated (before or during run), do nothing.

            else:
                 # This means Trakt search result was malformed or missing IDs
                 tqdm.write(f"Skipping '{display_title}' (MAL: {anilist_mal_id}): Could not extract valid Trakt IDs from search result.")
                 skipped_not_found += 1
        else:
            # tqdm.write(f"Skipping '{display_title}' (MAL: {anilist_mal_id}): Not found on Trakt via title search.") # Optional: verbose skip log
            skipped_not_found += 1

        # --- Batch Sending Logic ---
        # Check and send history batch if full
        if len(trakt_history_batch) >= BATCH_SIZE:
            tqdm.write(f"Adding HISTORY batch ({len(trakt_history_batch)} items)...")
            success, count_synced = add_to_trakt_history(trakt_history_batch, access_token)
            if success: total_history_synced += count_synced
            else: failed_history_batches += 1 # Error message printed in function
            trakt_history_batch = [] # Clear the batch regardless of success
            time.sleep(API_CALL_DELAY) # Delay after API call

        # Check and send ratings batch if full
        if len(trakt_ratings_batch) >= BATCH_SIZE:
            tqdm.write(f"Adding RATINGS batch ({len(trakt_ratings_batch)} items)...")
            success, count_synced = add_to_trakt_ratings(trakt_ratings_batch, access_token)
            if success: total_ratings_synced += count_synced
            else: failed_ratings_batches += 1
            trakt_ratings_batch = []
            time.sleep(API_CALL_DELAY)

    # --- Send Final Batches ---
    if trakt_history_batch:
        tqdm.write(f"Adding final HISTORY batch ({len(trakt_history_batch)} items)...")
        success, count_synced = add_to_trakt_history(trakt_history_batch, access_token)
        if success: total_history_synced += count_synced
        else: failed_history_batches += 1
        time.sleep(API_CALL_DELAY) # Delay even after last history if ratings follow

    if trakt_ratings_batch:
        tqdm.write(f"Adding final RATINGS batch ({len(trakt_ratings_batch)} items)...")
        success, count_synced = add_to_trakt_ratings(trakt_ratings_batch, access_token)
        if success: total_ratings_synced += count_synced
        else: failed_ratings_batches += 1
        # No delay needed after very last API call

    # --- Final Summary ---
    print("\n--- Migration Summary ---")
    print(f"Processed {len(completed_anime)} completed AniList anime entries.")
    print(f"Skipped {skipped_not_found} entries (not found on Trakt via title/year).")
    print(f"Skipped {skipped_already_watched} entries (already in Trakt history).")
    print(f"Skipped {skipped_already_rated} entries (already rated on Trakt before run).")
    print(f"Skipped {skipped_rated_this_run} ratings (Trakt item already rated in this run).")
    print("-" * 20)
    print(f"History Sync: Prepared {history_prepared_count} new entries.")
    print(f"              Successfully synced approx {total_history_synced} history entries.")
    if failed_history_batches > 0:
         print(f"!!! {failed_history_batches} HISTORY batches failed or partially failed. Check logs above.")
    print("-" * 20)
    print(f"Ratings Sync: Prepared {ratings_prepared_count} new entries (score > 0, not rated before).")
    print(f"              Successfully synced approx {total_ratings_synced} rating entries.")
    if failed_ratings_batches > 0:
         print(f"!!! {failed_ratings_batches} RATINGS batches failed or partially failed. Check logs above.")
    print("------------------------")
    print("Migration complete.")

    # --- Attribution ---
    print_boxed_attribution()