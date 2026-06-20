#!/usr/bin/env python3
"""
Framer Marketplace Scraper v4
Strategy: hit the paginated browse API directly, then enrich with detail pages
"""

import json, time, os, re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

def scrape():
    print("=" * 55)
    print(f"  Framer Scraper v4 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 55)

    templates = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )

        # ── STEP 1: intercept JSON from the listing page ──
        json_hits = []
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type","")
                if "json" in ct:
                    data = resp.json()
                    json_hits.append((resp.url, data))
            except: pass

        page = context.new_page()
        page.on("response", on_response)

        print("[1] Loading listing page & scrolling...")
        page.goto("https://www.framer.com/community/marketplace/templates/", wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # scroll to trigger lazy loads
        for _ in range(60):
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(0.4)
        time.sleep(3)

        print(f"    JSON responses captured: {len(json_hits)}")

        # ── STEP 2: pull real template slugs from the DOM ──
        links = page.eval_on_selector_all(
            "a[href*='/community/marketplace/templates/']",
            "els => els.map(e => e.href)"
        )
        slugs = set()
        for href in links:
            m = re.search(r"/templates/([^/?#]+)", href)
            if m:
                s = m.group(1)
                if s not in ("templates","categories","featured","hype","feed","activity"):
                    slugs.add(s)
        print(f"    Slugs found in DOM: {len(slugs)}")

        # ── STEP 3: visit each template detail page ──
        # First load any existing data to avoid re-scraping
        existing = {}
        latest_path = os.path.join(DATA_DIR, "latest.json")
        if os.path.exists(latest_path):
            try:
                with open(latest_path) as f:
                    old = json.load(f)
                for t in old.get("templates", []):
                    if t.get("name") and t["name"] != t["slug"]:
                        existing[t["slug"]] = t
                print(f"    Re-using {len(existing)} cached templates")
            except: pass

        to_scrape = [s for s in slugs if s not in existing]
        print(f"[2] Scraping {len(to_scrape)} new detail pages...")

        detail_page = context.new_page()
        done = 0

        for slug in to_scrape:
            try:
                url = f"https://www.framer.com/community/marketplace/templates/{slug}/"
                detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(0.8)

                # Extract structured data from JSON-LD first
                t = extract_jsonld(detail_page, slug, url)
                if not t:
                    t = extract_dom(detail_page, slug, url)

                if t:
                    templates[slug] = t

                done += 1
                if done % 50 == 0:
                    print(f"    {done}/{len(to_scrape)} pages scraped...")

            except Exception as e:
                pass

        browser.close()

    # Merge with cached
    for slug, t in existing.items():
        if slug not in templates:
            templates[slug] = t

    # Final list
    result = [t for t in templates.values() if t.get("name")]
    result.sort(key=lambda x: x.get("likes", 0), reverse=True)

    print(f"[3] Saving {len(result)} templates...")
    save(result)

    free = sum(1 for t in result if t.get("is_free"))
    print(f"✓ Done! {len(result)} templates | Free: {free} | Paid: {len(result)-free}")


def extract_jsonld(page, slug, url):
    """Try to get data from JSON-LD structured data"""
    try:
        scripts = page.eval_on_selector_all(
            'script[type="application/ld+json"]',
            "els => els.map(e => e.textContent)"
        )
        for s in scripts:
            try:
                data = json.loads(s)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    name = item.get("name")
                    if name:
                        price_raw = 0
                        offers = item.get("offers") or {}
                        if isinstance(offers, dict):
                            price_raw = float(offers.get("price", 0) or 0)
                        elif isinstance(offers, list) and offers:
                            price_raw = float(offers[0].get("price", 0) or 0)

                        creator = ""
                        author = item.get("author") or item.get("creator") or {}
                        if isinstance(author, dict):
                            creator = author.get("name","")
                        elif isinstance(author, str):
                            creator = author

                        cats = item.get("genre") or item.get("keywords") or ""
                        if isinstance(cats, list): cats = ", ".join(cats)

                        return make_template(slug, url, name, price_raw, creator, cats)
            except: pass
    except: pass
    return None


def extract_dom(page, slug, url):
    """Fallback DOM extraction"""
    try:
        # Get page title
        title = page.title()
        name = title.split(" — ")[0].split(" | ")[0].strip() or slug

        # Get price
        price_raw = 0
        price_els = page.query_selector_all("[class*='price'],[class*='Price']")
        for el in price_els:
            txt = el.inner_text().strip()
            m = re.search(r"\$(\d+(?:\.\d+)?)", txt)
            if m:
                price_raw = float(m.group(1))
                break

        # Get creator
        creator = ""
        creator_els = page.query_selector_all("[class*='creator'],[class*='Creator'],[class*='author'],[class*='Author']")
        for el in creator_els:
            txt = el.inner_text().strip()
            if txt and len(txt) < 60:
                creator = txt
                break

        # Get likes/views from page text
        body = page.inner_text("body") or ""
        likes = 0
        views = 0
        like_m = re.search(r"(\d[\d,]*)\s*(?:like|heart|❤)", body, re.I)
        view_m = re.search(r"(\d[\d,]*)\s*(?:view)", body, re.I)
        if like_m: likes = int(like_m.group(1).replace(",",""))
        if view_m: views = int(view_m.group(1).replace(",",""))

        return make_template(slug, url, name, price_raw, creator, "", likes, views)
    except:
        return None


def make_template(slug, url, name, price_raw, creator="", category="", likes=0, views=0, comments=0):
    is_free = price_raw == 0
    price = "Free" if is_free else f"${int(price_raw) if price_raw == int(price_raw) else price_raw}"
    return {
        "slug": slug,
        "name": name,
        "url": url,
        "price": price,
        "is_free": is_free,
        "creator": creator,
        "category": category,
        "likes": likes,
        "views": views,
        "comments": comments,
        "scraped_at": datetime.now(timezone.utc).isoformat()
    }


def save(templates):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(os.path.join(DATA_DIR, "latest.json"), "w") as f:
        json.dump({
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "total": len(templates),
            "templates": templates
        }, f, indent=2)

    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path) as f: history = json.load(f)
        except: pass

    free = sum(1 for t in templates if t.get("is_free"))
    paid = [t for t in templates if not t.get("is_free")]
    prices = [float(str(t["price"]).replace("$","").replace(",","")) for t in paid if t.get("price","Free") != "Free"]
    avg = round(sum(prices)/len(prices),2) if prices else 0

    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today, "total": len(templates), "free": free, "paid": len(paid),
        "avg_price": avg,
        "total_likes": sum(t.get("likes",0) for t in templates),
        "total_views": sum(t.get("views",0) for t in templates)
    })
    history = sorted(history, key=lambda x: x["date"])[-90:]

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


if __name__ == "__main__":
    scrape()
