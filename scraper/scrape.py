#!/usr/bin/env python3
"""
Framer Community Marketplace Scraper
Uses Playwright to handle the virtual scroll grid
"""

import json
import time
import os
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.framer.com/community/marketplace/templates/"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

def scrape():
    print("=" * 55)
    print("  Framer Community Marketplace Scraper")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 55)

    templates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()

        print("[1] Loading marketplace...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        print("[2] Scrolling to load all templates...")
        prev_count = 0
        stale_rounds = 0

        while stale_rounds < 4:
            # Scroll to bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # Count cards currently visible
            cards = page.query_selector_all("a[href*='/community/marketplace/templates/']")
            current_count = len(cards)
            print(f"    Cards found: {current_count}")

            if current_count == prev_count:
                stale_rounds += 1
            else:
                stale_rounds = 0
                prev_count = current_count

        print(f"[3] Extracting data from {prev_count} cards...")

        seen_slugs = set()
        cards = page.query_selector_all("a[href*='/community/marketplace/templates/']")

        for card in cards:
            try:
                href = card.get_attribute("href") or ""
                # Extract slug from href
                parts = [p for p in href.split("/") if p]
                if not parts:
                    continue
                slug = parts[-1]
                if slug in seen_slugs or slug == "templates":
                    continue
                seen_slugs.add(slug)

                # Get text content of the card
                text = card.inner_text().strip()
                lines = [l.strip() for l in text.split("\n") if l.strip()]

                name = lines[0] if lines else slug
                
                # Parse price and type
                price = "Free"
                resource_type = "Template"
                for line in lines:
                    if "$" in line:
                        price = line.strip()
                    if "·" in line:
                        parts2 = line.split("·")
                        resource_type = parts2[0].strip()
                        if len(parts2) > 1:
                            price_part = parts2[1].strip()
                            if price_part:
                                price = price_part

                # Extract likes and comments
                likes = 0
                comments = 0
                for line in lines:
                    try:
                        val = int(line.replace(",", "").replace("K", "000"))
                        if likes == 0:
                            likes = val
                        elif comments == 0:
                            comments = val
                    except:
                        pass

                templates.append({
                    "slug": slug,
                    "name": name,
                    "url": f"https://www.framer.com/community/marketplace/templates/{slug}/",
                    "price": price,
                    "is_free": price.lower() == "free",
                    "type": resource_type,
                    "likes": likes,
                    "comments": comments,
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                })

            except Exception as e:
                continue

        browser.close()

    print(f"[4] Saving {len(templates)} templates...")

    # Save latest.json
    latest_path = os.path.join(DATA_DIR, "latest.json")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total": len(templates),
        "templates": templates
    }
    with open(latest_path, "w") as f:
        json.dump(output, f, indent=2)

    # Update history.json
    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                history = json.load(f)
        except:
            history = []

    free_count = sum(1 for t in templates if t["is_free"])
    paid = [t for t in templates if not t["is_free"]]
    
    def parse_price(p):
        try:
            return float(p.replace("$", "").replace(",", "").strip())
        except:
            return 0.0

    paid_prices = [parse_price(t["price"]) for t in paid if parse_price(t["price"]) > 0]
    avg_price = round(sum(paid_prices) / len(paid_prices), 2) if paid_prices else 0

    # Remove existing entry for today if re-running
    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today,
        "total": len(templates),
        "free": free_count,
        "paid": len(paid),
        "avg_price": avg_price,
        "total_likes": sum(t["likes"] for t in templates),
        "total_comments": sum(t["comments"] for t in templates)
    })
    # Keep last 90 days
    history = sorted(history, key=lambda x: x["date"])[-90:]

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"✓ Done! {len(templates)} templates saved.")
    print(f"  Free: {free_count} | Paid: {len(paid)} | Avg price: ${avg_price}")

if __name__ == "__main__":
    scrape()
