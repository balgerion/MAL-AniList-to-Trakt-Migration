# MAL/AniList to Trakt Sync Script

This script synchronizes your **completed** anime watch history and ratings from either MyAnimeList (MAL) or AniList to your Trakt.tv profile. It fetches your existing Trakt history and ratings to avoid adding duplicates.

**Source:** Originally created by Nikoloz Taturashvili solely for AniList, adapted for MAL public API access and enhanced.

## Features

*   Syncs **completed** anime history from MAL/AniList to Trakt.
*   Syncs anime **ratings** (scores > 0) from MAL/AniList to Trakt.
*   Supports **MyAnimeList (MAL)** *or* **AniList** as the data source.
*   Fetches existing Trakt history/ratings to prevent duplicates.
*   Uses user-friendly Trakt device authentication (no password needed).
*   Uses MAL's public API access via Client ID (no complex MAL user auth needed, but requires a public MAL list).
*   Uses AniList's public GraphQL API.
*   Sends data to Trakt in batches to respect API limits.
*   Provides a summary report upon completion.

## Prerequisites

1.  **Python 3.x:** Ensure you have Python 3 installed.
2.  **pip:** Python's package installer (usually included with Python).
3.  **Required Libraries:** `requests` and `tqdm`.
4.  **Accounts:**
    *   A Trakt.tv account.
    *   An account on either MyAnimeList *or* AniList.
5.  **Public Anime List (either source):** Your MAL/AniList Anime List **must** be set to 'Public' for the script to access it.

## Setup: API Keys & Credentials

You need to register applications on both Trakt and MAL (if using MAL) to get the necessary API credentials.

### 1. Trakt Application

