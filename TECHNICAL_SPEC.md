# AI News Aggregator - Technical Specification

## Executive Summary

The AI News Aggregator is a Python-based news curation system that automatically fetches, scores, groups, and displays AI-related news from multiple sources. It uses Claude AI (Anthropic API) for intelligent scoring and learning objective generation, with a Streamlit-based dashboard for viewing and managing content.

**Key Features:**
- Two-tier source system: "trusted" (official vendor feeds, every 15 min) and "open" (general news/search, daily digest)
- Multi-source news aggregation (RSS, HTML scraping, web search, email newsletters)
- Newsletter ingestion via IMAP with Claude-powered story extraction
- AI-powered relevance scoring and categorization using Claude Sonnet
- Intelligent deduplication (fuzzy + semantic via Claude) and grouping of related articles
- Three RSS feeds: combined (8+), trusted (all scores), digest (7+)
- Learning objective generation using Claude Opus with web research
- Dark-themed dashboard with minimalist Linear/Notion aesthetic
- Daily Digest page with stories grouped by day and sorted by score
- Interactive filtering, sorting, and acknowledgment system

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interface Layer                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Streamlit Dashboard (dashboard.py)                    │ │
│  │  - News viewing with filters                           │ │
│  │  - Settings management                                 │ │
│  │  - Pipeline execution                                  │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                    Processing Pipeline                       │
│  ┌────────────┬────────────┬────────────┬────────────────┐ │
│  │  Fetchers  │  Deduper   │  Scorer    │    Grouper     │ │
│  │  (RSS/Web) │  (Fuzzy)   │  (Claude)  │  (Clustering)  │ │
│  └────────────┴────────────┴────────────┴────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  SQLite Database (ainews.db)                           │ │
│  │  - News items with scores                              │ │
│  │  - Source tracking                                     │ │
│  │  - User acknowledgments                                │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                   External Services                          │
│  ┌──────────────┬──────────────┬──────────────┬──────────┐  │
│  │  Claude API  │  RSS Feeds   │  DuckDuckGo  │  IMAP    │  │
│  │  (Anthropic) │  (Multiple)  │  (Search)    │  (Email) │  │
│  └──────────────┴──────────────┴──────────────┴──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Language** | Python | 3.10+ | Core application |
| **UI Framework** | Streamlit | Latest | Interactive dashboard |
| **Database** | SQLite | 3.x | Local data storage |
| **AI/ML** | Anthropic Claude API | 4.5/4.6 | Scoring and LO generation |
| **HTTP Client** | httpx | 0.28.0+ | Web requests |
| **RSS Parser** | feedparser | 6.0.0+ | RSS feed parsing |
| **Browser Automation** | Playwright | 1.50.0+ | JavaScript-rendered pages |
| **Search** | duckduckgo_search | 9.0.0+ | Web search |
| **Fuzzy Matching** | thefuzz | 0.22.0+ | Deduplication and grouping |
| **Date Parsing** | python-dateutil | 2.9.0+ | Date handling |
| **HTML Parsing** | lxml + cssselect | 5.0.0+ | Web scraping |
| **Config** | PyYAML | 6.0+ | Configuration management |

---

## Data Flow

### Pipeline Execution Flow

```
1. FETCH PHASE
   ├── RSS Fetcher → Parse RSS/Atom feeds (trusted + open)
   ├── HTML Scraper → Auto-detect RSS or scrape HTML
   ├── Browser Scraper → Render JS pages with Playwright
   ├── Search Fetcher → Query DuckDuckGo for keywords (open only)
   └── Email Fetcher → IMAP newsletters + Claude extraction (open only)
                ↓
2. DEDUPLICATE PHASE
   ├── Normalize URLs (lowercase domain, strip tracking params)
   ├── Hash normalized URLs
   ├── Fuzzy-match titles (Levenshtein ratio)
   ├── Semantic dedup via Claude for borderline pairs
   └── Mark duplicates for removal
                ↓
3. CONTENT FETCH PHASE
   └── Fetch full article text via httpx + trafilatura
                ↓
4. SCORE PHASE
   ├── Batch items (default: 20 per batch)
   ├── Send to Claude Sonnet API with scoring prompt
   ├── Parse JSON response (score, category, summary, reasoning, LOs)
   └── Categories: New Releases, Research, Business, Developer Tools
                ↓
5. GROUP PHASE
   ├── Extract significant words from titles
   ├── Calculate fuzzy token-sort ratios
   ├── Semantic grouping via Claude for near-misses
   ├── Cluster items covering same story
   └── Prefer vendor sources as primary (OpenAI, Anthropic, etc.)
                ↓
6. STORE + RSS PHASE
   ├── Write to SQLite with automatic schema migrations
   └── Generate 3 RSS feeds (combined 8+, trusted all, digest 7+)
```

