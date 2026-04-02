#!/usr/bin/env python3
"""Run on VPS: test all 17 news scrapers via proxy.

Usage:
  # Make sure .env has SCRAPER_PROXY_URL set, then:
  docker compose exec app python test_all_sources_vps.py

  # Or run directly (needs deps installed):
  SCRAPER_PROXY_URL="http://user:pass@host:port" python test_all_sources_vps.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__) or ".")

from datetime import datetime, timedelta, timezone
from src.scrapers.news_sources import NEWS_SOURCES

now = datetime.now(timezone.utc)
since = now - timedelta(days=2)

results = []

for src_cfg in NEWS_SOURCES:
    name = src_cfg["name"]
    cls = src_cfg["scraper_class"]
    print(f"\n{'='*70}")
    print(f"Testing: {name} ({src_cfg['description']})")
    print(f"{'='*70}")

    try:
        scraper = cls()
        has_proxy = bool(scraper.session.proxies)
        print(f"  Proxy: {has_proxy}")

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
