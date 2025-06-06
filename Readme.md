
# SearXNG Query Generator v4

`generate_queries_v4.py` automates query generation and data collection from a [SearXNG](https://docs.searxng.org/) instance. Starting with a seed query, it expands searches using modifier terms and saves results to CSV.

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
1. Place `generate_queries_v4.py` in your working directory
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
| `SEARXNG_URL`               | `http://localhost:8080/search` | **Required** SearXNG endpoint |
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
python generate_queries_v4.py
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