---

## Database Schema

### Tables

#### `news_items`
Primary storage for all news articles.

```sql
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    url_hash TEXT,  -- MD5 hash of normalized URL
    source TEXT,    -- Source name (e.g., "OpenAI News")
    published DATETIME,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    fetched_via TEXT,  -- 'rss', 'html', 'web', 'search'

    -- Scoring results from Claude
    score INTEGER,  -- 1-10 relevance score
    category TEXT,  -- 'New Releases' or 'Industry'
    summary TEXT,
    score_reasoning TEXT,
    learning_objectives TEXT,
    lo_generated_with_opus BOOLEAN DEFAULT 0,

    -- Grouping
    group_id INTEGER,  -- Links related articles
    is_primary BOOLEAN DEFAULT 0,  -- Primary article in group

    -- User interaction
    acknowledged BOOLEAN DEFAULT 0,
    acknowledged_at DATETIME
);

CREATE INDEX idx_url_hash ON news_items(url_hash);
CREATE INDEX idx_category ON news_items(category);
CREATE INDEX idx_score ON news_items(score);
CREATE INDEX idx_group_id ON news_items(group_id);
CREATE INDEX idx_published ON news_items(published);
```

#### `feed_scans`
Tracks when each feed was last scanned (used by `--category` scheduling).

```sql
CREATE TABLE feed_scans (
    feed_name TEXT PRIMARY KEY,
    last_scanned DATETIME
);
```

#### `processed_emails`
Tracks processed newsletter emails for idempotency.

```sql
CREATE TABLE processed_emails (
    message_id TEXT PRIMARY KEY,
    sender TEXT,
    subject TEXT,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    stories_extracted INTEGER DEFAULT 0
);
```

---

## Configuration

### config.yaml Structure

```yaml
# Database
db_path: "data/ainews.db"

# Anthropic API
anthropic_api_key: "sk-ant-..."  # Required for scoring and LO generation
model: claude-sonnet-4-5-20250929
lo_model: claude-opus-4-6

# Scoring configuration
scoring_batch_size: 20  # Items per Claude API request
semantic_dedup: true     # Use Claude for borderline dedup cases

# Source scheduling
trusted_interval: 15    # Minutes between trusted source scans
open_interval: 1440     # Minutes between open source scans (24h)

# News sources (category: trusted or open)
feeds:
  - name: "OpenAI News"
    url: "https://openai.com/news/"
    type: "web"
    enabled: true
    category: trusted    # Scanned every 15 min

  - name: "Anthropic News"
    url: "https://www.anthropic.com/news"
    type: "web"
    enabled: true
    category: trusted

  - name: "TechCrunch AI"
    url: "https://techcrunch.com/category/artificial-intelligence/feed/"
    type: "rss"
    enabled: true
    category: open       # Included in daily digest

# Search queries (run on open/daily schedule)
search_queries:
  - query: "openai news"
    category: open
  - query: "anthropic news"
    category: open

# Newsletter email ingestion (runs on open/daily schedule)
newsletters:
  enabled: false
  imap_host: imap.gmail.com
  imap_port: 993
  email: your-newsletters@gmail.com
  # Password via env var: AINEWS_EMAIL_PASSWORD
  max_emails_per_run: 50
  senders:
    - name: "TLDR AI"
      address: "dan@tldrnewsletter.com"
    - name: "Import AI"
      address: "jack@jack-clark.net"
```

---

## File Structure

