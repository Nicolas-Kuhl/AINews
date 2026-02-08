# AI News Aggregator

A curated AI news dashboard that aggregates, scores, and groups news from multiple sources using Claude AI. Built for educational video production — designed to cut through the noise and surface what matters.

## Features

- **Multi-source fetching** — 49+ feeds from major AI/LLM vendors (OpenAI, Anthropic, Google, Microsoft, GitHub, AWS, Meta, NVIDIA, Hugging Face, Cohere, Mistral, Stability AI, Databricks, IBM) via RSS feeds and JavaScript-rendered websites using headless Chromium (Playwright)
- **AI scoring** — Claude Sonnet scores each item 1-10 for relevance, assigns categories (New Releases / Industry), writes summaries and learning objectives
- **Web-research enhanced learning objectives** — Claude Opus performs DuckDuckGo web searches to gather additional context and generate comprehensive, research-backed learning objectives on demand
- **Smart grouping** — clusters articles covering the same story using fuzzy title matching
- **Dark dashboard** — Streamlit app with a Pluralsight-inspired theme, expandable rows, filters, and acknowledge workflow
- **Source management** — enable/disable individual feeds, add/remove sources, all from the Settings tab
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
python fetch_news.py
```

**Automated scheduling:** When deployed (see [Deployment](#deployment)), the pipeline runs automatically every 15 minutes via cron. You can adjust the frequency in your crontab:

```bash
# Edit crontab to change schedule
crontab -e

# Examples:
# */15 * * * *   - Every 15 minutes (default)
# */30 * * * *   - Every 30 minutes
# 0 */6 * * *    - Every 6 hours
# 0 9 * * *      - Daily at 9am
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

### Generate RSS Feed

You can generate an RSS feed of high-priority items (score 8+) for use in RSS readers:

**Via Dashboard:**
1. Go to the **Settings** tab
2. Adjust the minimum score slider (default: 8)
3. Click **Generate RSS**
4. Download the XML file

**Via Command Line:**
```bash
python generate_rss_feed.py --min-score 8 --output data/high_priority.xml
```

To serve the feed for RSS readers:
```bash
# Start a simple HTTP server
python -m http.server 8080

# Subscribe in your RSS reader
http://localhost:8080/data/high_priority.xml
```

Or upload the XML file to your web hosting and subscribe to that URL.

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
├── fetch_news.py              # CLI pipeline entry point
├── dashboard.py               # Streamlit dashboard
├── generate_rss_feed.py       # Generate RSS feed for high-priority items
├── config.example.yaml        # Example configuration (copy to config.yaml)
├── requirements.txt           # Python dependencies
├── data/                      # SQLite database and logs (gitignored)
└── ainews/                    # Core package
    ├── config.py              # Config loader / saver
    ├── models.py              # Data models (RawNewsItem, ProcessedNewsItem)
    ├── rss_generator.py       # RSS feed XML generator
    ├── fetchers/
    │   ├── rss_fetcher.py     # RSS/auto-detect feed fetcher
    │   ├── web_page_fetcher.py # Playwright browser fetcher
    │   ├── web_searcher.py    # DuckDuckGo search
    │   └── html_scraper.py    # HTML link/title extraction
    ├── processing/
    │   ├── scorer.py          # Claude scoring (Sonnet)
    │   ├── deduplicator.py    # URL normalization + fuzzy title dedup
    │   └── grouper.py         # Fuzzy story grouping
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
| `feeds` | List of news sources (name, url, type, enabled) | 49 sources (6 enabled by default) |
| `search_queries` | DuckDuckGo search terms | `[]` |
| `dedup_threshold` | Fuzzy match threshold for dedup (0-100) | `80` |
| `max_items_per_feed` | Max items fetched per source | `20` |
| `scoring_batch_size` | Items per Claude API request | `20` |
| `scoring_prompt` | Custom scoring prompt (optional) | Built-in default |
| `lo_prompt` | Custom learning objectives prompt (optional) | Built-in default |
| `rss_output_path` | Output path for RSS feed | `data/high_priority.xml` |
| `rss_min_score` | Minimum score for RSS feed items | `8` |

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
./venv/bin/python fetch_news.py
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

**Access RSS feed:**
```bash
# Test locally on EC2
curl http://localhost/rss/high_priority.xml

# Access from browser
http://YOUR_EC2_PUBLIC_IP/rss/high_priority.xml
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
