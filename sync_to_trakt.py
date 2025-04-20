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
# --------------------------------------------------------------------------
# REQUIRED: Register Trakt App: https://trakt.tv/oauth/applications/new
TRAKT_CLIENT_ID = "TRAKT_CLIENT_ID" # Paste your Trakt Client ID here
TRAKT_CLIENT_SECRET = "TRAKT_CLIENT_SECRET" # Paste your Trakt Client Secret here

# REQUIRED: Set Data Source ('MAL' or 'AniList')
DATA_SOURCE = "MAL" # Choose 'MAL' for MyAnimeList or 'AniList'

# --- Source Specific Configuration ---

# ---> If DATA_SOURCE is 'MAL':
#      REQUIRED: Register MAL App: https://myanimelist.net/apiconfig
#      (Choose 'other' app type, Redirect URI isn't strictly needed but you might need to enter one like http://localhost)
MAL_CLIENT_ID = "MAL_CLIENT_ID" # Paste your MAL Client ID here
MAL_USERNAME = "MAL_USERNAME" # Paste the MAL Username whose list you want to sync

# ---> If DATA_SOURCE is 'AniList':
ANILIST_USERNAME = "ANILIST_USERNAME" # Paste the AniList Username whose list you want to sync
# --------------------------------------------------------------------------

# File to store Trakt tokens (will be created automatically)
TRAKT_TOKEN_FILE = "trakt_tokens.json"

# --- Constants ---
ANILIST_API_URL = "https://graphql.anilist.co"
MAL_API_URL = "https://api.myanimelist.net/v2"
TRAKT_API_URL = "https://api.trakt.tv"
TRAKT_HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": TRAKT_CLIENT_ID,
}
# Number of items to send to Trakt in one batch
BATCH_SIZE = 50
# Delay between Trakt API calls (seconds)
API_CALL_DELAY = 1.5
# Delay between Source API calls (seconds) - Increase if rate limited
# MAL Rate Limit is stricter (~60/min), AniList is generally more lenient
SOURCE_API_DELAY = 1.2 if DATA_SOURCE == "MAL" else 0.8

# --- Helper Functions ---

