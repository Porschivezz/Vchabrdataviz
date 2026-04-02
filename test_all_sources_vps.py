#!/usr/bin/env python3
"""Run on VPS: test all 17 news scrapers via proxy.

Usage:
  # Make sure .env has SCRAPER_PROXY_URL set, then:
  docker compose exec app python test_all_sources_vps.py

  # Or run directly:
  SCRAPER_PROXY_URL="http://user:pass@host:port" python test_all_sources_vps.py

  # Test a single source:
  docker compose exec app python test_all_sources_vps.py tass
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__) or ".")

from datetime import datetime, timedelta, timezone
from src.scrapers.news_sources import NEWS_SOURCES

# Filter by source name if provided as arg
filter_name = sys.argv[1] if len(sys.argv) > 1 else None

now = datetime.now(timezone.utc)
since = now - timedelta(days=2)

results = []

sources_to_test = NEWS_SOURCES
if filter_name:
    sources_to_test = [s for s in NEWS_SOURCES if s["name"] == filter_name]
    if not sources_to_test:
        print(f"Source '{filter_name}' not found. Available: {[s['name'] for s in NEWS_SOURCES]}")
        sys.exit(1)

for src_cfg in sources_to_test:
    name = src_cfg["name"]
    cls = src_cfg["scraper_class"]
    print(f"\n{'='*70}")
    print(f"Testing: {name} ({src_cfg['description']})")
    print(f"{'='*70}")

    try:
        scraper = cls()
        has_proxy = bool(getattr(scraper, 'session', None) and scraper.session.proxies)
        print(f"  Proxy: {has_proxy}")

        # Show feed URLs if available
        if hasattr(scraper, 'feed_urls'):
            print(f"  Feed URLs: {scraper.feed_urls}")

        articles = scraper.fetch_articles(since=since, until=now)

        if not articles:
            print(f"  WARNING: 0 articles collected!")
            results.append((name, 0, 0, 0, "NO ARTICLES"))
            continue

        total = len(articles)
        full_text_count = sum(1 for a in articles if len(a.raw_text) > 300)
        avg_len = sum(len(a.raw_text) for a in articles) // total
        max_len = max(len(a.raw_text) for a in articles)
        min_len = min(len(a.raw_text) for a in articles)

        sample = articles[0]
        print(f"  Total articles: {total}")
        print(f"  Full text (>300 chars): {full_text_count}/{total}")
        print(f"  Text lengths: min={min_len}, avg={avg_len}, max={max_len}")
        print(f"  Sample: {sample.title[:70]}")
        print(f"  Sample link: {sample.link}")
        print(f"  Sample text ({len(sample.raw_text)} chars):")
        print(f"    {sample.raw_text[:300]}...")

        # Show short articles for debugging
        short = [a for a in articles if len(a.raw_text) <= 300]
        if short:
            s = short[0]
            print(f"  Short example: {s.title[:60]} ({len(s.raw_text)} chars)")
            print(f"    Link: {s.link}")
            print(f"    Text: {s.raw_text[:200]}")

        status = "OK" if full_text_count >= total * 0.5 else "NEEDS_FIX"
        results.append((name, total, full_text_count, avg_len, status))

    except Exception as exc:
        import traceback
        traceback.print_exc()
        results.append((name, 0, 0, 0, f"ERROR: {str(exc)[:50]}"))

print(f"\n\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
print(f"{'Source':<15} {'Total':>6} {'Full':>6} {'AvgLen':>8} {'Status'}")
print("-" * 55)
for name, total, full, avg, status in results:
    mark = "OK" if status == "OK" else "!!"
    print(f"[{mark}] {name:<13} {total:>6} {full:>6} {avg:>8} {status}")

ok_count = sum(1 for r in results if r[4] == "OK")
fail_count = len(results) - ok_count
print(f"\nResult: {ok_count}/{len(results)} sources OK, {fail_count} need attention")