*   Go to [Trakt API Applications](https://trakt.tv/oauth/applications/new).
*   Click "NEW APPLICATION".
*   **Name:** Choose a name (e.g., "MAL/AniList Sync Script").
*   **Redirect uri:** Enter exactly `urn:ietf:wg:oauth:2.0:oob`. This is required for the device authentication flow used by the script.
*   **Permissions:** Ensure `/sync` permissions are included (usually default). `/checkin` and `/scrobble` might be checked by default but are not strictly necessary for this script's *sync* functionality.
*   Leave "Javascript (cors) origin" blank.
*   Click "SAVE APP".
*   Note down the `Client ID` and `Client Secret`. You will need both.

### 2. MyAnimeList Application (Only if using MAL as source)

*   Go to [MAL API Create Client](https://myanimelist.net/apiconfig).
*   Log in to your MAL account if prompted.
*   Click "Create ID"
*   Fill out the form:
    *   **App Name:** Choose a name (e.g., "Trakt Sync Script").
    *   **App Type:** Select `Other`.
    *   **App Description:** For some reason this is required by MAL (e.g., "Script to sync history to Trakt").
    *   **Redirect URL:** **Required**, but not actively used by this script. Enter a placeholder like `http://localhost` or `http://localhost:8080/mal_callback`.
    *   **Homepage URL:** **Required**, but not actively used by this script. Enter a placeholder like `http://localhost`.
    *   **Commercial / Non-commercial:** Select `Non-commercial`.
    *   **Name / Company Name:** Add your name, nickname or any placeholder value, required by MAL.
    *   **Purpose of Use:** Any option is totally fine. if unsure go with "`Other`".
    *   **Location / etc.:** Optional.
    *   Agree to the terms and conditions.
    *   Click "Submit".
*   Your application will be created. Note down the `Client ID`. You **do not** need the Client Secret for this script.

## Configuration

1.  **Download the Script:** Save the Python script (e.g., `sync_to_trakt.py`).
2.  **Edit the Script:** Open the script file in a text editor.
3.  **Fill in Credentials:** Locate the `# --- Configuration ---` section near the top and replace the placeholder values:
    *   `TRAKT_CLIENT_ID`: Your Trakt application's Client ID.
    *   `TRAKT_CLIENT_SECRET`: Your Trakt application's Client Secret.
    *   `DATA_SOURCE`: Set this to either `"MAL"` or `"AniList"` depending on where your anime list is hosted.
    *   If `DATA_SOURCE = "MAL"`:
        *   `MAL_CLIENT_ID`: Your MAL application's Client ID.
        *   `MAL_USERNAME`: The specific MAL username whose list you want to sync (likely your own).
    *   If `DATA_SOURCE = "AniList"`:
        *   `ANILIST_USERNAME`: The specific AniList username whose list you want to sync.

## Installation & Usage

1.  **Open Terminal/Command Prompt:** Navigate to the directory where you saved the script file.
2.  **Install Dependencies:** Run the following command:
    ```bash
    pip install requests tqdm
    ```
3.  **Run the Script:** Execute the script using Python:
    ```bash
    python sync_to_trakt.py
    ```
    *(Replace `sync_to_trakt.py` with the actual filename if you saved it differently)*
4.  **Trakt Authentication (First Run or Expired Token):**
    *   The script will print a URL and a code.
    *   Go to the URL in your web browser.
    *   Log in to Trakt if necessary.
    *   Enter the code displayed in the terminal.
    *   Authorize the application.
    *   The script will automatically detect the authorization and continue.
5.  **Syncing Process:**
    *   The script will fetch your existing Trakt history and ratings.
    *   It will then fetch your anime list from the configured source (MAL or AniList).
    *   It will process your *completed* anime, search for matches on Trakt, check for duplicates, and prepare batches.
    *   Finally, it will send the new history and rating entries to Trakt.
    *   A summary will be displayed at the end.

## ⚠️ Important Warning: Review Your Trakt History!

This script relies on searching Trakt using the **Anime Title** and **Start Year** obtained from MAL/AniList. There is **no direct ID mapping** available through the public APIs used. While this works well for many entries, it can sometimes lead to **incorrect matches** on Trakt.

**Why Mismatches Happen:**

*   **Multiple Versions:** Trakt might have entries for TV series, OVAs, movies, specials, or remakes with very similar titles and sometimes overlapping years (e.g., "Attack on Titan", "Attack on Titan OVA", "Attack on Titan Season 2").
*   **Title Variations:** Minor differences in how titles are stored on MAL/AniList vs. Trakt can cause the search to pick the wrong entry.
*   **Ambiguity:** Some titles might simply be ambiguous, and Trakt's search might return a different but similarly named show/movie first, even with the year filter.

**Recommendation:**

After running the script, **it is highly recommended to manually review your recently added history and ratings on your Trakt.tv profile page.** Pay particular attention to:

*   Shows with multiple seasons, OVAs, or movies.
*   Remakes or reboots.
*   Anime with very generic or common titles.

If you find incorrect matches, you will need to manually remove them from your Trakt history/ratings. This script provides a good starting point for bulk syncing but cannot guarantee 100% accuracy due to the limitations of title/year-based searching between different platforms.

## How It Works (Briefly)

1.  **Authenticate with Trakt:** Gets an access token using device authentication.
2.  **Fetch Trakt Data:** Retrieves lists of already watched and rated show/movie Trakt IDs to avoid duplicates.
3.  **Fetch Source Data:**
    *   **MAL:** Uses the provided `MAL_USERNAME` and `MAL_CLIENT_ID` to fetch the public anime list via the MAL API v2.
    *   **AniList:** Uses the provided `ANILIST_USERNAME` to fetch the anime list via the AniList GraphQL API.
4.  **Filter:** Selects only entries marked as "completed".
5.  **Process Entries:** For each completed entry:
    *   Extracts title, year, format, score, and completion date.
    *   Searches Trakt using title and year.
    *   If a match is found on Trakt:
        *   Checks if the Trakt ID is already in the fetched watched/rated lists.
        *   If not watched, formats the completion date and adds it to the history batch.
        *   If not rated (and has a score > 0), converts the score, formats the date, and adds it to the ratings batch.
6.  **Sync to Trakt:** Sends the prepared history and ratings batches to the Trakt `/sync/history` and `/sync/ratings` endpoints.
7.  **Report:** Prints a summary of processed and skipped items.

## Limitations

*   **Matching Accuracy:** Relies entirely on Trakt's search results for Title/Year matching. Mismatches *will* occur (see Warning section).
*   **Completed Items Only:** Only syncs items marked as 'completed' on the source platform. 'Watching' or 'Plan to Watch' items are ignored.
*   **No Episode Progress:** Marks the entire show/movie as watched based on the completion date; does not sync individual episode watches.
*   **Public List:** Requires the source list to be public.
*   **Rate Limits:** Be mindful of API rate limits, especially MAL's (around 60 requests/minute). The script has built-in delays (`SOURCE_API_DELAY`, `API_CALL_DELAY`), but you might need to increase them if you encounter rate limit errors (HTTP 429).

## License

This script is released under the MIT License. See the LICENSE file for details
