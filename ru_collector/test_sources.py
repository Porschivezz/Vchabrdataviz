#!/usr/bin/env python3
"""Test script: run each scraper and print stats.

Usage:
    python -m ru_collector.test_sources              # test all
    python -m ru_collector.test_sources tass ria      # test specific sources
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

from ru_collector.scrapers.sources import ALL_SOURCES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

def main():
    since = datetime.now(timezone.utc) - timedelta(hours=48)
    sources_to_test = sys.argv[1:] if len(sys.argv) > 1 else list(ALL_SOURCES.keys())

    results = []
    for name in sources_to_test:
        if name not in ALL_SOURCES:
            print(f"Unknown source: {name}")
            continue

        print(f"\n{'=' * 70}")
        print(f"Testing: {name}")
        print(f"{'=' * 70}")

        try:
            scraper = ALL_SOURCES[name]()
            articles = scraper.fetch_articles(since=since)

            total = len(articles)
            full = sum(1 for a in articles if len(a.raw_text) > 300)
            lengths = [len(a.raw_text) for a in articles]
            avg_len = int(sum(lengths) / len(lengths)) if lengths else 0
            max_len = max(lengths) if lengths else 0
            min_len = min(lengths) if lengths else 0

            print(f"  Total articles: {total}")
            print(f"  Full text (>300 chars): {full}/{total}")
            print(f"  Text lengths: min={min_len}, avg={avg_len}, max={max_len}")

            if articles:
                a = articles[0]
                print(f"  Sample: {a.title[:70]}")
                print(f"  Sample link: {a.link}")
                print(f"  Sample text ({len(a.raw_text)} chars): {a.raw_text[:100]}...")

            # Show a short-text example if any
            short = [a for a in articles if len(a.raw_text) <= 300]
            if short:
                s = short[0]
                print(f"  Short example: {s.title[:60]} ({len(s.raw_text)} chars)")
                print(f"    Link: {s.link}")

            status = "OK" if total > 0 and full / max(total, 1) > 0.5 else "NEEDS_FIX"
            results.append((name, total, full, avg_len, status))

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((name, 0, 0, 0, "ERROR"))

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Source':<16} {'Total':>5} {'Full':>5} {'AvgLen':>8} Status")
    print("-" * 55)
    for name, total, full, avg_len, status in results:
        marker = "[OK]" if status == "OK" else "[!!]"
        print(f"{marker} {name:<14} {total:>5} {full:>5} {avg_len:>8} {status}")

    ok_count = sum(1 for *_, s in results if s == "OK")
    print(f"\nResult: {ok_count}/{len(results)} sources OK, {len(results) - ok_count} need attention")


if __name__ == "__main__":
    main()
