#!/usr/bin/env python3
"""
Framer Community Marketplace Scraper v3
Intercepts internal API calls + deep scroll to get ALL templates
"""

import json
import time
import os
import re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

MARKETPLACE_URL = "https://www.framer.com/community/marketplace/templates/"

def scrape():
    print("=" * 55)
    print("  Framer Community Marketplace Scraper v3")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 55)

    api_responses = []
    templates_map = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )

        def handle_response(response):
            url = response.url
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and any(x in url for x in ["/api/", "marketplace", "resources", "templates", "community", "framer"]):
                    data = response.json()
                    api_responses.append({"url": url, "data": data})
            except:
                pass

        page = context.new_page()
        page.on("response", handle_response)

        print("[1] Loading marketplace...")
        page.goto(MARKETPLACE_URL, wait_until="networkidle", timeout=60000)
        time.sleep(5)

        print("[2] Deep scrolling to load all templates...")
        last_height = 0
        stale = 0

        for i in range(150):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.keyboard.press("End")
            time.sleep(1.2)

            h = page.evaluate("document.body.scrollHeight")
            if i % 15 == 0:
                count = len(page.query_selector_all("a[href*='/community/marketplace/templates/']"))
                print(f"    Scroll {i}: height={h}, cards visible={count}, api calls={len(api_responses)}")

            if h == last_height:
                stale += 1
                if stale >= 5:
                    print(f"    Fully loaded at scroll {i}")
                    break
            else:
                stale = 0
            last_height = h

        time.sleep(3)

        print(f"[3] Parsing {len(api_responses)} API responses...")
        for resp in api_responses:
            extract_templates(resp["data"], templates_map)

        print(f"    Found {len(templates_map)} from API")

        # Always also scrape DOM for any missed items
        print("[4] DOM scrape for remaining cards...")
        dom_items = dom_scrape(page)
        added = 0
        for t in dom_items:
            if t["slug"] not in templates_map:
                templates_map[t["slug"]] = t
                added += 1
        print(f"    Added {added} more from DOM")

        browser.close()

    # Filter junk
    JUNK = {"categories", "featured", "all", "templates", "hype", "members", "gallery", "components", "vectors", "plugins"}
    templates = []
    for slug, t in templates_map.items():
        if slug in JUNK or slug.startswith("#"):
            continue
        if t.get("name") in {"See all", "All Categories", "All Templates", ""}:
            continue
        # Skip if name exactly equals slug and 0 likes (likely nav item)
        if t.get("name", "").lower().replace("-", "") == slug.lower().replace("-", "") and t.get("likes", 0) == 0 and t.get("views", 0) == 0:
            # Keep it anyway - might be a real template with no engagement yet
            pass
        templates.append(t)

    templates.sort(key=lambda x: x.get("likes", 0), reverse=True)

    print(f"[5] Saving {len(templates)} templates...")
    save_data(templates)

    free = sum(1 for t in templates if t.get("is_free"))
    print(f"\n✓ Done! {len(templates)} templates | Free: {free} | Paid: {len(templates)-free}")


def extract_templates(data, out):
    if isinstance(data, list):
        for item in data:
            extract_templates(item, out)
    elif isinstance(data, dict):
        slug = data.get("slug") or data.get("handle") or data.get("id")
        name = data.get("name") or data.get("title")

        if slug and name and isinstance(slug, str) and len(slug) > 1 and isinstance(name, str):
            price_raw = data.get("price") or data.get("amount") or 0
            is_free = True
            price = "Free"

            if isinstance(price_raw, (int, float)) and price_raw > 0:
                price = f"${int(price_raw)}" if price_raw == int(price_raw) else f"${price_raw:.2f}"
                is_free = False
            elif isinstance(price_raw, str) and price_raw not in ("", "0", "free", "Free"):
                price = price_raw if "$" in price_raw else f"${price_raw}"
                is_free = False

            creator = data.get("creator") or data.get("author") or data.get("user") or {}
            creator_name = ""
            if isinstance(creator, dict):
                creator_name = creator.get("name") or creator.get("displayName") or creator.get("username") or ""
            elif isinstance(creator, str):
                creator_name = creator

            cats = data.get("categories") or data.get("category") or data.get("tags") or []
            if isinstance(cats, list):
                cats = ", ".join(str(c.get("name", c) if isinstance(c, dict) else c) for c in cats)
            elif isinstance(cats, dict):
                cats = cats.get("name", "")

            out[str(slug)] = {
                "slug": str(slug),
                "name": str(name),
                "url": f"https://www.framer.com/community/marketplace/templates/{slug}/",
                "price": price,
                "is_free": is_free,
                "creator": creator_name,
                "category": str(cats),
                "likes": int(data.get("likes") or data.get("likeCount") or data.get("hearts") or 0),
                "comments": int(data.get("comments") or data.get("commentCount") or 0),
                "views": int(data.get("views") or data.get("viewCount") or 0),
                "scraped_at": datetime.now(timezone.utc).isoformat()
            }

        for v in data.values():
            if isinstance(v, (dict, list)):
                extract_templates(v, out)


def dom_scrape(page):
    results = []
    seen = set()
    cards = page.query_selector_all("a[href*='/community/marketplace/templates/']")

    for card in cards:
        try:
            href = card.get_attribute("href") or ""
            m = re.search(r"/templates/([^/?#]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            text = card.inner_text().strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if not lines:
                continue

            name = lines[0]
            price = "Free"
            is_free = True
            likes = 0
            comments = 0

            for line in lines[1:]:
                if "$" in line:
                    nums = re.findall(r"\$[\d,]+", line)
                    if nums:
                        price = nums[0]
                        is_free = False
                ns = re.findall(r"\b(\d[\d,.]*[Kk]?)\b", line)
                for n in ns:
                    try:
                        v = n.replace(",", "")
                        val = int(float(v[:-1]) * 1000) if v.lower().endswith("k") else int(float(v))
                        if likes == 0 and val > 0:
                            likes = val
                        elif comments == 0 and val > 0 and val != likes:
                            comments = val
                    except:
                        pass

            results.append({
                "slug": slug,
                "name": name,
                "url": f"https://www.framer.com/community/marketplace/templates/{slug}/",
                "price": price,
                "is_free": is_free,
                "creator": "",
                "category": "",
                "likes": likes,
                "comments": comments,
                "views": 0,
                "scraped_at": datetime.now(timezone.utc).isoformat()
            })
        except:
            continue
    return results


def save_data(templates):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(os.path.join(DATA_DIR, "latest.json"), "w") as f:
        json.dump({"scraped_at": datetime.now(timezone.utc).isoformat(), "total": len(templates), "templates": templates}, f, indent=2)

    history_path = os.path.join(DATA_DIR, "history.json")
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path) as f:
                history = json.load(f)
        except:
            pass

    free_c = sum(1 for t in templates if t.get("is_free"))
    paid_t = [t for t in templates if not t.get("is_free")]
    def to_n(p):
        try: return float(str(p).replace("$","").replace(",","").strip())
        except: return 0.0
    prices = [to_n(t["price"]) for t in paid_t if to_n(t["price"]) > 0]
    avg = round(sum(prices)/len(prices), 2) if prices else 0

    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "total": len(templates), "free": free_c, "paid": len(paid_t),
                    "avg_price": avg, "total_likes": sum(t.get("likes",0) for t in templates),
                    "total_comments": sum(t.get("comments",0) for t in templates),
                    "total_views": sum(t.get("views",0) for t in templates)})
    history = sorted(history, key=lambda x: x["date"])[-90:]

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


if __name__ == "__main__":
    scrape()
