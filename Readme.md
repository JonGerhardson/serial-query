
# SearXNG scraper

`serial_query.py` automates query generation and data collection from a [SearXNG](https://docs.searxng.org/) instance. Starting with a seed query, it expands searches using modifier terms and saves results to CSV.

Example logs with max items set to six for the sake of brevity. 
```
 python serial-query.py
Successfully loaded 49 modifier terms from /poath/to/serial-query/modifiers.csv
--- Query Generation Utility (v4 - Pause/Resume, Progressive Save, Auto-Retry) ---
Enter initial seed query: Best ice cream parlor

--- Processing query 1/50: "Best ice cream parlor" ---

Fetching up to 6 new items, across max 100 pages for query: "Best ice cream parlor" (starting page 1)
🔍 Searching SearXNG (page 1) for: "Best ice cream parlor"
Saved 38 new items from page 1 for "Best ice cream parlor". Total for this query: 38.
Collected 38 new items, reaching target of 6 for "Best ice cream parlor".
Finished fetching for "Best ice cream parlor". Total new items added to CSV for this query: 38.

--- Processing query 2/50: "Best ice cream parlor California" ---

Fetching up to 6 new items, across max 100 pages for query: "Best ice cream parlor California" (starting page 1)

```


## Intended for self-hosted SearxNG instances
This should in theory work with public instances that do not require an API key, but it is reccomended to host it yourself from [https://github.com/searxng/searxng
](https://github.com/searxng/searxng)

## Takes a while to run
Bot avoidance in this script is unsophisticated. It just sets a really long delay between requests. Expect a long run to take a day or more. You can adjust the delay between requests in the script. Default is minimum 90 seconds maximum 300 seconds. It saves state to a json file so you can stop and restart where you left off if needed. 

## Key Features

- **Query Expansion**: Combines base queries with terms from `modifiers.csv`
- **Progressive Saving**: Appends results incrementally to prevent data loss
- **Pause & Resume**: Save state with `Ctrl+C` and resume later
- **Automatic Retry**: Retries failed requests with delay
- **Rate-Limit Handling**: Detects empty results and pauses
- **Deduplication**: Prevents duplicate URL entries
- **Configurable**: Environment variable configuration
- **Logging**: Detailed console output

## Installation

### Prerequisites
- Python 3.x
- Access to SearXNG instance
- Required libraries:
  ```bash
  pip install requests pandas tenacity
  ```

### Setup
1. Place `serial_query.py` in your working directory
2. Create `modifiers.csv` with one term per line:
   ```plaintext
   review
   vs
   alternative
   reddit
   2024
   ```

## Configuration
Set these environment variables before execution:

| Variable                    | Default Value               | Description |
|-----------------------------|-----------------------------|-------------|
| `SEARXNG_URL`               | `https://example.gov.biz/search` | **Required** SearXNG endpoint set to the instance you're using|
| `OUTPUT_CSV_FILENAME`       | `queries_with_urls.csv`     | Output filename |
| `TOP_N_RESULTS_PER_QUERY`   | `2666`                      | Max unique results per query |
| `MAX_PAGES_TO_FETCH_PER_QUERY` | `100`                    | Max pages per query |
| `MIN_DELAY_SECONDS`         | `94.20`                     | Min request delay (seconds) |
| `MAX_DELAY_SECONDS`         | `300.0`                     | Max request delay (seconds) |
| `REQUEST_TIMEOUT`           | `30`                        | Request timeout (seconds) |
| `RETRY_ATTEMPTS`            | `3`                         | Network retry attempts |

**Example Configuration:**
```bash
# Linux/macOS
export SEARXNG_URL="https://searx.example.com/search"

# Windows
set SEARXNG_URL="https://searx.example.com/search"
```

## Usage

### Starting New Session
```bash
python serial_query.py
> Enter initial seed query: [Your Search Term Here]
```

### Pausing and Resuming
1. Pause with `Ctrl+C`:
   ```plaintext
   🚫 Ctrl+C detected. Saving state...
   🔄 Script state saved to searxng_scraper_state.json
   ```
2. Resume by re-running script:
   ```plaintext
   📄 Found saved state. Resume previous session? (y/n): y
   ```

### Handling Empty Results
When no results appear:
```plaintext
INFO: No results on page 5 for query "Example Query" 
INFO: Pausing for 600 seconds...
ACTION: Press 'r' + Enter to retry immediately
```

## Output Files
| Filename                      | Description |
|-------------------------------|-------------|
| `queries_with_urls.csv`       | Main results (Query Title + URL) |
| `searxng_scraper_state.json`  | Auto-saved state (deleted on completion) |
```

Key formatting elements used:
- Code blocks with syntax highlighting (bash, plaintext)
- Tables with clear column alignment
- Bold text for emphasis
- Emojis for visual cues
- Proper escaping of special characters
- Organized section separation
- Clear command examples with prompts
- Required vs optional configuration indicators
- Consistent indentation and spacing


