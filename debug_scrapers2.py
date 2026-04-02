#!/usr/bin/env python3
"""Debug: try alternative endpoints for TASS and Gazeta.ru (API, AMP, mobile)."""

import sys, os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@db:5432/monitoring")
sys.path.insert(0, os.path.dirname(__file__) or ".")

import json
import requests
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

article_id = "26985769"

def try_url(label, url, headers=None):
    print(f"\n--- {label} ---")
    print(f"URL: {url}")
    try:
        h = dict(session.headers)
        if headers:
            h.update(headers)
        resp = session.get(url, timeout=30, headers=headers or {})
        print(f"Status: {resp.status_code}")
        ct = resp.headers.get("content-type", "")
        print(f"Content-Type: {ct}")
        print(f"Length: {len(resp.text)} chars")

        if resp.status_code == 200:
            text = resp.text
            # Check if it has actual content
            if "json" in ct.lower() or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = resp.json()
                    print(f"JSON keys: {list(data.keys()) if isinstance(data, dict) else f'array[{len(data)}]'}")
                    print(f"JSON preview: {json.dumps(data, ensure_ascii=False)[:500]}")
                except:
                    print(f"Raw: {text[:500]}")
            else:
                # Count meaningful content
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(text, "html.parser")
                ps = soup.find_all("p")
                p_text = sum(len(p.get_text()) for p in ps)
                links = len(soup.find_all("a", href=True))
                print(f"<p> tags: {len(ps)}, total p text: {p_text} chars, links: {links}")
                if ps:
                    for p in ps[:3]:
                        print(f"  <p>: {p.get_text(strip=True)[:120]}")
                elif len(text) < 5000:
                    print(f"Raw HTML: {text[:800]}")
        else:
            print(f"Body: {resp.text[:300]}")
    except Exception as exc:
        print(f"ERROR: {exc}")

print("=" * 70)
print("TASS: trying alternative endpoints")
print("=" * 70)

# 1. Googlebot user-agent (sites often serve SSR to bots)
try_url("TASS article with Googlebot UA",
        f"https://tass.ru/ekonomika/{article_id}",
        {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"})

# 2. Try curl-like minimal request
try_url("TASS article with curl UA",
        f"https://tass.ru/ekonomika/{article_id}",
        {"User-Agent": "curl/8.0"})

# 3. AMP version
try_url("TASS AMP", f"https://tass.ru/ekonomika/{article_id}/amp")

# 4. TASS API endpoints
try_url("TASS API v1 article", f"https://tass.ru/api/v1/article/{article_id}")
try_url("TASS API news", f"https://tass.ru/api/news/{article_id}")
try_url("TASS userApi", f"https://tass.ru/userApi/article/{article_id}")

# 5. Try with Accept: application/json
try_url("TASS article JSON accept",
        f"https://tass.ru/ekonomika/{article_id}",
        {"Accept": "application/json"})

# 6. Disable JS rendering indicator
try_url("TASS with no-js cookie",
        f"https://tass.ru/ekonomika/{article_id}",
        {"Cookie": "js_disabled=1"})

# 7. RSS feed - check what description contains
print("\n--- TASS RSS feed content ---")
try:
    resp = session.get("https://tass.ru/rss/v2.xml", timeout=30)
    print(f"Status: {resp.status_code}, length: {len(resp.text)}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")
    print(f"Items: {len(items)}")
    if items:
        item = items[0]
        print(f"Title: {item.find('title').get_text(strip=True) if item.find('title') else 'N/A'}")
        link = item.find("link")
        print(f"Link tag content: '{link}'" if link else "Link: N/A")
        print(f"Link text: '{link.get_text(strip=True)}'" if link else "")
        print(f"Link string: '{link.string}'" if link and link.string else "")
        if link and link.next_sibling:
            print(f"Link next_sibling: '{str(link.next_sibling).strip()[:100]}'")
        desc = item.find("description")
        print(f"Description: {desc.get_text(strip=True)[:200] if desc else 'N/A'}")
        content = item.find("content:encoded") or item.find("content")
        print(f"Content: {content.get_text(strip=True)[:200] if content else 'N/A'}")
        # Show full item XML
        print(f"Full item XML:\n{str(item)[:800]}")
except Exception as exc:
    print(f"ERROR: {exc}")

print("\n\n" + "=" * 70)
print("GAZETA.RU: trying alternative endpoints")
print("=" * 70)

# 1. Googlebot
try_url("Gazeta.ru with Googlebot UA",
        "https://www.gazeta.ru/",
        {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"})

# 2. RSS attempts
try_url("Gazeta RSS /rss/all.xml", "https://www.gazeta.ru/rss/all.xml")
try_url("Gazeta RSS /export/rss/lenta.xml", "https://www.gazeta.ru/export/rss/lenta.xml")
try_url("Gazeta RSS /export/rss/", "https://www.gazeta.ru/export/rss/")

# 3. API
try_url("Gazeta API", "https://www.gazeta.ru/api/")
try_url("Gazeta API news", "https://api.gazeta.ru/news/")

# 4. last.shtml
try_url("Gazeta last.shtml", "https://www.gazeta.ru/last.shtml")

# 5. An article page with Googlebot
try_url("Gazeta article with Googlebot",
        "https://www.gazeta.ru/politics/",
        {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"})