```
AINews/
├── dashboard.py                    # Main Streamlit app
├── dashboard_components.py         # UI rendering components
├── fetch_news.py                   # Pipeline execution script (--category trusted|open)
├── generate_rss_feed.py            # Standalone RSS generator
├── config.yaml                     # User configuration (gitignored)
├── config.example.yaml             # Example configuration template
├── requirements.txt                # Python dependencies
│
├── assets/
│   └── style.css                   # Custom dark theme CSS
│
├── ainews/                         # Core backend package
│   ├── __init__.py
│   ├── models.py                   # Data models (RawNewsItem, ProcessedNewsItem)
│   ├── config.py                   # Configuration loading/saving
│   ├── rss_generator.py            # RSS feed generator (combined, trusted, digest)
│   │
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── rss_fetcher.py         # RSS/Atom feed parser
│   │   ├── html_scraper.py        # HTML scraping with auto-RSS detection
│   │   ├── web_searcher.py        # DuckDuckGo search integration
│   │   ├── content_fetcher.py     # Full article content via trafilatura
│   │   └── email_fetcher.py       # IMAP newsletter ingestion + Claude extraction
│   │
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── deduplicator.py        # URL normalization + fuzzy + semantic dedup
│   │   ├── scorer.py              # Claude API scoring (Sonnet)
│   │   └── grouper.py             # Fuzzy + semantic article clustering
│   │
│   └── storage/
│       ├── __init__.py
│       └── database.py            # SQLite operations + migrations
│
├── data/                           # Created at runtime (gitignored)
│   ├── ainews.db                  # SQLite database
│   ├── pipeline.log               # Pipeline run log (rotated daily)
│   ├── high_priority.xml          # Combined RSS feed (score 8+)
│   ├── high_priority_trusted.xml  # Trusted sources RSS feed (all scores)
│   └── high_priority_digest.xml   # Daily digest RSS feed (score 7+)
│
├── deployment/                     # AWS deployment scripts and docs
│   ├── aws-ec2-setup.sh
│   ├── QUICKSTART.md
│   ├── README-AWS.md
│   └── SECURITY.md
│
└── TECHNICAL_SPEC.md              # This document
```

---

## Component Details

### 1. Fetchers (`ainews/fetchers/`)

#### RSS Fetcher (`rss_fetcher.py`)
**Purpose:** Parse RSS and Atom feeds using feedparser.

**Key Functions:**
```python
def fetch_rss(url: str, source_name: str) -> list[RawNewsItem]:
    """
    Fetch and parse RSS/Atom feed.

    Args:
        url: Feed URL
        source_name: Display name for source

    Returns:
        List of RawNewsItem objects

    Implementation:
        1. Fetch feed with httpx
        2. Parse with feedparser
        3. Extract title, link, published date, description
        4. Create RawNewsItem for each entry
    """
```

**Date Parsing:** Uses python-dateutil to parse various date formats.

#### HTML Scraper (`html_scraper.py`)
**Purpose:** Auto-detect RSS feeds or scrape HTML directly.

**Key Functions:**
```python
def fetch_html_or_rss(url: str, source_name: str) -> list[RawNewsItem]:
    """
    Auto-detect RSS feed link or scrape HTML.

    Args:
        url: Page URL
        source_name: Display name

    Returns:
        List of RawNewsItem objects

    Implementation:
        1. Fetch HTML page with httpx
        2. Look for <link type="application/rss+xml"> in <head>
        3. If found, fetch and parse RSS
        4. If not found, scrape HTML for article links
        5. Use lxml + cssselect to find <article>, <h2>, <time> elements
        6. Extract titles, links, dates from HTML structure
    """
```

**Heuristics for HTML Scraping:**
- Look for `<article>`, `<div class="post">`, `<div class="news-item">`
- Find headlines in `<h1>`, `<h2>`, `<h3>` with `<a>` tags
- Find dates in `<time>`, `<span class="date">`, `<meta property="article:published_time">`
- Extract descriptions from `<p>` near headlines or `<meta name="description">`

#### Browser Scraper (`browser_scraper.py`)
**Purpose:** Render JavaScript-heavy pages with headless browser.

**Key Functions:**
```python
def fetch_with_browser(url: str, source_name: str) -> list[RawNewsItem]:
    """
    Scrape page using Playwright headless browser.

    Args:
        url: Page URL
        source_name: Display name

    Returns:
        List of RawNewsItem objects

    Implementation:
        1. Launch Chromium browser (headless)
        2. Navigate to URL
        3. Wait for network idle (page fully loaded)
        4. Extract rendered HTML
        5. Parse with lxml/cssselect (same as HTML scraper)
        6. Close browser
    """
```

**Use Cases:** Sites that block simple HTTP requests or require JavaScript to render content (e.g., React/Vue SPAs).

#### Email Fetcher (`email_fetcher.py`)
**Purpose:** Fetch stories from email newsletters via IMAP and extract them using Claude.