# --- Token Loading/Saving (Only Trakt) ---
def load_tokens_generic(token_file):
    """Loads tokens from a specified file."""
    if os.path.exists(token_file):
        try:
            with open(token_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load token file {token_file}: {e}. Need to re-authenticate.")
            return None
    return None

def save_tokens_generic(tokens, token_file):
    """Saves tokens to a specified file."""
    try:
        with open(token_file, 'w') as f:
            json.dump(tokens, f, indent=4)
    except IOError as e:
        print(f"Error: Could not save tokens to {token_file}: {e}")

# --- Trakt Authentication ---

def load_trakt_tokens():
    return load_tokens_generic(TRAKT_TOKEN_FILE)

def save_trakt_tokens(tokens):
    save_tokens_generic(tokens, TRAKT_TOKEN_FILE)

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
        response_text = getattr(response, 'text', 'No response text available')
        print(f"Error getting Trakt device code: {e}")
        print(f"Response content: {response_text}")
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
            status_code = response.status_code
            if status_code == 200:
                print("Trakt Authentication successful!")
                tokens = response.json()
                tokens['acquired_at'] = time.time()
                return tokens
            elif status_code == 400: continue # Waiting for user
            elif status_code in [404, 410]: print("Error: Trakt Device code expired."); return None
            elif status_code == 409: print("Error: Trakt Device code already used."); return None
            elif status_code == 418: print("Error: User denied Trakt authorization."); return None
            elif status_code == 429: print("Warning: Rate limited by Trakt during auth. Waiting longer..."); time.sleep(interval * 2)
            else: response.raise_for_status() # Raise for other unexpected errors
        except requests.exceptions.Timeout:
            print("Warning: Timeout polling for Trakt token.")
        except requests.exceptions.RequestException as e:
            print(f"Error polling for Trakt token: {e}")
            time.sleep(5)

    print("Error: Trakt Authentication timed out.")
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
        tokens['acquired_at'] = time.time()
        print("Trakt Token refreshed successfully.")
        return tokens
    except requests.exceptions.Timeout:
        print("Error: Timeout refreshing Trakt token.")
        return None
    except requests.exceptions.RequestException as e:
        response_text = getattr(response, 'text', 'No response text available')
        print(f"Error refreshing Trakt token: {e}")
        print(f"Response content: {response_text}")
        return None

def get_trakt_access_token():
    """Handles the entire Trakt authentication process (load, auth, refresh)."""
    tokens = load_trakt_tokens()
    if tokens:
        expires_at = tokens.get('acquired_at', 0) + tokens.get('expires_in', 0)
        # Use a buffer (e.g., 1 day = 86400 seconds)
        if time.time() < expires_at - 86400:
            return tokens.get('access_token')
        elif 'refresh_token' in tokens:
            print("Trakt token expired, attempting refresh...")
            new_tokens = refresh_trakt_token(tokens['refresh_token'])
            if new_tokens:
                save_trakt_tokens(new_tokens)
                return new_tokens.get('access_token')
            else:
                print("Trakt token refresh failed. Need to re-authenticate.")
                if os.path.exists(TRAKT_TOKEN_FILE):
                    try: os.remove(TRAKT_TOKEN_FILE)
                    except OSError as e: print(f"Error removing token file: {e}")
        else:
            print("Trakt token expired and no refresh token found. Need to re-authenticate.")
            if os.path.exists(TRAKT_TOKEN_FILE):
                try: os.remove(TRAKT_TOKEN_FILE)
                except OSError as e: print(f"Error removing token file: {e}")

    # --- Perform Device Authentication Flow ---
    print("\n--- Trakt Authentication Required ---")
    device_code_info = get_trakt_device_code()
    if not device_code_info: return None

    print(f"1. Go to: {device_code_info.get('verification_url', 'URL missing')}")
    print(f"2. Enter code: {device_code_info.get('user_code', 'CODE missing')} (Expires in {device_code_info.get('expires_in', 'N/A')} seconds)")
    print("3. Authorize the application on Trakt.tv.")
    print("-------------------------------------\n")

    new_tokens = poll_trakt_token(device_code_info)
    if new_tokens:
        save_trakt_tokens(new_tokens)
        return new_tokens.get('access_token')
    else:
        print("Trakt authentication failed.")
        return None

# --- Data Fetching ---

def get_anilist_data(username):
    """Fetches all COMPLETED and CURRENT anime for a given AniList user."""
    if not username or "YOUR_ANILIST_USERNAME" in username:
         print("Error: ANILIST_USERNAME not set correctly.")
         return None

    all_entries = []
    page = 1
    has_next_page = True
    # GraphQL query to get relevant fields
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
            time.sleep(SOURCE_API_DELAY)
            response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables}, timeout=20)
            response.raise_for_status()
            data = response.json()
            if "errors" in data and data["errors"]: # Check if errors list is not empty
                print(f"AniList API Error: {data['errors']}")
                return None
            page_data = data.get('data', {}).get('Page', {})
            if not page_data:
                 print(f"Warning: No page data received from AniList for page {page}. Stopping.")
                 break
            media_list = page_data.get('mediaList', [])
            # Filter for ANIME type just in case query filter fails
            anime_list = [e for e in media_list if e.get('media', {}).get('type') == 'ANIME']
            all_entries.extend(anime_list)
            has_next_page = page_data.get('pageInfo', {}).get('hasNextPage', False)
            if has_next_page: print(f"Fetched page {page}..."); page += 1;
            else: print(f"Fetched page {page}. No more pages.")
        except requests.exceptions.Timeout:
            print(f"Error: Timeout fetching page {page} from AniList. Retrying once...")
            time.sleep(5) # Wait before retry
            try: # Simple retry logic
                 response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables}, timeout=30)
                 response.raise_for_status()
                 data = response.json()
                 if "errors" in data and data["errors"]: print(f"AniList API Error on retry: {data['errors']}"); return None
                 page_data = data.get('data', {}).get('Page', {})
                 if not page_data: print(f"Warning: No page data received on retry page {page}. Stopping."); break
                 media_list = page_data.get('mediaList', [])
                 anime_list = [e for e in media_list if e.get('media', {}).get('type') == 'ANIME']
                 all_entries.extend(anime_list)
                 has_next_page = page_data.get('pageInfo', {}).get('hasNextPage', False)
                 if has_next_page: print(f"Fetched page {page} (after retry)..."); page += 1;
                 else: print(f"Fetched page {page} (after retry). No more pages.")
            except Exception as e_retry:
                 print(f"Error fetching page {page} from AniList even after retry: {e_retry}")
                 return None # Abort on retry failure
        except requests.exceptions.RequestException as e:
            response_text = getattr(response, 'text', 'No response text available')
            print(f"Error fetching page {page} from AniList: {e}")
            print(f"Status: {getattr(response, 'status_code', 'N/A')}, Text: {response_text[:200]}")
            return None
        except json.JSONDecodeError:
            response_text = getattr(response, 'text', 'No response text available')
            print(f"Error decoding AniList response page {page}. Content: {response_text[:200]}")
            return None
    print(f"Found {len(all_entries)} anime entries on AniList for user '{username}'.")
    return all_entries


