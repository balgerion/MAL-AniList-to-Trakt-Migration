# AniList to Trakt Migration Script

![Python](https://img.shields.io/badge/Python-3.x-blue.svg)

This Python script helps you migrate your completed anime history and ratings from your AniList profile to your Trakt.tv account.

It fetches your completed anime list from AniList, searches for corresponding shows or movies on Trakt.tv, and then adds them to your Trakt watched history and ratings.

**Disclaimer:** Due to limitations in Trakt's public search API and differences in how platforms structure shows (especially seasons, OVAs, etc.), **automatic matching is not perfect**. Manual verification of your Trakt history after running the script is recommended.

## Features

*   **Fetches Completed Anime:** Retrieves your anime list entries marked as `COMPLETED` from AniList using their GraphQL API.
*   **Trakt Search:** Searches for matching shows or movies on Trakt.tv using **Title and Year** (as direct MAL ID lookup via URL is not supported by Trakt's public API).
*   **History Sync:** Adds found anime to your Trakt watched history, using the `completedAt` date from AniList.
*   **Rating Sync:** Adds ratings to Trakt (converting AniList's 0-100 score to Trakt's 1-10 scale), using the `completedAt` date as the `rated_at` timestamp.
*   **Idempotent Design:** Checks your existing Trakt history and ratings before adding new entries to avoid duplicates on subsequent runs.
*   **Handles Seasons (Rating):** Attempts to rate a specific Trakt show/movie ID only *once* per script run, typically using the rating from the first encountered AniList entry (e.g., Season 1) that maps to that Trakt ID.
*   **Trakt Authentication:** Uses Trakt's Device Authentication flow for easy and secure login without needing to handle callbacks. Tokens are stored locally for reuse.
*   **Batch Processing:** Sends data to Trakt in batches for API efficiency.
*   **Progress Indication:** Uses `tqdm` to display a progress bar during processing.
*   **Filters:** Ignores manga entries and focuses only on `ANIME` type from AniList.

## Prerequisites

*   **Python 3:** Ensure you have Python 3 (preferably 3.7+) installed. ([Download Python](https://www.python.org/downloads/))
*   **pip:** Python's package installer, usually included with Python 3.
*   **AniList Account:** Your AniList profile (specifically your list activity) should ideally be set to **Public** for the script to access it via the public API. You can change this in your AniList settings under Settings -> Account -> Privacy.
*   **Trakt.tv Account:** You need an account on Trakt.tv.

## Setup Instructions

**1. Get the Script:**

   Clone this repository or download the `anilist_to_trakt.py` script file.

   ```bash
   git clone https://github.com/tnicko1/anilist-to-trakt-migration.git
   cd anilist-to-trakt-migration
   ```

**2. Install Dependencies:**

   Open your terminal or command prompt, navigate to the script's directory, and install the required Python libraries:

   ```bash
   pip install requests tqdm
   ```
   or
   ```bash
   pip install -r requirements.txt
   ```

   *   `requests`: For making HTTP requests to the AniList and Trakt APIs.
   *   `tqdm`: For displaying a progress bar.

**3. Get Trakt API Credentials:**

   You need to register an application on Trakt.tv to get API keys.

   *   Go to [https://trakt.tv/oauth/applications/new](https://trakt.tv/oauth/applications/new).
   *   Fill in the form:
        *   **Name:** Choose any name (e.g., `AniList Sync Script`).
        *   **Description:** Optional.
        *   **Redirect uri:** `urn:ietf:wg:oauth:2.0:oob` **(This exact value is crucial for device authentication!)**
        *   **Permissions:** Make sure `/checkin` and `/scrobble` is checked.
   *   Click "SAVE APP".
   *   You will now see your **Client ID** and **Client Secret**. **Copy these down securely.**

**4. Configure the Script:**

   *   Open the `anilist_to_trakt.py` file in a text editor.
   *   Find the following lines near the top under the `--- Configuration ---` section:

     ```python
     # Paste your Trakt API credentials here
     TRAKT_CLIENT_ID = "YOUR_TRAKT_CLIENT_ID"
     TRAKT_CLIENT_SECRET = "YOUR_TRAKT_CLIENT_SECRET"
     ANILIST_USERNAME = "YOUR_ANILIST_USERNAME" # Replace with your AniList username
     ```

   *   Replace the placeholder values:
        *   `"YOUR_TRAKT_CLIENT_ID"` with your actual Trakt **Client ID**.
        *   `"YOUR_TRAKT_CLIENT_SECRET"` with your actual Trakt **Client Secret**.
        *   `"YOUR_ANILIST_USERNAME"` with your exact **AniList username** (case-sensitive).

   *   Save the file.

## How to Run

1.  Open your terminal or command prompt.
2.  Navigate to the directory where you saved `anilist_to_trakt.py`.
3.  Run the script using Python 3:

    ```bash
    python anilist_to_trakt.py
    ```

4.  **First Run - Trakt Authentication:**
    *   The script will print instructions similar to this:
        ```
        --- Trakt Authentication Required ---
        1. Go to: https://trakt.tv/activate
        2. Enter code: XXXXXXXX (Expires in 600s)
        3. Authorize the application on Trakt.tv.
        -------------------------------------
        ```
    *   Open the provided URL (`https://trakt.tv/activate`) in your web browser.
    *   Log in to your Trakt.tv account if prompted.
    *   Enter the 8-character code displayed in your terminal.
    *   Click "Continue" and then "Yes" to authorize the application.
    *   The script in your terminal will detect the authorization and continue automatically.
    *   A `trakt_tokens.json` file will be created in the same directory to store your authentication tokens securely.

5.  **Subsequent Runs:** The script will automatically load the tokens from `trakt_tokens.json`. If the tokens expire (after ~3 months), it will attempt to refresh them or prompt you to re-authenticate via the device flow.

6.  **Execution:** The script will then:
    *   Fetch your existing watched history and ratings from Trakt (to avoid duplicates).
    *   Fetch your completed anime list from AniList.
    *   Process each AniList entry:
        *   Search for it on Trakt using Title and Year.
        *   Check if it's already watched/rated on Trakt or rated during this run.
        *   Prepare batches of new history/rating entries.
    *   Send batches to the Trakt API.
    *   Display progress using `tqdm`.
    *   Print warnings for items it cannot find or potential API issues.
    *   Print a final summary of actions taken.

## Configuration Options

The following constants near the top of the script can be adjusted, but it's generally recommended to leave them at their defaults unless you encounter specific issues:

*   `BATCH_SIZE`: Number of items to send to Trakt in a single API request (Default: 50).
*   `API_CALL_DELAY`: Delay (in seconds) between consecutive calls to the Trakt API to help avoid rate limits (Default: 1.5).

## Important Notes & Limitations

*   **Accuracy Limitations & Manual Verification:**
    *   The biggest limitation is matching AniList entries to Trakt entries. Since Trakt's public API **does not support searching directly by MAL ID via URL**, this script relies on **searching by Title and Year**.
    *   This method is **prone to inaccuracies**, especially for:
        *   Anime with very similar titles.
        *   OVAs, ONAs, Specials, or Movies that might be structured differently on Trakt (e.g., listed under a parent show's "Specials" vs. being a separate entry).
        *   Sequels/Seasons: AniList often lists seasons separately (e.g., "Show Name Season 2"), while Trakt usually groups them under one show entry.
    *   **Example Mismatch:** The script might incorrectly match "Link Click Season 2" (from AniList) to an unrelated show called "Click Boys" on Trakt if the title search yields that as the first result.
    *   **RECOMMENDATION:** After running the script, **please manually review your Trakt.tv watched history and ratings**, especially for series with multiple seasons, OVAs, or potentially ambiguous titles. You may need to manually correct some entries on the Trakt website.
*   **Rating Behavior:** Trakt applies ratings to the entire show/movie entity. When processing multiple AniList entries that map to the *same* Trakt show (like seasons), this script will typically only attempt to rate the Trakt show **once per run**, using the score from the *first* AniList entry it encounters for that show (usually Season 1).
*   **Scope:** This script focuses only on migrating `COMPLETED` anime history and ratings. It does not handle 'Watching' status, watchlist synchronization, or detailed progress tracking.
*   **Idempotency:** The script tries hard to avoid adding duplicate history or ratings if they already exist on Trakt *before* the script runs. Running it multiple times should be generally safe, but it **will not fix incorrect matches** made during a previous run.
*   **API Limits:** While the script includes delays, very large libraries or running it excessively might still encounter Trakt API rate limits. The script includes basic retry logic for rate limit errors (HTTP 429).
*   **Error Handling:** Basic error handling for network issues and API errors is included, but complex or persistent issues might cause the script to fail. Check the terminal output for warnings or errors.

## License

This project is licensed under the MIT License - see the LICENSE file for details