**Key Functions:**
```python
def fetch_all_newsletters(cfg: dict, db: Database) -> list[RawNewsItem]:
    """
    Connect to IMAP inbox, fetch unread emails from known senders,
    extract stories using Claude, and return as RawNewsItem objects.

    Flow:
        1. Connect to IMAP server (Gmail via app password)
        2. Fetch unread emails (up to max_emails_per_run)
        3. Match sender against configured newsletter list
        4. Convert HTML to text via trafilatura
        5. Send text to Claude for structured story extraction
        6. Parse JSON response (with repair for truncated responses)
        7. Convert stories to RawNewsItem objects
        8. Mark email as processed in DB and as read in IMAP

    Newsletter senders are configured in config.yaml under newsletters.senders.
    Password is stored in AINEWS_EMAIL_PASSWORD environment variable.
    """
```

**Claude Extraction:** Each newsletter email is sent to Claude with a prompt that extracts individual stories as a JSON array with title, url, description, and content fields. Stories without URLs get synthetic `newsletter://` URIs.

**Idempotency:** The `processed_emails` table tracks message IDs to prevent re-processing.

#### Search Fetcher (`search_fetcher.py`)
**Purpose:** Query DuckDuckGo for keywords.

**Key Functions:**
```python
def fetch_from_search(query: str) -> list[RawNewsItem]:
    """
    Search DuckDuckGo and return results.

    Args:
        query: Search query string

    Returns:
        List of RawNewsItem objects

    Implementation:
        1. Query DuckDuckGo using ddgs library
        2. Limit to recent results (last 7 days)
        3. Extract title, link, snippet, date from results
        4. Create RawNewsItem for each result
        5. Mark as fetched_via='search'
    """
```

---

### 2. Processing Pipeline

#### Deduplicator (`processing/deduplicator.py`)
**Purpose:** Remove duplicate articles using URL normalization and fuzzy title matching.

**Algorithm:**
```python
def deduplicate(items: list[RawNewsItem]) -> list[RawNewsItem]:
    """
    Remove duplicates based on URLs and titles.

    Steps:
        1. Normalize URLs:
           - Lowercase domain
           - Remove tracking params (utm_*, fbclid, etc.)
           - Remove www. prefix
           - Sort query parameters

        2. Hash normalized URLs:
           - MD5 hash for fast comparison
           - Group items with same hash

        3. Fuzzy match titles:
           - For items with different URLs
           - Calculate Levenshtein ratio (thefuzz library)
           - Threshold: 0.85 similarity = duplicate
           - Keep item with higher-quality source or earlier date

        4. Return deduplicated list
    """
```

**URL Normalization Example:**
```
Original: https://www.example.com/article?utm_source=twitter&fbclid=123&id=456
Normalized: https://example.com/article?id=456
```

#### Scorer (`processing/scorer.py`)
**Purpose:** Score articles using Claude Sonnet API.

**Scoring Prompt Structure:**
```
You are an AI news curator. Score these news items for relevance to AI practitioners.

For each item, return JSON with:
- score: 1-10 (10 = groundbreaking, 1 = irrelevant)
- category: "New Releases" (products/features) or "Industry" (news/analysis)
- summary: 2-3 sentence summary
- score_reasoning: Why this score?
- learning_objectives: 3-5 bullet points

Items to score:
{items_text}

Return ONLY valid JSON array, no preamble.
```

**Implementation:**
```python
def score_items(
    client: anthropic.Anthropic,
    model: str,
    items: list[RawNewsItem],
    batch_size: int = 10,
    scoring_prompt: Optional[str] = None,
) -> list[ProcessedNewsItem]:
    """
    Score items in batches using Claude API.

    Args:
        client: Anthropic API client
        model: Model to use (claude-sonnet-4-5-20250929)
        items: Items to score
        batch_size: Items per API call
        scoring_prompt: Custom prompt (optional)

    Returns:
        List of ProcessedNewsItem with scores

    Implementation:
        1. Batch items (default 10 per batch)
        2. Format items as JSON for prompt
        3. Call Claude API with scoring prompt
        4. Parse JSON response
        5. Create ProcessedNewsItem objects
        6. Handle API errors (retry with exponential backoff)
    """
```

**API Call Example:**
```python
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}]
)
```

#### Grouper (`processing/grouper.py`)
**Purpose:** Cluster related articles covering the same story.