def get_mal_anime_list(username, client_id):
    """Fetches all completed and watching anime for a specific MAL user (unauthenticated)."""
    if not username or "YOUR_MAL_USERNAME" in username:
        print("Error: MAL_USERNAME is not set in the script configuration.")
        return None
    if not client_id or "YOUR_MAL_CLIENT_ID" in client_id:
         print("Error: MAL_CLIENT_ID is not set correctly in the script.")
         return None

    all_entries = []
    # Request fields needed for processing and Trakt matching
    # node fields doc: https://myanimelist.net/apiconfig/references/api/v2#operation/users_user_id_animelist_get
    fields = "fields=list_status{status,score,start_date,finish_date,updated_at},node{id,title,alternative_titles{en},media_type,start_date}"
    # Fetch both completed and watching (though only completed are synced currently)
    statuses = ["completed", "watching"]
    limit = 100 # MAL API limit per page

    mal_headers = {
        "X-MAL-CLIENT-ID": client_id
    }

    print(f"Fetching ANIME list for user '{username}' from MyAnimeList (public API)...")
    print("Ensure the user's MAL Anime List is set to Public in their profile settings.")

    for status in statuses:
        print(f"Fetching '{status}' list for '{username}'...")
        # Endpoint for specific user's list
        url = f"{MAL_API_URL}/users/{username}/animelist?{fields}&status={status}&limit={limit}&nsfw=1" # Include NSFW by default

        page_num = 1
        while url:
            try:
                time.sleep(SOURCE_API_DELAY) # Delay before request
                response = requests.get(url, headers=mal_headers, timeout=20)

                # Handle specific HTTP errors for MAL public access
                if response.status_code == 404:
                     print(f"Error: Received 404 Not Found when fetching '{status}' list for user '{username}'.")
                     print("Please double-check the MAL_USERNAME in the script configuration.")
                     url = None; continue
                elif response.status_code == 403:
                     print(f"Error: Received 403 Forbidden when fetching '{status}' list for user '{username}'.")
                     print("This usually means the user's list is private.")
                     print("Ensure the target MAL list is set to 'Public'. Cannot proceed with private lists.")
                     url = None; continue

                response.raise_for_status() # Check for other HTTP errors (429, 5xx)
                data = response.json()

                entries = data.get('data', [])
                all_entries.extend(entries)
                print(f"Fetched page {page_num} for status '{status}' ({len(entries)} items)...")

                # Get URL for next page from MAL's paging object
                url = data.get('paging', {}).get('next')
                page_num += 1

            except requests.exceptions.Timeout:
                print(f"Error: Timeout fetching page {page_num} (status: {status}) from MAL for user '{username}'. Retrying once...")
                time.sleep(5)
                try: # Simple retry
                    response = requests.get(url, headers=mal_headers, timeout=30)
                    # Repeat 404/403 checks on retry
                    if response.status_code == 404: print(f"Error on retry: 404 Not Found for user '{username}'. Check username."); url = None; continue
                    if response.status_code == 403: print(f"Error on retry: 403 Forbidden for user '{username}'. Check list privacy."); url = None; continue
                    response.raise_for_status()
                    data = response.json()
                    entries = data.get('data', [])
                    all_entries.extend(entries)
                    print(f"Fetched page {page_num} (status: {status}) after retry...")
                    url = data.get('paging', {}).get('next')
                    page_num += 1
                except Exception as e_retry:
                    print(f"Error fetching MAL page {page_num} (status: {status}) even after retry: {e_retry}")
                    url = None # Stop fetching for this status on retry failure
            except requests.exceptions.HTTPError as e:
                 print(f"HTTP Error fetching MAL page {page_num} (status: {status}): {e}")
                 if response is not None:
                     print(f"Status: {response.status_code}, Response: {response.text[:500]}")
                     if response.status_code == 429:
                          print("Rate limited by MAL API. Try increasing SOURCE_API_DELAY in script config.")
                 url = None # Stop fetching for this status
            except requests.exceptions.RequestException as e:
                print(f"Error fetching MAL page {page_num} (status: {status}): {e}")
                url = None
            except json.JSONDecodeError:
                response_text = getattr(response, 'text', 'No response text available')
                print(f"Error decoding MAL response page {page_num} (status: {status}). Content: {response_text[:200]}")
                url = None

    print(f"Found {len(all_entries)} total public anime entries (completed & watching) for user '{username}' on MyAnimeList.")
    return all_entries


def search_trakt(title_main, title_english, source_id_logging, year, media_format, access_token):
    """Searches Trakt for a show or movie using title and year."""
    search_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    trakt_type = None
    # Map source format to Trakt type ('show' or 'movie')
    if media_format in ["TV", "tv", "OVA", "ova", "ONA", "ona", "SPECIAL", "special", "TV_SHORT"]:
        trakt_type = "show"
    elif media_format in ["MOVIE", "movie"]:
        trakt_type = "movie"
    else:
        # Silently skip unsupported formats like MUSIC, UNKNOWN
        return None

    display_title = title_english or title_main # For logging purposes

    # Create a list of unique, non-empty titles to search
    search_titles = list(dict.fromkeys(filter(None, [title_english, title_main])))
    if not search_titles:
        return None # Skip if no usable titles

    for title in search_titles:
        if not title.strip(): continue

        # Basic title normalization (remove accents/diacritics)
        try:
            nfkd_form = unicodedata.normalize('NFKD', title)
            normalized_title = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
            if not normalized_title.strip(): continue
        except Exception:
            normalized_title = title # Fallback if normalization fails

        # Prepare URL-encoded query, limit length
        query = requests.utils.quote(normalized_title[:100].encode('utf-8'))
        search_url = f"{TRAKT_API_URL}/search/{trakt_type}?query={query}"
        # Add year filter if available for better matching
        if year:
             search_url += f"&years={year}"

        try:
            time.sleep(0.4) # Small delay between Trakt search API calls
            response = requests.get(search_url, headers=search_headers, timeout=15)

            if response.status_code == 404:
                 continue # Title not found, try next title variation if available

            response.raise_for_status() # Handle other errors (401, 429, 5xx)
            results = response.json()

            if results:
                # Basic check: Does the year in the result match the input year?
                trakt_result_year_str = results[0].get(trakt_type, {}).get('year')
                if year and trakt_result_year_str:
                    try:
                        if int(trakt_result_year_str) != int(year):
                            # Year mismatch, likely not the correct item, try next search title
                            continue
                    except (ValueError, TypeError): pass # Ignore if years cannot be compared

                # Return the first result, assuming Trakt's relevance sorting is good enough
                return results[0]

        except requests.exceptions.Timeout:
            tqdm.write(f"Warning: Timeout searching Trakt by title: '{normalized_title}' (Source ID: {source_id_logging})")
        except requests.exceptions.RequestException as e:
             # Log non-404 errors
             if response is None or response.status_code != 404:
                status_code = getattr(response, 'status_code', 'N/A')
                error_text = getattr(response, 'text', 'No response text')[:150]
                tqdm.write(f"Warning: Trakt title search failed ('{normalized_title}', Source ID: {source_id_logging}, Type: {trakt_type}): {e} - Status: {status_code}")
        except json.JSONDecodeError:
             tqdm.write(f"Warning: Error decoding Trakt title search response for '{normalized_title}'. Content: {getattr(response, 'text', 'N/A')[:150]}")
        except Exception as e: # Catch unexpected errors during processing
            tqdm.write(f"Unexpected error during title search for '{title}' (Source ID: {source_id_logging}): {e}")

    # If loop finishes without returning a result
    return None

