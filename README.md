# AI News Aggregator

A curated AI news dashboard that aggregates, scores, and groups news from multiple sources using Claude AI. Built for educational video production — designed to cut through the noise and surface what matters.

## Features

- **Two-tier source system** — "Trusted" sources (official vendor feeds) scan every 15 minutes; "Open" sources (general news, search) run as a daily digest
- **Multi-source fetching** — 49+ feeds from major AI/LLM vendors (OpenAI, Anthropic, Google, Microsoft, GitHub, AWS, Meta, NVIDIA, Hugging Face, Cohere, Mistral, Stability AI, Databricks, IBM) via RSS feeds and JavaScript-rendered websites using headless Chromium (Playwright)
- **Newsletter ingestion** — IMAP email fetcher reads AI newsletters (TLDR AI, Import AI, AlphaSignal, etc.), extracts stories using Claude, and feeds them into the normal pipeline
- **AI scoring** — Claude Sonnet scores each item 1-10 for relevance, assigns categories (New Releases / Research / Business / Developer Tools), writes summaries and learning objectives
- **Web-research enhanced learning objectives** — Claude Opus performs DuckDuckGo web searches to gather additional context and generate comprehensive, research-backed learning objectives on demand
- **Smart grouping** — clusters articles covering the same story using fuzzy title matching + semantic dedup via Claude
- **Three RSS feeds** — Combined (score 8+), Trusted (all scores from official sources), and Daily Digest (score 7+ from open sources)
- **Daily Digest page** — Dashboard page showing stories grouped by day, sorted by score, with direct article links
- **Dark dashboard** — Streamlit app with a minimalist Linear/Notion aesthetic, expandable rows, filters, and acknowledge workflow
- **Source management** — enable/disable individual feeds, add/remove sources, manage newsletter senders, all from the Settings tab
- **Customizable prompts** — both the scoring prompt and learning objectives prompt are fully editable

## Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Nicolas-Kuhl/AINews.git
cd AINews
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

The website scraper uses a headless Chromium browser to fetch JavaScript-rendered pages:

```bash
playwright install chromium
```

> **Note:** On a fresh Linux machine you may also need system dependencies:
> ```bash
> playwright install-deps chromium
> ```

### 5. Configure

Copy the example config and add your Anthropic API key:

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` and replace `YOUR_API_KEY_HERE` with your key. Alternatively, set the environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 6. Create the data directory

```bash
mkdir -p data
```

## Usage

### Run the fetch pipeline

Fetches news from all enabled sources, deduplicates, scores with Claude, and groups related stories:

```bash
# Run all sources
python fetch_news.py

# Run only trusted (official vendor) sources
python fetch_news.py --category trusted

# Run only open (daily digest + newsletters) sources
python fetch_news.py --category open
```

**Automated scheduling:** When deployed, two cron jobs run automatically:

```bash
# Trusted sources — every 15 minutes
*/15 * * * * cd /opt/ainews && python fetch_news.py --category trusted

# Open sources + newsletters — daily at 5am AEDT (18:00 UTC)
0 18 * * * cd /opt/ainews && . /opt/ainews/.env && export AINEWS_EMAIL_PASSWORD && python fetch_news.py --category open
```

### Launch the dashboard

```bash
streamlit run dashboard.py
```

The dashboard opens at `http://localhost:8501`.

**Optional: Enable authentication** (recommended before deployment):
```bash
chmod +x scripts/setup_auth.sh
./scripts/setup_auth.sh
# Default: username=admin, password=changeme123
```

From the dashboard you can:

- Browse scored news in the **New Releases** and **Industry News** tabs
- Expand any row to see the summary, score reasoning, and learning objectives
- Click **Generate With Opus** to create deep learning objectives for any item
- Use the **Settings** tab to run the pipeline, manage sources, and edit prompts
- Filter by score range, date, and sort order in the sidebar

### RSS Feeds

Three RSS feeds are generated automatically after each pipeline run:

| Feed | File | Filter | Description |
|------|------|--------|-------------|
| **Combined** | `high_priority.xml` | Score 8+ | Top stories from all sources |
| **Trusted** | `high_priority_trusted.xml` | All scores | Everything from official vendor channels |
| **Digest** | `high_priority_digest.xml` | Score 7+ | Daily digest from open/search sources |

**Access on EC2:**
```
http://YOUR_EC2_IP/rss/high_priority.xml
http://YOUR_EC2_IP/rss/high_priority_trusted.xml
http://YOUR_EC2_IP/rss/high_priority_digest.xml
```

**Generate manually:**
```bash
python generate_rss_feed.py --min-score 8 --output data/high_priority.xml
```

## Deployment

### AWS Deployment

See **[deployment/QUICKSTART.md](deployment/QUICKSTART.md)** for deployment options:

- **🚀 Simple (5 min):** EC2 deployment - [Setup Script](deployment/aws-ec2-setup.sh)
- **🏢 Production (30 min):** App Runner + ECS - [Full Guide](deployment/README-AWS.md)
- **🐳 Local Testing:** Docker - See `docker-compose.yml`

Quick start with Docker:
```bash
docker-compose up dashboard
```

## Project Structure