**Algorithm:**
```python
def run_grouper(db: Database) -> int:
    """
    Group related news items.

    Algorithm:
        1. Get all ungrouped items from last 30 days

        2. Extract significant words from titles:
           - Remove stop words (a, the, is, etc.)
           - Keep capitalized words (likely names)
           - Keep numbers

        3. For each item pair:
           - Calculate token-sort ratio (thefuzz)
           - If ratio > 0.75, consider related

        4. Create clusters:
           - Use union-find algorithm
           - Merge items with high similarity

        5. Select primary article per cluster:
           - Prefer vendor sources (OpenAI, Anthropic, Google, etc.)
           - Otherwise, prefer higher score
           - Otherwise, prefer earlier publication date

        6. Assign group_id and is_primary flag

    Returns:
        Number of groups created
    """
```

**Vendor Priority List:**
```python
VENDOR_SOURCES = [
    "OpenAI News",
    "Anthropic News",
    "Google AI Blog",
    "Microsoft AI",
    "Meta AI",
    # ... etc
]
```

---

### 3. Storage Layer

#### Database (`storage/database.py`)
**Purpose:** SQLite operations with automatic schema migrations.

**Key Methods:**
```python
class Database:
    def __init__(self, db_path: str):
        """Initialize database connection and run migrations."""

    def add_item(self, item: ProcessedNewsItem) -> int:
        """Insert or update news item. Returns item ID."""

    def query_grouped(
        self,
        category: str,
        min_score: int,
        max_score: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        show_acknowledged: bool,
        sort_by: str,
        sort_dir: str
    ) -> list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]:
        """
        Query items with filtering and grouping.

        Returns:
            List of (primary_item, related_items) tuples
        """

    def acknowledge(self, item_id: int):
        """Mark item as acknowledged."""

    def update_learning_objectives(
        self,
        item_id: int,
        objectives: str,
        generated_with_opus: bool
    ):
        """Update learning objectives for an item."""

    def get_source_status(self) -> list[dict]:
        """Get scan history for all sources."""

    def get_last_run_stats(self) -> Optional[dict]:
        """Get stats from most recent pipeline run."""
```

**Schema Migrations:**
```python
MIGRATIONS = [
    # Version 1: Initial schema
    """
    CREATE TABLE news_items (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT UNIQUE,
        -- ... all columns
    );
    """,

    # Version 2: Add learning objectives
    """
    ALTER TABLE news_items
    ADD COLUMN learning_objectives TEXT;

    ALTER TABLE news_items
    ADD COLUMN lo_generated_with_opus BOOLEAN DEFAULT 0;
    """,

    # Version 3: Add grouping support
    """
    ALTER TABLE news_items ADD COLUMN group_id INTEGER;
    ALTER TABLE news_items ADD COLUMN is_primary BOOLEAN DEFAULT 0;
    CREATE INDEX idx_group_id ON news_items(group_id);
    """
]

def run_migrations(conn: sqlite3.Connection):
    """Apply unapplied migrations in order."""
```

---

### 4. User Interface

#### Dashboard (`dashboard.py`)
**Purpose:** Main Streamlit application.

**Structure:**
```python
def main():
    """
    Main dashboard function.

    Layout:
        1. Page config (title, icon, wide layout)
        2. Load custom CSS from assets/style.css
        3. Display title and last run stats
        4. Sidebar filters:
           - Score range slider (1-10)
           - Date range picker
           - Show acknowledged checkbox
           - Sort by dropdown
           - Sort direction radio
        5. Main tabs:
           - New Releases: category='New Releases'
           - Industry: category='Industry'
           - Settings: pipeline controls, prompts, sources
           - About: documentation
        6. For each tab:
           - Query database with filters
           - Render news list using components
    """
```

#### Dashboard Components (`dashboard_components.py`)
**Purpose:** Reusable rendering functions.