# --- Date/Score Formatting ---

def format_anilist_date_to_iso(anilist_date):
    """Converts AniList date dict {year, month, day} to ISO 8601 string (UTC noon)."""
    if not anilist_date or not all(k in anilist_date and anilist_date[k] is not None for k in ['year', 'month', 'day']):
        return None
    try:
        if anilist_date['year'] < 1900: return None # Avoid potential invalid dates
        # Use noon to avoid potential timezone issues if user entered local date near midnight
        dt = datetime.datetime(anilist_date['year'], anilist_date['month'], anilist_date['day'], 12, 0, 0)
        # Format as UTC ISO 8601 with Z suffix for Trakt
        return dt.replace(tzinfo=datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, TypeError):
        # Handle invalid dates like Feb 30th
        return None

def format_mal_date_to_iso(mal_date_str):
    """Converts MAL 'YYYY-MM-DD' or empty string to ISO 8601 string (UTC noon)."""
    if not mal_date_str or not isinstance(mal_date_str, str): return None
    try:
        # MAL dates are YYYY-MM-DD
        dt = datetime.datetime.strptime(mal_date_str, '%Y-%m-%d')
        # Use noon UTC for consistency and to avoid timezone issues
        dt_aware = dt.replace(hour=12, tzinfo=datetime.timezone.utc)
        # Format as UTC ISO 8601 with Z suffix
        return dt_aware.isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, TypeError):
        # Handle potential parsing errors or invalid date strings
        return None


def convert_anilist_score_to_rating(anilist_score):
    """Converts AniList 0-100 score to Trakt 1-10 rating."""
    if anilist_score is None or anilist_score <= 0: return None # Skip 0 scores
    # Round score/10 to nearest integer
    rating = round(float(anilist_score) / 10.0)
    # Clamp result to Trakt's 1-10 range
    return max(1, min(10, rating))


def convert_mal_score_to_rating(mal_score):
    """Converts MAL 0-10 score to Trakt 1-10 rating."""
    if mal_score is None or not isinstance(mal_score, int) or mal_score <= 0: return None # Skip 0 scores
    # MAL score is already 1-10, just clamp it to be safe
    return max(1, min(10, mal_score))


