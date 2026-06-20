# Framer Marketplace Intelligence Dashboard

A free, automated dashboard that scrapes the Framer Community Marketplace daily and gives you clean analytics.

## What you get

- **Daily auto-updates** — data refreshes every morning at 6am UTC automatically
- **Full marketplace coverage** — every template across all categories
- **Rich data per template** — name, price, creator, views, likes, categories, features, publish date
- **90-day trend history** — track growth over time
- **Dashboard** — KPIs, charts, sortable/filterable table, leaderboard

---

## Setup (one-time, ~10 minutes, no coding)

### Step 1 — Create a GitHub account
Go to https://github.com and sign up (free).

### Step 2 — Create a new repository
1. Click the **+** button → "New repository"
2. Name it: `framer-dashboard`
3. Set to **Public** (required for free GitHub Actions)
4. Click "Create repository"

### Step 3 — Upload these files
Upload all files from this folder maintaining the folder structure:
```
.github/
  workflows/
    scrape.yml
scraper/
  scrape.py
dashboard/
  index.html
data/              ← will be created automatically by scraper
README.md
```

You can drag and drop into the GitHub web interface, or use the GitHub Desktop app.

### Step 4 — Run the scraper manually (first time)
1. In your GitHub repo, click the **Actions** tab
2. Click "Daily Framer Marketplace Scrape" in the left sidebar
3. Click "Run workflow" → "Run workflow"
4. Wait ~20–30 minutes for it to complete
5. A `data/` folder will appear with `latest.json` and `history.json`

### Step 5 — Deploy the dashboard on Vercel
1. Go to https://vercel.com and sign up with your GitHub account (free)
2. Click "New Project" → "Import" your `framer-dashboard` repo
3. Set **Root Directory** to `dashboard`
4. Click Deploy

Your dashboard is now live at a URL like `framer-dashboard.vercel.app`!

---

## How it works

- **Scraper** (`scraper/scrape.py`) — pure Python, no external dependencies except standard library. Walks every category page, collects all template slugs, then visits each detail page to extract all data.
- **GitHub Actions** (`.github/workflows/scrape.yml`) — runs the scraper every day at 6am UTC, commits the updated JSON files back to the repo automatically.
- **Vercel** — hosts the dashboard and serves the JSON data files. Re-deploys automatically whenever GitHub pushes new data.
- **Dashboard** (`dashboard/index.html`) — single HTML file with Chart.js. Reads `../data/latest.json` and `../data/history.json` at load time.

## Data collected per template

| Field | Description |
|---|---|
| `name` | Template name |
| `slug` | URL slug |
| `price` | Price in USD (0 = free) |
| `is_free` | Boolean |
| `creator` | Creator name |
| `published` | Publish date |
| `last_updated` | Last update (relative) |
| `views` | View count |
| `likes` | Like count |
| `categories` | Category tags |
| `features` | Feature tags (CMS, Forms, etc.) |
| `license` | License type |
| `url` | Full URL |
| `scraped_at` | ISO timestamp |

## Daily history tracked

Each day's snapshot records: total count, free count, paid count, average price, total views, total likes.

## Troubleshooting

**Scraper failed in GitHub Actions?**
Check the Actions tab → click the failed run → read the logs. Usually a temporary network issue — just re-run it.

**Dashboard shows "Could not load data"?**
Make sure the scraper has run at least once and `data/latest.json` exists in your repo.

**Missing templates?**
The scraper covers all category pages. New templates added to the marketplace will appear in the next daily run.