**Key Components:**
```python
def _render_news_list(grouped_items, db, cfg):
    """Render all news items as expandable cards."""

def _render_news_item(primary, related, db, cfg):
    """
    Render single news item.

    Layout:
        - st.expander with title as label
        - Score icon (🔴/🟠/⚪) + score + title + related count
        - Inside expander:
          - Link, source, date, acknowledge button
          - Summary, score reasoning, learning objectives
          - Metadata (category, fetched_via, published date)
          - Related sources (if grouped)
    """

def _render_item_details(primary, related, db, cfg):
    """Render detailed content inside expander."""

def _render_learning_objectives(primary, cfg, db):
    """
    Render LO section with generate button.

    Features:
        - Show badge if generated with Opus
        - Generate button (calls Claude Opus API)
        - Loading spinner during generation
        - Display generated objectives as markdown
        - Error handling
    """

def _render_settings_tab(cfg, db, project_root):
    """
    Render settings tab.

    Sections:
        1. Pipeline runner with live log
        2. Scoring batch size setting
        3. Scoring prompt editor (with save/reset)
        4. LO prompt editor (with save/reset)
        5. Smart grouper button
        6. RSS/Auto feed management
        7. Website feed management
        8. Search query management
        9. Source scan history table
    """
```

#### Styling (`assets/style.css`)
**Purpose:** Custom CSS for Pluralsight dark theme.

**Key Styles:**
```css
/* Color palette */
:root {
    --score-high: #d32f2f;      /* Red for score ≥8 */
    --score-mid: #f39c12;       /* Orange for score ≥5 */
    --score-low: #a5aacf;       /* Muted for score <5 */
    --bg-dark: #130f25;         /* Dark purple background */
    --bg-panel: #1e1a36;        /* Panel background */
    --accent-pink: #e7005e;     /* Pluralsight pink */
    --text-primary: #ffffff;
    --text-secondary: #a5aacf;
    --border-color: #383461;
}

/* Global */
.stApp {
    background-color: var(--bg-dark);
    color: var(--text-primary);
    font-family: 'Inter', sans-serif;
}

/* Expanders */
[data-testid="stExpander"] {
    border-left: 3px solid var(--accent-pink);
    background-color: var(--bg-panel);
    border-radius: 0 8px 8px 0;
}

/* Primary buttons */
.stButton > button[kind="primary"] {
    background-color: var(--accent-pink) !important;
    color: white !important;
    border-radius: 6px;
}

.stButton > button[kind="primary"]:hover {
    background-color: #ff1675 !important;
    transform: translateY(-1px);
}
```

---

## Pipeline Execution

### Pipeline Script (`fetch_news.py`)
**Purpose:** Command-line tool to run the full pipeline.

```python
def main():
    """
    Execute the news aggregation pipeline.

    Steps:
        1. Load configuration from config.yaml
        2. Initialize database
        3. FETCH:
           - For each enabled feed:
             - If type='rss': use RSS fetcher
             - If type='auto': use HTML scraper (auto-detect)
             - If type='web': use browser scraper
           - For each search query:
             - Use search fetcher
        4. DEDUPLICATE:
           - Normalize URLs
           - Fuzzy-match titles
           - Keep unique items
        5. SCORE:
           - Batch items (default 10)
           - Call Claude Sonnet API
           - Parse scores, categories, summaries
        6. STORE:
           - Insert new items into database
           - Update existing items
        7. GROUP:
           - Run grouper to cluster related articles
        8. LOG:
           - Record run statistics
           - Print summary
    """

if __name__ == "__main__":
    main()
```

**Execution:**
```bash
python fetch_news.py
```

**Output Example:**
```
=== AI News Aggregator Pipeline ===

[1/5] Fetching from sources...
  ✓ OpenAI News (RSS): 12 items
  ✓ Anthropic News (Auto): 8 items
  ✓ Google AI Blog (Web): 15 items
  ✓ Search: "OpenAI news": 10 items
  Total fetched: 45 items

[2/5] Deduplicating...
  ✓ Removed 8 duplicates
  Unique items: 37

[3/5] Scoring with Claude Sonnet...
  ✓ Batch 1/4: 10 items scored
  ✓ Batch 2/4: 10 items scored
  ✓ Batch 3/4: 10 items scored
  ✓ Batch 4/4: 7 items scored
  Average score: 6.2

[4/5] Storing in database...
  ✓ Added 23 new items
  ✓ Updated 14 existing items

[5/5] Grouping related articles...
  ✓ Created 8 groups
  ✓ 15 items grouped, 22 standalone

Pipeline complete! Duration: 42.3s
```

---

## Learning Objectives Generation

### Process Flow

