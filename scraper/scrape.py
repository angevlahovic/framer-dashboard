"""
Framer Community Marketplace Scraper
Scrapes framer.com/community/marketplace and saves structured JSON data.
Runs daily via GitHub Actions — zero external dependencies beyond standard library + requests.
"""

import json
import time
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"])
    import requests

from html.parser import HTMLParser

BASE_URL = "https://www.framer.com"
MARKETPLACE_URL = f"{BASE_URL}/community/marketplace/templates/"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# Browser-realistic session
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
})

CATEGORIES = [
    "personal", "photography", "resume-cv", "landing-page", "professional-services",
    "technology", "real-estate", "health", "ecommerce", "food", "portfolio", "saas",
    "blog", "agency", "startup", "community", "education", "finance", "travel",
    "arts-and-crafts", "jewelry", "fashion", "beauty", "music", "sports", "nonprofit",
    "events", "architecture", "interior-design", "restaurant", "fitness", "legal",
    "consulting", "creative", "minimal", "dark", "colorful",
]


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            time.sleep(1.0)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 404:
                return None  # template removed
            elif r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  Attempt {attempt+1} error: {e}")
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return None


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_price(text):
    text = clean(text).lower()
    if "free" in text:
        return 0.0
    m = re.search(r"\$?([\d,]+(?:\.\d{2})?)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


# ─── SLUG EXTRACTOR ───────────────────────────────────────────────────────────

class SlugParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.slugs = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            m = re.match(r"/community/marketplace/templates/([^/?#]+)/?$", href)
            if m and m.group(1) not in ("categories", "featured"):
                self.slugs.add(m.group(1))


def scrape_slugs_from(html):
    p = SlugParser()
    p.feed(html)
    return p.slugs


# ─── DETAIL EXTRACTOR ─────────────────────────────────────────────────────────

class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts = []
        self._in_title = False
        self._page_title = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title and not self._page_title:
            self._page_title = text
        self._texts.append(text)

    def parse(self):
        texts = self._texts
        name = None
        price = None
        creator = None
        published = None
        last_updated = None
        categories = []
        features = []
        license_type = None
        num_candidates = []

        # Name from title
        if self._page_title:
            m = re.match(r"^([^·\-–—]+)", self._page_title)
            if m:
                name = clean(m.group(1))

        for i, t in enumerate(texts):
            # Buy button price
            buy_m = re.match(r"Buy for (\$[\d,]+)", t)
            if buy_m:
                price = float(buy_m.group(1).replace("$", "").replace(",", ""))

            # Standalone price
            if re.match(r"^\$[\d,]+$", t):
                price = float(t.replace("$", "").replace(",", ""))

            # Free
            if t.lower() == "free" and price is None:
                price = 0.0

            # Creator
            if t == "Creator" and i + 1 < len(texts):
                c = clean(texts[i + 1])
                if c and len(c) < 60:
                    creator = c

            # Published date
            if t == "Published" and i + 1 < len(texts):
                d = clean(texts[i + 1])
                if re.search(r"\d{4}", d):
                    published = d

            # License
            if t == "License" and i + 1 < len(texts):
                license_type = clean(texts[i + 1])

            # Updated
            if "Updated" in t:
                m = re.search(r"Updated (.+?ago)", t)
                if m:
                    last_updated = m.group(1)

            # Numeric candidates (for views/likes)
            if re.match(r"^\d{1,7}$", t.replace(",", "")):
                num_candidates.append(int(t.replace(",", "")))

            # Categories block
            if t == "Categories":
                j = i + 1
                while j < len(texts) and texts[j] not in ("Features", "Creator", "Published", "License", "Details"):
                    v = clean(texts[j])
                    if v and v not in ("See all", "Categories") and len(v) < 40:
                        categories.append(v)
                    j += 1

            # Features block
            if t == "Features":
                j = i + 1
                while j < len(texts) and texts[j] not in ("Categories", "Creator", "Published", "License", "Details"):
                    v = clean(texts[j])
                    if v and v != "Features" and len(v) < 40:
                        features.append(v)
                    j += 1

        # Assign views/likes: biggest number = views, second = likes
        num_candidates_sorted = sorted(set(num_candidates), reverse=True)
        views = num_candidates_sorted[0] if num_candidates_sorted else 0
        likes = num_candidates_sorted[1] if len(num_candidates_sorted) > 1 else 0

        # Sanity: likes shouldn't be near views in magnitude if there's a big gap
        if likes and views and likes > views * 0.9:
            likes = 0  # probably same number counted twice

        return {
            "name": name,
            "price": price,
            "is_free": price == 0.0,
            "creator": creator,
            "published": published,
            "last_updated": last_updated,
            "views": views,
            "likes": likes,
            "categories": list(dict.fromkeys(categories))[:8],
            "features": list(dict.fromkeys(features))[:20],
            "license": license_type,
        }


# ─── SCRAPE FUNCTIONS ─────────────────────────────────────────────────────────

def collect_all_slugs():
    slugs = set()

    print("  → Main listing page")
    html = fetch(MARKETPLACE_URL)
    if html:
        slugs |= scrape_slugs_from(html)

    print("  → Featured page")
    html = fetch(f"{MARKETPLACE_URL}featured/")
    if html:
        slugs |= scrape_slugs_from(html)

    for cat in CATEGORIES:
        url = f"{MARKETPLACE_URL}categories/{cat}/"
        html = fetch(url)
        if html:
            found = scrape_slugs_from(html)
            if found:
                print(f"  → [{cat}] {len(found)} templates")
                slugs |= found

    return list(slugs)


def scrape_detail(slug):
    url = f"{MARKETPLACE_URL}{slug}/"
    html = fetch(url)
    if not html:
        return None
    p = DetailParser()
    p.feed(html)
    data = p.parse()
    data["slug"] = slug
    data["url"] = url
    data["scraped_at"] = datetime.now(timezone.utc).isoformat()
    return data


# ─── HISTORY ─────────────────────────────────────────────────────────────────

def load_history():
    path = OUTPUT_DIR / "history.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_all(templates, meta):
    # Latest snapshot
    with open(OUTPUT_DIR / "latest.json", "w") as f:
        json.dump({"meta": meta, "templates": templates}, f, indent=2, ensure_ascii=False)

    # Daily history entry
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = [h for h in history if h.get("date") != today]
    paid = [t for t in templates if t.get("price") and t["price"] > 0]
    history.append({
        "date": today,
        "total": len(templates),
        "free": sum(1 for t in templates if t.get("is_free")),
        "paid": len(paid),
        "avg_price": round(sum(t["price"] for t in paid) / max(1, len(paid)), 2),
        "total_views": sum(t.get("views", 0) for t in templates),
        "total_likes": sum(t.get("likes", 0) for t in templates),
    })
    history = sorted(history, key=lambda h: h["date"])[-90:]

    with open(OUTPUT_DIR / "history.json", "w") as f:
        json.dump(history, f, indent=2)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Framer Community Marketplace Scraper")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 55)

    t0 = time.time()

    # Warm up session with homepage
    print("\n[0] Warming up session...")
    SESSION.get(f"{BASE_URL}/", timeout=10)
    time.sleep(1)

    print("\n[1] Collecting slugs...")
    slugs = collect_all_slugs()
    print(f"\n    Total unique templates: {len(slugs)}")

    print(f"\n[2] Scraping {len(slugs)} detail pages...")
    templates = []
    failed = []

    for i, slug in enumerate(slugs, 1):
        sys.stdout.write(f"\r    [{i}/{len(slugs)}] {slug[:40]:<40}")
        sys.stdout.flush()
        data = scrape_detail(slug)
        if data and data.get("name"):
            templates.append(data)
        else:
            failed.append(slug)

    print(f"\n\n[3] Saving data...")
    elapsed = round(time.time() - t0, 1)
    meta = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": elapsed,
        "total_found": len(slugs),
        "total_scraped": len(templates),
        "failed": len(failed),
        "failed_slugs": failed[:20],
    }
    save_all(templates, meta)

    print(f"\n✓ Complete in {elapsed}s")
    print(f"  {len(templates)} templates saved, {len(failed)} failed")
    if failed:
        print(f"  Failed slugs: {failed[:5]}{'...' if len(failed) > 5 else ''}")


if __name__ == "__main__":
    main()