# --- Trakt Sync Batch Sending ---
def _send_trakt_sync_batch(endpoint, payload_key, items, access_token):
    """Generic function to send a batch to a Trakt sync endpoint."""
    if not items: return True, 0
    url = f"{TRAKT_API_URL}/{endpoint}"
    auth_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    payload = {"shows": [], "movies": []}
    items_to_send_shows = []
    items_to_send_movies = []
    expected_item_count = 0

    # Prepare items and validate required fields
    for item in items:
        entry = {}
        if not item.get("type") or not item.get("trakt_ids"):
             tqdm.write(f"Warning: Skipping item in batch due to missing type or trakt_ids: {item.get('title', 'Unknown Title')}")
             continue

        if endpoint == "sync/history":
            if not item.get("watched_at"):
                 tqdm.write(f"Warning: Skipping history item due to missing watched_at: {item.get('title', 'Unknown Title')}")
                 continue
            entry = {"watched_at": item["watched_at"], "ids": item["trakt_ids"]}

        elif endpoint == "sync/ratings":
            if item.get("rating") is None:
                 tqdm.write(f"Warning: Skipping rating item due to missing rating: {item.get('title', 'Unknown Title')}")
                 continue
            entry = {
                 # Fallback 'rated_at' to now if missing (should be set earlier)
                 "rated_at": item.get("rated_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                 "rating": int(item["rating"]),
                 "ids": item["trakt_ids"]
             }
        else:
             print(f"Error: Unknown endpoint '{endpoint}' in _send_trakt_sync_batch")
             return False, 0 # Abort if endpoint is wrong

        # Add prepared entry to the correct list
        if item["type"] == "show": items_to_send_shows.append(entry); expected_item_count += 1
        elif item["type"] == "movie": items_to_send_movies.append(entry); expected_item_count += 1

    payload["shows"] = items_to_send_shows
    payload["movies"] = items_to_send_movies

    # Skip API call if no valid items were prepared
    if not payload["shows"] and not payload["movies"]:
        # tqdm.write(f"Info: No valid items to send in {payload_key.upper()} batch.")
        return True, 0

    # Make the API call to Trakt
    try:
        response = requests.post(url, headers=auth_headers, json=payload, timeout=30)
        response_data = {}
        try: response_data = response.json() # Try to parse JSON even on error for details
        except json.JSONDecodeError: pass

        response.raise_for_status() # Check for HTTP errors after getting potential response data

        # --- Parse Trakt Response for Approximate Count ---
        synced_count = 0
        added_section = response_data.get('added', {})
        if endpoint == "sync/history":
            # History adds episodes for shows, movies directly.
            # Count movies added + estimate shows added based on if any episodes were added.
            synced_count = added_section.get('movies', 0)
            if len(items_to_send_shows) > 0 and added_section.get('episodes', 0) > 0:
                 synced_count += len(items_to_send_shows) # Approx count for shows added
        elif endpoint == "sync/ratings":
            synced_count = added_section.get('shows', 0) + added_section.get('movies', 0)

        # Report potential mismatch between sent and added (can be normal)
        if synced_count != expected_item_count and expected_item_count > 0:
             tqdm.write(f"Info: Trakt {payload_key.upper()} sync response indicates {synced_count} items added (expected {expected_item_count}).")
             # Use the expected count for progress reporting, as Trakt count can be complex (e.g., history)
             # return True, synced_count # Alternative: return Trakt's count

        return True, expected_item_count # Return success and the number of items *sent*

    except requests.exceptions.Timeout:
        print(f"\nError: Timeout adding {payload_key.upper()} batch to Trakt ({endpoint})")
        return False, 0
    except requests.exceptions.RequestException as e:
        error_content = getattr(response, 'text', 'No response text')
        print(f"\nError adding {payload_key.upper()} batch to Trakt ({endpoint}): {e}")
        print(f"Response status: {getattr(response, 'status_code', 'N/A')}, Content sample: {error_content[:500]}")
        # Handle rate limiting with retry
        if response is not None and response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 15)) # Default 15s
            print(f"Rate limited. Waiting {retry_after}s before retrying {payload_key.upper()}...")
            time.sleep(retry_after)
            # Retry ONCE
            try:
                response_retry = requests.post(url, headers=auth_headers, json=payload, timeout=45)
                response_retry.raise_for_status()
                # Re-parse count on retry success
                response_data_retry = response_retry.json()
                synced_count_retry = 0
                added_section_retry = response_data_retry.get('added', {})
                if endpoint == "sync/history":
                     synced_count_retry = added_section_retry.get('movies', 0)
                     if len(items_to_send_shows) > 0 and added_section_retry.get('episodes', 0) > 0:
                          synced_count_retry += len(items_to_send_shows)
                elif endpoint == "sync/ratings":
                     synced_count_retry = added_section_retry.get('shows', 0) + added_section_retry.get('movies', 0)
                print(f"Retry successful. Synced approx {synced_count_retry} items.")
                return True, synced_count_retry # Return actual count from successful retry
            except Exception as e2:
                 error_content_retry = getattr(response_retry, 'text', 'No response text')
                 print(f"Error on retry adding {payload_key.upper()} batch: {e2}")
                 print(f"Retry Response: {getattr(response_retry, 'status_code', 'N/A')} {error_content_retry[:500]}")
                 return False, 0 # Failed even after retry
        return False, 0 # General failure
    except json.JSONDecodeError: # Fallback if JSON parsing failed earlier
        print(f"Error decoding Trakt {payload_key} response. Content: {getattr(response, 'text', 'N/A')[:500]}")
        return False, 0


def add_to_trakt_history(items_to_add, access_token):
    """Adds batch to Trakt watched history. Returns success bool, count added."""
    return _send_trakt_sync_batch("sync/history", "history", items_to_add, access_token)

def add_to_trakt_ratings(items_to_rate, access_token):
    """Adds batch to Trakt ratings. Returns success bool, count added."""
    return _send_trakt_sync_batch("sync/ratings", "ratings", items_to_rate, access_token)