1. **User Action:** Click "⚡ Generate with Opus" button in expanded item
2. **API Call:** Send to Claude Opus API with custom prompt
3. **Prompt Template:**
```
You are an expert AI curriculum designer creating learning objectives for
educational video content about AI developments.

Given the following news item, generate 3-5 concise, actionable learning
objectives that a course or video covering this topic should teach.

Each learning objective should:
- Start with an action verb (Explain, Demonstrate, Compare, Implement, Analyze)
- Be specific and measurable
- Focus on the most important takeaways for AI practitioners
- Be 1-2 sentences max

Title: {title}
Source: {source}
Summary: {summary}
URL: {url}

Respond with ONLY the learning objectives as a markdown bulleted list.
```

4. **Response Processing:**
   - Parse markdown bullet list from Claude response
   - Store in database with `lo_generated_with_opus=True` flag
   - Update UI to show badge and objectives

5. **Display:**
   - Show "✨ Generated with Opus" badge
   - Render objectives as markdown (bullets render properly)

---

## Configuration Management

### Config Loading (`ainews/config.py`)

```python
def load_config() -> dict:
    """
    Load configuration from config.yaml.

    Returns:
        Config dictionary with defaults applied

    Defaults:
        - db_path: "data/ainews.db"
        - scoring_batch_size: 10
        - feeds: [] (empty list)
        - search_queries: [] (empty list)
    """

def save_config(config: dict):
    """
    Save configuration to config.yaml.

    Args:
        config: Config dictionary

    Implementation:
        1. Write to config.yaml with proper YAML formatting
        2. Preserve comments where possible
        3. Validate required fields (anthropic_api_key)
    """
```

---

## Error Handling

### Fetcher Errors
```python
try:
    items = fetch_rss(url, source_name)
except httpx.HTTPError as e:
    logger.warning(f"HTTP error fetching {url}: {e}")
    return []
except feedparser.ParserError as e:
    logger.warning(f"Parse error for {url}: {e}")
    return []
```

### Claude API Errors
```python
try:
    response = client.messages.create(...)
except anthropic.APIError as e:
    if e.status_code == 429:  # Rate limit
        time.sleep(60)  # Wait 1 minute
        retry()
    elif e.status_code >= 500:  # Server error
        logger.error(f"Claude API error: {e}")
        return []  # Skip this batch
    else:
        raise  # Re-raise for unexpected errors
```

### Database Errors
```python
try:
    db.add_item(item)
except sqlite3.IntegrityError:
    # Duplicate URL - update existing instead
    db.update_item(item)
except sqlite3.OperationalError as e:
    logger.error(f"Database error: {e}")
    # Retry with exponential backoff
```

---

## Performance Considerations

### Optimization Strategies

1. **Batch API Calls**
   - Score 10 items per Claude API call
   - Reduces API cost and latency
   - Configurable batch size

2. **Database Indexing**
   - Indexes on: url_hash, category, score, group_id, published
   - Fast filtering and sorting
   - Query time <100ms for 10,000 items

3. **Deduplication Caching**
   - Hash normalized URLs (MD5)
   - O(1) lookup for duplicates
   - Fuzzy matching only when needed

4. **Lazy Loading in UI**
   - st.expander loads details only when expanded
   - No upfront rendering of all content
   - Smooth performance with 100+ items

5. **Concurrent Fetching**
   - Use asyncio for parallel RSS fetches
   - ThreadPoolExecutor for I/O-bound operations
   - 3-5x faster than sequential

---

## Security Considerations

1. **API Key Protection**
   - Store in config.yaml (gitignored)
   - Never log or display API key
   - Validate key format before use

2. **SQL Injection Prevention**
   - Use parameterized queries
   - Never interpolate user input into SQL
   ```python
   # Good
   cursor.execute("SELECT * FROM news_items WHERE id = ?", (item_id,))

   # Bad
   cursor.execute(f"SELECT * FROM news_items WHERE id = {item_id}")
   ```

3. **URL Validation**
   - Validate URLs before fetching
   - Block local file:// URLs
   - Timeout requests after 30s

4. **HTML Sanitization**
   - Streamlit auto-escapes content
   - Only use `unsafe_allow_html=True` for trusted CSS
   - Never render user input as HTML

---

## Deployment

### Local Development

```bash
# 1. Clone repository
git clone <repo-url>
cd AINews

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers (for web scraping)
playwright install chromium

# 5. Create config
cp config.example.yaml config.yaml
# Edit config.yaml with your Anthropic API key

# 6. Run pipeline
python fetch_news.py

# 7. Start dashboard
streamlit run dashboard.py
```