```
AINews/
├── fetch_news.py              # CLI pipeline entry point (--category trusted|open)
├── dashboard.py               # Streamlit dashboard
├── dashboard_components.py    # UI rendering components
├── generate_rss_feed.py       # Generate RSS feed for high-priority items
├── config.example.yaml        # Example configuration (copy to config.yaml)
├── requirements.txt           # Python dependencies
├── assets/
│   └── style.css              # Custom dark theme CSS
├── data/                      # SQLite database, logs, RSS feeds (gitignored)
└── ainews/                    # Core package
    ├── config.py              # Config loader / saver
    ├── models.py              # Data models (RawNewsItem, ProcessedNewsItem)
    ├── rss_generator.py       # RSS feed generator (combined, trusted, digest)
    ├── fetchers/
    │   ├── rss_fetcher.py     # RSS/auto-detect feed fetcher
    │   ├── html_scraper.py    # HTML link/title extraction
    │   ├── web_searcher.py    # DuckDuckGo search
    │   ├── content_fetcher.py # Full article content via trafilatura
    │   └── email_fetcher.py   # IMAP newsletter ingestion + Claude extraction
    ├── processing/
    │   ├── scorer.py          # Claude scoring (Sonnet)
    │   ├── deduplicator.py    # URL normalization + fuzzy title dedup
    │   └── grouper.py         # Fuzzy + semantic story grouping
    └── storage/
        └── database.py        # SQLite with auto-migrations
```

## Configuration

All settings are in `config.yaml` and can also be edited from the dashboard Settings tab:

| Key | Description | Default |
|-----|-------------|---------|
| `anthropic_api_key` | Your Anthropic API key | — |
| `model` | Model used for scoring | `claude-sonnet-4-5-20250929` |
| `lo_model` | Model used for learning objectives | `claude-opus-4-6` |
| `lo_web_research` | Enable web research for learning objectives | `true` |
| `lo_search_count` | Number of web searches per learning objective | `3` |
| `feeds` | List of news sources (name, url, type, enabled, category) | 49 sources |
| `feeds[].category` | `trusted` (frequent scan) or `open` (daily digest) | — |
| `search_queries` | DuckDuckGo search terms | `[]` |
| `trusted_interval` | Minutes between trusted source scans | `15` |
| `open_interval` | Minutes between open source scans | `1440` |
| `dedup_threshold` | Fuzzy match threshold for dedup (0-100) | `80` |
| `semantic_dedup` | Enable Claude-based semantic dedup | `true` |
| `max_items_per_feed` | Max items fetched per source | `20` |
| `scoring_batch_size` | Items per Claude API request | `20` |
| `scoring_prompt` | Custom scoring prompt (optional) | Built-in default |
| `lo_prompt` | Custom learning objectives prompt (optional) | Built-in default |
| `rss_output_path` | Output path for RSS feed | `data/high_priority.xml` |
| `rss_min_score` | Minimum score for combined RSS feed | `8` |
| `newsletters.enabled` | Enable email newsletter ingestion | `false` |
| `newsletters.email` | Gmail address for newsletters | — |
| `newsletters.imap_host` | IMAP server hostname | `imap.gmail.com` |
| `newsletters.senders` | List of newsletter senders (name + address) | `[]` |

## Common Operations

### Local Development

**Clear the database:**
```bash
rm data/ainews.db
```
The database will be automatically recreated on the next run.

**View pipeline logs:**
```bash
tail -f data/pipeline.log
```

**Check RSS feed locally:**
```bash
# After running the pipeline
cat data/high_priority.xml

# Or serve it locally
python -m http.server 8080
# Access at: http://localhost:8080/data/high_priority.xml
```

### EC2 Deployment Operations

**Update application from GitHub:**
```bash
cd /opt/ainews
git pull origin main
sudo systemctl restart ainews-dashboard
```

**Clear the database:**
```bash
rm /opt/ainews/data/ainews.db
```

**Check cron job status:**
```bash
# View cron schedule
crontab -l

# Check if crond service is running (Amazon Linux 2023)
sudo systemctl status crond

# View recent cron execution logs
grep CRON /var/log/cron | tail -20

# Or check syslog (Ubuntu)
grep CRON /var/log/syslog | tail -20
```

**View pipeline logs:**
```bash
# Real-time log viewing
tail -f /opt/ainews/data/pipeline.log

# View last 50 lines
tail -50 /opt/ainews/data/pipeline.log

# Search for errors
grep -i error /opt/ainews/data/pipeline.log
```

**Manually run the pipeline:**
```bash
cd /opt/ainews

# Run all sources
./venv/bin/python fetch_news.py

# Run only trusted sources
./venv/bin/python fetch_news.py --category trusted

# Run only open/digest sources (includes newsletters)
. /opt/ainews/.env && export AINEWS_EMAIL_PASSWORD
./venv/bin/python fetch_news.py --category open
```

**Check dashboard service:**
```bash
# Service status
sudo systemctl status ainews-dashboard

# View logs
sudo journalctl -u ainews-dashboard -f

# Restart service
sudo systemctl restart ainews-dashboard

# Stop/start service
sudo systemctl stop ainews-dashboard
sudo systemctl start ainews-dashboard
```

**Check Nginx:**
```bash
# Status
sudo systemctl status nginx

# Test configuration
sudo nginx -t

# Restart
sudo systemctl restart nginx

# View logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

**Access RSS feeds:**
```bash
# Combined (score 8+)
curl http://localhost/rss/high_priority.xml

# Trusted sources (all scores)
curl http://localhost/rss/high_priority_trusted.xml

# Daily digest (score 7+)
curl http://localhost/rss/high_priority_digest.xml
```

**Troubleshooting:**
```bash
# Check all services are running
sudo systemctl status ainews-dashboard nginx crond

# Test if Streamlit is responding
curl http://localhost:8501

# Test if Nginx is proxying correctly
curl http://localhost

# Check disk space
df -h

# Check memory usage
free -h

# View Python errors in dashboard
sudo journalctl -u ainews-dashboard --since "1 hour ago"
```