# --- Trakt Existing Data Fetching ---
def _get_trakt_sync_ids(endpoint, access_token):
    """Fetches all Trakt IDs for a given sync endpoint (watched or ratings)."""
    ids = set()
    # Request a large limit, Trakt might cap it but worth asking.
    url = f"{TRAKT_API_URL}/{endpoint}?limit=10000"
    auth_headers = {**TRAKT_HEADERS, "Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=auth_headers, timeout=45) # Increase timeout for potentially large lists
        response.raise_for_status()
        data = response.json()
        # Ensure response is a list as expected
        if not isinstance(data, list):
             print(f"Error: Unexpected response format from {endpoint}. Expected a list.")
             print(f"Content sample: {str(data)[:500]}")
             return None

        # Extract Trakt IDs based on the endpoint's structure
        for item in data:
            item_type = None
            ids_obj = None
            # /sync/watched response structure
            if endpoint.startswith("sync/watched"):
                 if 'show' in item and item['show']: item_type = 'show'; ids_obj = item.get('show', {}).get('ids')
                 elif 'movie' in item and item['movie']: item_type = 'movie'; ids_obj = item.get('movie', {}).get('ids')
            # /sync/ratings response structure
            elif endpoint.startswith("sync/ratings"):
                 item_key = item.get('type') # 'show' or 'movie'
                 if item_key and item_key in item and item[item_key]:
                     item_type = item_key
                     ids_obj = item.get(item_key, {}).get('ids')

            # Add the composite ID (e.g., "show_12345") to the set
            if item_type and ids_obj and ids_obj.get('trakt'):
                trakt_id = ids_obj['trakt']
                ids.add(f"{item_type}_{trakt_id}")

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
    time.sleep(API_CALL_DELAY) # Delay between Trakt calls
    watched_movie_ids = _get_trakt_sync_ids("sync/watched/movies", access_token)
    # Check if either fetch failed
    if watched_show_ids is None or watched_movie_ids is None: return None
    # Combine the sets of IDs
    all_watched_ids = watched_show_ids.union(watched_movie_ids)
    print(f"Found {len(all_watched_ids)} existing watched items on Trakt.")
    return all_watched_ids

def get_trakt_rated_ids(access_token):
    """Fetches all rated show and movie Trakt IDs."""
    print("Fetching existing ratings from Trakt...")
    rated_show_ids = _get_trakt_sync_ids("sync/ratings/shows", access_token)
    time.sleep(API_CALL_DELAY) # Delay between Trakt calls
    rated_movie_ids = _get_trakt_sync_ids("sync/ratings/movies", access_token)
    # Check if either fetch failed
    if rated_show_ids is None or rated_movie_ids is None: return None
    # Combine the sets of IDs
    all_rated_ids = rated_show_ids.union(rated_movie_ids)
    print(f"Found {len(all_rated_ids)} existing rated items on Trakt.")
    return all_rated_ids


# --- Stylish Print Function ---
def print_boxed_attribution():
    """Prints the attribution in a simple box."""
    name = "Made by Nikoloz Taturashvili"
    # modification = "..." # Removed AI line
    width = len(name) + 4 # Adjust padding
    print("\n" + " " * 4 + "┌" + "─" * width + "┐")
    print(" " * 4 + "│" + " " * width + "│")
    print(" " * 4 + "│" + name.center(width) + "│")
    # print(" " * 4 + "│" + modification.center(width) + "│")
    print(" " * 4 + "│" + " " * width + "│")
    print(" " * 4 + "└" + "─" * width + "┘")


# --- Main Execution ---
if __name__ == "__main__":
    print(f"--- {DATA_SOURCE} to Trakt Migration Script ---")

    # --- Configuration Checks ---
    if "YOUR_TRAKT_CLIENT_ID" in TRAKT_CLIENT_ID or "YOUR_TRAKT_CLIENT_SECRET" in TRAKT_CLIENT_SECRET:
        print("Error: Please update TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET in the script configuration.")
        exit(1)

    if DATA_SOURCE == "MAL":
        if "YOUR_MAL_CLIENT_ID" in MAL_CLIENT_ID:
             print("Error: Please update MAL_CLIENT_ID in the script configuration.")
             exit(1)
        if not MAL_USERNAME or "YOUR_MAL_USERNAME" in MAL_USERNAME:
             print("Error: Please update MAL_USERNAME in the script configuration.")
             exit(1)
    elif DATA_SOURCE == "AniList":
        if not ANILIST_USERNAME or "YOUR_ANILIST_USERNAME" in ANILIST_USERNAME:
             print("Error: Please update ANILIST_USERNAME in the script configuration.")
             exit(1)
    else:
        print(f"Error: Invalid DATA_SOURCE selected: '{DATA_SOURCE}'. Choose 'MAL' or 'AniList'.")
        exit(1)


    # 1. Authenticate with Trakt (Always Required)
    trakt_access_token = get_trakt_access_token()
    if not trakt_access_token:
        print("Exiting due to Trakt authentication failure.")
        exit(1)

    # 2. Notify User about Source API Access Method
    if DATA_SOURCE == "MAL":
        print("MAL Sync selected: Using public API access (no user authentication required).")
    elif DATA_SOURCE == "AniList":
        print("AniList Sync selected: Using public API access.")

    # 3. Fetch Existing Trakt Data (to avoid duplicates)
    existing_watched_ids = get_trakt_watched_ids(trakt_access_token)
    if existing_watched_ids is None:
        print("Exiting due to failure fetching existing Trakt watched history.")
        exit(1)
    time.sleep(API_CALL_DELAY) # Delay before next Trakt API call

    existing_rated_ids = get_trakt_rated_ids(trakt_access_token)
    if existing_rated_ids is None:
        print("Exiting due to failure fetching existing Trakt ratings.")
        exit(1)
    time.sleep(API_CALL_DELAY) # Delay before fetching from source

    # 4. Fetch Source Data (MAL or AniList)
    source_entries = None
    print(f"\nFetching data from {DATA_SOURCE}...")
    if DATA_SOURCE == "MAL":
        source_entries = get_mal_anime_list(MAL_USERNAME, MAL_CLIENT_ID)
    elif DATA_SOURCE == "AniList":
        source_entries = get_anilist_data(ANILIST_USERNAME)

    # Handle potential failure during source data fetch
    if source_entries is None:
        print(f"Exiting due to failure fetching {DATA_SOURCE} data. Check logs above for details (e.g., private list, wrong username, API errors).")
        exit(1)
    if not source_entries:
         print(f"No anime entries found on {DATA_SOURCE} profile to process.")
         exit(0)

    # 5. Filter for Completed Anime (Primary target for sync)
    completed_anime = []
    if DATA_SOURCE == "MAL":
        completed_anime = [
            e for e in source_entries
            # Ensure entry has list_status and node, list status is 'completed', and media type is supported
            if e.get('list_status') and e.get('node') and
               e['list_status'].get('status') == 'completed' and
               e['node'].get('media_type') not in ['music', 'unknown'] # Exclude unsupported types
        ]
    elif DATA_SOURCE == "AniList":
        completed_anime = [
            e for e in source_entries
            # Ensure entry has status and media, status is COMPLETED, and type is ANIME
            if e.get('status') and e.get('media') and
               e['status'] == 'COMPLETED' and
               e['media'].get('type') == 'ANIME' # Ensure it's anime
        ]

    if not completed_anime:
        print(f"No *completed* and syncable anime found on {DATA_SOURCE} profile to process.")
        exit(0)

    print(f"\nFound {len(completed_anime)} completed {DATA_SOURCE} anime to process for Trakt sync.")
    print("Will skip items already marked as watched or rated on Trakt.")
    print("Will attempt to rate each Trakt show/movie ID only once per run.")

    # 6. Initialize counters and batches for Trakt sync
    trakt_history_batch = []
    trakt_ratings_batch = []
    # Keep track of items rated *during this run* to avoid duplicate rating attempts within the run
    rated_trakt_ids_this_run = set()
    # Statistics counters
    skipped_not_found = 0
    skipped_already_watched = 0
    skipped_already_rated = 0
    skipped_rated_this_run = 0
    skipped_unsupported_format = 0
    skipped_missing_data = 0
    history_prepared_count = 0
    ratings_prepared_count = 0
    total_history_synced = 0 # Based on successful batches sent
    total_ratings_synced = 0 # Based on successful batches sent
    failed_history_batches = 0
    failed_ratings_batches = 0
    # Get current time once for potential fallbacks
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


    print(f"\nSearching Trakt (using title/year), checking for duplicates, and preparing batches...")
    # --- Main Processing Loop ---
    for entry in tqdm(completed_anime, desc=f"Processing {DATA_SOURCE} Entries"):
        # --- Extract Data based on Source ---
        title_main = None; title_english = None; source_id = None; year = None
        media_format = None; source_score = None; completed_at_source_format = None

        try: # Add try-except block for safer data extraction
            if DATA_SOURCE == "MAL":
                node = entry.get('node', {})
                source_list_status = entry.get('list_status', {})
                # Basic validation moved to filter step, but double-check here if needed
                # if not node or not source_list_status: skipped_missing_data +=1; continue

                source_id = node.get('id')
                title_main = node.get('title')
                alt_titles = node.get('alternative_titles', {})
                title_english = alt_titles.get('en') if alt_titles else None
                # Extract year from start_date string (can be YYYY-MM-DD, YYYY-MM, YYYY)
                start_date_str = node.get('start_date')
                year = int(start_date_str[:4]) if start_date_str and len(start_date_str) >= 4 else None
                media_format = node.get('media_type')
                source_score = source_list_status.get('score') # MAL score: 0-10
                completed_at_source_format = source_list_status.get('finish_date') # 'YYYY-MM-DD' or ''

            elif DATA_SOURCE == "AniList":
                media = entry.get('media', {})
                # if not media: skipped_missing_data +=1; continue # Validation moved to filter
                source_list_status = entry

                source_id = media.get('id')
                title_main = media.get('title', {}).get('romaji')
                title_english = media.get('title', {}).get('english')
                year = media.get('startDate', {}).get('year')
                media_format = media.get('format')
                source_score = source_list_status.get('score') # AniList score: 0-100
                completed_at_source_format = source_list_status.get('completedAt') # { year, month, day } dict

            # Check for essential data after extraction
            display_title = title_english or title_main or f"{DATA_SOURCE} ID: {source_id}"
            if not (title_main or title_english):
                tqdm.write(f"Skipping {DATA_SOURCE} ID {source_id}: No title found.")
                skipped_missing_data += 1; continue
            if not media_format:
                 tqdm.write(f"Skipping '{display_title}' (ID: {source_id}): Missing media format.")
                 skipped_missing_data += 1; continue

        except Exception as e:
            tqdm.write(f"Error extracting data for an entry: {e} - Entry data: {entry}")
            skipped_missing_data += 1
            continue # Skip to next entry

        # --- Search Trakt ---
        trakt_match = search_trakt(title_main, title_english, source_id, year, media_format, trakt_access_token)

        if trakt_match:
            trakt_ids = None; item_type = None; specific_trakt_id = None; item_data = None

            # Extract Trakt item details
            if 'show' in trakt_match and trakt_match['show']:
                item_type = "show"; item_data = trakt_match.get('show')
            elif 'movie' in trakt_match and trakt_match['movie']:
                item_type = "movie"; item_data = trakt_match.get('movie')

            if item_data: trakt_ids = item_data.get('ids')

            # Proceed if we found a match with valid Trakt IDs
            if trakt_ids and item_type and trakt_ids.get('trakt'):
                specific_trakt_id = trakt_ids['trakt']
                trakt_composite_id = f"{item_type}_{specific_trakt_id}" # e.g., "show_123"

                # --- History Processing ---
                # Check against existing Trakt watched list
                if trakt_composite_id in existing_watched_ids:
                    skipped_already_watched += 1
                else:
                    # Format completion date to ISO string
                    watched_at = None
                    if DATA_SOURCE == "MAL": watched_at = format_mal_date_to_iso(completed_at_source_format)
                    elif DATA_SOURCE == "AniList": watched_at = format_anilist_date_to_iso(completed_at_source_format)

                    # Add to history batch using completion date or fallback to current time
                    trakt_history_batch.append({
                        "type": item_type, "trakt_ids": trakt_ids,
                        "watched_at": watched_at or now_iso,
                        "title": display_title # Keep title for potential debugging
                    })
                    history_prepared_count += 1

                # --- Rating Processing ---
                # Convert source score to Trakt rating (1-10)
                trakt_rating = None
                if DATA_SOURCE == "MAL": trakt_rating = convert_mal_score_to_rating(source_score)
                elif DATA_SOURCE == "AniList": trakt_rating = convert_anilist_score_to_rating(source_score)

                # Add rating only if score was valid (> 0)
                if trakt_rating is not None:
                    # Check against existing Trakt ratings and ratings added this run
                    if trakt_composite_id in existing_rated_ids:
                        skipped_already_rated += 1
                    elif trakt_composite_id in rated_trakt_ids_this_run:
                        skipped_rated_this_run += 1
                    else:
                        # Format completion date (same as watched_at) for rated_at timestamp
                        rated_at = None
                        if DATA_SOURCE == "MAL": rated_at = format_mal_date_to_iso(completed_at_source_format)
                        elif DATA_SOURCE == "AniList": rated_at = format_anilist_date_to_iso(completed_at_source_format)

                        # Add to ratings batch using completion date or fallback to current time
                        trakt_ratings_batch.append({
                            "type": item_type, "trakt_ids": trakt_ids,
                            "rating": trakt_rating,
                            "rated_at": rated_at or now_iso, # Use same date logic as history
                            "title": display_title # For debugging
                        })
                        ratings_prepared_count += 1
                        # Mark this Trakt item as rated *in this run*
                        rated_trakt_ids_this_run.add(trakt_composite_id)

            else: # Trakt search result was missing required ID data
                 tqdm.write(f"Skipping '{display_title}' (ID: {source_id}): Could not extract valid Trakt IDs from search result: {trakt_match}")
                 skipped_not_found += 1
        # Handle cases where Trakt search returned None
        elif media_format in ['music', 'unknown']: # Check if format was skipped intentionally
             skipped_unsupported_format += 1
        else: # Genuine "not found" on Trakt search
             skipped_not_found += 1


        # --- Batch Sending Logic (Inside Loop) ---
        # Send history batch if full
        if len(trakt_history_batch) >= BATCH_SIZE:
            tqdm.write(f"\nAdding HISTORY batch ({len(trakt_history_batch)} items)...")
            success, count_synced = add_to_trakt_history(trakt_history_batch, trakt_access_token)
            if success: total_history_synced += count_synced
            else: failed_history_batches += 1
            trakt_history_batch = [] # Clear batch
            time.sleep(API_CALL_DELAY) # Delay after Trakt API call

        # Send ratings batch if full
        if len(trakt_ratings_batch) >= BATCH_SIZE:
            tqdm.write(f"\nAdding RATINGS batch ({len(trakt_ratings_batch)} items)...")
            success, count_synced = add_to_trakt_ratings(trakt_ratings_batch, trakt_access_token)
            if success: total_ratings_synced += count_synced
            else: failed_ratings_batches += 1
            trakt_ratings_batch = [] # Clear batch
            time.sleep(API_CALL_DELAY) # Delay after Trakt API call

    # --- Send Final Batches (After Loop) ---
    if trakt_history_batch:
        tqdm.write(f"\nAdding final HISTORY batch ({len(trakt_history_batch)} items)...")
        success, count_synced = add_to_trakt_history(trakt_history_batch, trakt_access_token)
        if success: total_history_synced += count_synced
        else: failed_history_batches += 1
        # Delay if ratings batch follows
        if trakt_ratings_batch: time.sleep(API_CALL_DELAY)

    if trakt_ratings_batch:
        tqdm.write(f"\nAdding final RATINGS batch ({len(trakt_ratings_batch)} items)...")
        success, count_synced = add_to_trakt_ratings(trakt_ratings_batch, trakt_access_token)
        if success: total_ratings_synced += count_synced
        else: failed_ratings_batches += 1

    # --- Final Summary ---
    print(f"\n--- {DATA_SOURCE} to Trakt Migration Summary ---")
    print(f"Processed {len(completed_anime)} completed {DATA_SOURCE} anime entries.")
    print(f"Skipped {skipped_not_found} entries (not found on Trakt via title/year search).")
    print(f"Skipped {skipped_already_watched} entries (already in Trakt watched history).")
    print(f"Skipped {skipped_already_rated} entries (already rated on Trakt before this run).")
    print(f"Skipped {skipped_rated_this_run} ratings (item already rated earlier in this run).")
    print(f"Skipped {skipped_unsupported_format} entries (unsupported media format like 'music').")
    print(f"Skipped {skipped_missing_data} entries (missing essential source data like title/format).")
    print("-" * 25)
    print(f"History Sync: Prepared {history_prepared_count} new entries.")
    print(f"              Successfully synced approx {total_history_synced} history entries to Trakt.")
    if failed_history_batches > 0:
         print(f"!!! WARNING: {failed_history_batches} HISTORY batches failed or partially failed. Check logs above.")
    print("-" * 25)
    print(f"Ratings Sync: Prepared {ratings_prepared_count} new entries (score > 0, not rated before).")
    print(f"              Successfully synced approx {total_ratings_synced} rating entries to Trakt.")
    if failed_ratings_batches > 0:
         print(f"!!! WARNING: {failed_ratings_batches} RATINGS batches failed or partially failed. Check logs above.")
    print("-----------------------------")
    print("Migration complete.")

    # --- Attribution ---
    print_boxed_attribution()