### Production Deployment

**Option 1: Streamlit Cloud**
```yaml
# .streamlit/config.toml
[server]
headless = true
port = 8501

[browser]
gatherUsageStats = false
```

**Option 2: Docker**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Playwright dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium

COPY . .

CMD ["streamlit", "run", "dashboard.py"]
```

**Option 3: systemd Service**
```ini
[Unit]
Description=AI News Aggregator
After=network.target

[Service]
Type=simple
User=ainews
WorkingDirectory=/opt/ainews
ExecStart=/opt/ainews/.venv/bin/streamlit run dashboard.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Testing Strategy

### Unit Tests
```python
# tests/test_deduplicator.py
def test_url_normalization():
    url = "https://www.example.com/article?utm_source=twitter&id=123"
    normalized = normalize_url(url)
    assert normalized == "https://example.com/article?id=123"

def test_fuzzy_title_matching():
    title1 = "OpenAI Releases GPT-5"
    title2 = "OpenAI releases GPT-5 to public"
    ratio = calculate_fuzzy_ratio(title1, title2)
    assert ratio > 0.85  # Should be considered duplicate
```

### Integration Tests
```python
# tests/test_pipeline.py
def test_end_to_end_pipeline():
    # 1. Fetch from test RSS feed
    items = fetch_rss("https://example.com/test-feed.xml", "Test Source")
    assert len(items) > 0

    # 2. Deduplicate
    unique = deduplicate(items)
    assert len(unique) <= len(items)

    # 3. Score (mock Claude API)
    with mock.patch('anthropic.Anthropic') as mock_claude:
        mock_claude.return_value.messages.create.return_value = mock_response
        scored = score_items(mock_claude(), "test-model", unique)
        assert all(item.score is not None for item in scored)
```

---

## Monitoring & Logging

### Logging Configuration
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data/ainews.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('ainews')
```

### Key Metrics to Track
- Items fetched per source
- Deduplication rate
- Average score distribution
- API call latency
- Database query performance
- Pipeline execution time

---

## Troubleshooting Guide

### Common Issues

**Issue:** Pipeline fails with "No API key found"
- **Solution:** Set `anthropic_api_key` in config.yaml

**Issue:** Browser scraper fails with "Executable not found"
- **Solution:** Run `playwright install chromium`

**Issue:** Database locked error
- **Solution:** Close other processes accessing the database, or wait for transaction to complete

**Issue:** High Claude API costs
- **Solution:** Reduce `scoring_batch_size` or limit number of sources

**Issue:** Slow dashboard loading
- **Solution:** Add more database indexes, reduce date range filter

---

## Future Enhancements

### Planned Features
1. **Multi-user Support**
   - User accounts and authentication
   - Per-user acknowledgment tracking
   - Shared vs. personal feeds

2. **Advanced Filtering**
   - Tag system
   - Saved filter presets

3. **Analytics Dashboard**
   - Score trends over time
   - Source performance metrics
   - Topic clustering visualization

4. **Email Digest Output**
   - Daily/weekly email summaries sent to subscribers
   - Top-scored items with summaries
   - Customizable templates

---

## API Reference

### Anthropic Claude API Usage

**Scoring Call:**
```python
import anthropic

client = anthropic.Anthropic(api_key="sk-ant-...")

response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    messages=[
        {
            "role": "user",
            "content": scoring_prompt
        }
    ]
)

result = response.content[0].text
```

**Learning Objectives Call:**
```python
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": lo_prompt.format(
                title=item.title,
                source=item.source,
                summary=item.summary,
                url=item.url
            )
        }
    ]
)

objectives = response.content[0].text.strip()
```

---

## Conclusion

This specification provides a complete blueprint for recreating the AI News Aggregator application. Key design principles:

1. **Modularity:** Separate fetchers, processors, and UI layers
2. **Configurability:** YAML config for easy customization
3. **Extensibility:** Easy to add new sources or processing steps
4. **Reliability:** Error handling and retry logic throughout
5. **Performance:** Batching, caching, and indexing for speed
6. **User Experience:** Clean UI with Streamlit best practices

The application successfully demonstrates:
- Multi-source data aggregation
- AI-powered content curation
- Intelligent deduplication and grouping
- Interactive web dashboard
- Learning objective generation

For questions or issues, refer to the troubleshooting guide or examine the implementation details in this specification.
