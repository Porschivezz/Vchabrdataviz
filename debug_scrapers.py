#!/usr/bin/env python3
"""Debug TASS and Gazeta.ru scrapers — show what's happening at each step."""

import sys, os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@db:5432/monitoring")
sys.path.insert(0, os.path.dirname(__file__) or ".")

import requests
from bs4 import BeautifulSoup
from src.core.config import settings

proxy_url = settings.scraper_proxy_url.strip()
proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})
if proxies:
    session.proxies.update(proxies)

print("=" * 70)
print("DEBUG: TASS article page")
print("=" * 70)

# Fetch one TASS article
tass_url = "https://tass.ru/ekonomika/26985769"
print(f"Fetching: {tass_url}")
try:
    resp = session.get(tass_url, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
    print(f"Content length: {len(resp.text)} chars")

    # Check if it's a redirect or error page
    if resp.status_code != 200:
        print(f"Response body (first 500): {resp.text[:500]}")
    else:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check for __NEXT_DATA__
        next_data = soup.find("script", id="__NEXT_DATA__")
        print(f"\n__NEXT_DATA__ script: {'FOUND' if next_data else 'NOT FOUND'}")

        # Check for JSON-LD
        jsonld = soup.find_all("script", type="application/ld+json")
        print(f"JSON-LD scripts: {len(jsonld)}")
        for i, s in enumerate(jsonld):
            print(f"  JSON-LD[{i}]: {s.string[:200] if s.string else 'empty'}...")

        # Check title
        h1 = soup.find("h1")
        print(f"\n<h1>: {h1.get_text(strip=True)[:100] if h1 else 'NOT FOUND'}")

        # Check content containers
        for sel in ("div.text-content", "div.news-body", "div[class*='NewsBody']",
                     "article", "div[class*='text']"):
            el = soup.select_one(sel)
            if el:
                ps = el.find_all("p")
                text = el.get_text(strip=True)
                print(f"  {sel}: FOUND, {len(ps)} <p> tags, {len(text)} chars text")
            else:
                print(f"  {sel}: NOT FOUND")

        # Show all div classes that contain <p> tags
        print("\nDivs with multiple <p> tags:")
        for div in soup.find_all("div"):
            ps = div.find_all("p", recursive=False)
            if len(ps) >= 2:
                classes = " ".join(div.get("class", []))
                total_text = sum(len(p.get_text()) for p in ps)
                if total_text > 100:
                    print(f"  div.{classes}: {len(ps)} <p>, {total_text} chars")

        # Show first 10 substantial <p> tags
        print("\nFirst 10 substantial <p> tags in body:")
        body = soup.find("body")
        if body:
            count = 0
            for p in body.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) > 20:
                    parent_class = " ".join(p.parent.get("class", []))
                    print(f"  <p> in .{parent_class}: {text[:100]}")
                    count += 1
                    if count >= 10:
                        break
            if count == 0:
                print("  NO substantial <p> tags found!")

        # Check for articleBody in JSON
        import re, json
        for pattern in (r'"articleBody"\s*:\s*"(.{0,200})"',
                        r'"text"\s*:\s*"(.{0,200})"',
                        r'"body"\s*:\s*"(.{0,200})"'):
            m = re.search(pattern, resp.text)
            if m:
                print(f"\nFound JSON field matching {pattern[:20]}...: {m.group(1)[:150]}...")

except Exception as exc:
    print(f"ERROR: {exc}")
    import traceback
    traceback.print_exc()

print("\n\n" + "=" * 70)
print("DEBUG: Gazeta.ru listing page")
print("=" * 70)

gazeta_url = "https://www.gazeta.ru/"
print(f"Fetching: {gazeta_url}")
try:
    resp = session.get(gazeta_url, timeout=30)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
    print(f"Content length: {len(resp.text)} chars")

    if resp.status_code != 200:
        print(f"Response body (first 500): {resp.text[:500]}")
    else:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Count all links
        all_links = soup.find_all("a", href=True)
        print(f"Total <a> links: {len(all_links)}")

        # Show internal links with depth >= 2
        internal = []
        for a in all_links:
            href = a["href"]
            if href.startswith("/") and len(href.split("/")) >= 3:
                internal.append(href)
            elif "gazeta.ru/" in href:
                path = href.split("gazeta.ru")[-1]
                if len(path.split("/")) >= 3:
                    internal.append(href)

        print(f"Internal links (depth >= 2): {len(internal)}")
        print("Sample links (first 20):")
        for link in internal[:20]:
            print(f"  {link}")

        # Check if it might be JS-rendered
        scripts = soup.find_all("script")
        print(f"\n<script> tags: {len(scripts)}")
        noscript = soup.find("noscript")
        if noscript:
            print(f"<noscript> content: {noscript.get_text(strip=True)[:200]}")

except Exception as exc:
    print(f"ERROR: {exc}")
    import traceback
    traceback.print_exc()
