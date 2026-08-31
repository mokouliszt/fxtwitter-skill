#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 mokouliszt
"""
Smoke test for the fxtwitter client.

    python3 scripts/smoke_test.py            # live: ~10 requests against the API
    python3 scripts/smoke_test.py --offline  # parsing and formatting only, no network

Live failures are not always bugs here: the search-backed endpoints
(`/2/search`, `/2/search/users`, `/2/status/{id}/quotes`) frequently return an
empty result set from the public instance, so they are reported as warnings
rather than failures.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fxtwitter  # noqa: E402

# jack's first post: the oldest stable public status on the platform.
SAMPLE_ID = "20"
SAMPLE_HANDLE = "jack"

passed: list = []
failed: list = []
warned: list = []


def check(name: str, condition: bool, detail: str = "", soft: bool = False) -> None:
    if condition:
        passed.append(name)
        print(f"  ok    {name}")
    elif soft:
        warned.append((name, detail))
        print(f"  warn  {name} {detail}")
    else:
        failed.append((name, detail))
        print(f"  FAIL  {name} {detail}")


def test_parsing() -> None:
    print("parsing")
    cases = {
        "20": "20",
        "https://x.com/jack/status/20": "20",
        "https://twitter.com/jack/status/20/photo/1": "20",
        "d.fxtwitter.com/jack/status/20.mp4": "20",
        "https://vxtwitter.com/jack/status/20?s=46&t=abc": "20",
        "https://fixupx.com/jack/status/20/ja": "20",
    }
    for raw, expected in cases.items():
        try:
            got = fxtwitter.parse_status_id(raw)
        except fxtwitter.FxError as exc:
            got = f"error: {exc}"
        check(f"parse_status_id({raw!r})", got == expected, f"got {got!r}")

    handles = {
        "@NASA": "NASA",
        "NASA": "NASA",
        "https://x.com/NASA": "NASA",
        "id:11348282": "id:11348282",
        "11348282": "id:11348282",
    }
    for raw, expected in handles.items():
        try:
            got = fxtwitter.parse_handle(raw)
        except fxtwitter.FxError as exc:
            got = f"error: {exc}"
        check(f"parse_handle({raw!r})", got == expected, f"got {got!r}")

    for bad in ("", "not a url", "this-handle-is-far-too-long"):
        try:
            fxtwitter.parse_status_id(bad)
            ok = False
        except fxtwitter.FxError:
            ok = True
        check(f"parse_status_id rejects {bad!r}", ok)


def test_formatting() -> None:
    print("formatting")
    payload = {
        "code": 200,
        "status": {
            "type": "status", "id": "1", "url": "https://x.com/a/status/1",
            "text": "hello", "created_timestamp": 0, "likes": 1, "reposts": 2,
            "replies": 3, "quotes": 4, "lang": "en", "source": "test",
            "author": {"type": "profile", "screen_name": "a", "name": "A"},
            "media": {"photos": [{"type": "photo", "url": "https://p/1.jpg",
                                  "width": 1, "height": 1, "altText": "alt"}]},
            "quote": {"type": "tombstone", "reason": "deleted", "message": "gone"},
        },
        "thread": [],
        "author": {"type": "profile", "screen_name": "a", "name": "A"},
    }
    summary = fxtwitter.format_summary(payload, 600)
    check("summary renders text", "hello" in summary)
    check("summary renders counts", "likes=1" in summary and "reposts=2" in summary)
    check("summary renders media", "https://p/1.jpg" in summary)
    check("summary renders tombstone", "tombstone" in summary and "deleted" in summary)

    markdown = fxtwitter.format_markdown(payload, 600)
    check("markdown renders quote block", "> hello" in markdown)

    urls = fxtwitter.format_urls(payload)
    check("urls extracts permalink", urls.strip() == "https://x.com/a/status/1")

    media = fxtwitter.media_urls(payload)
    check("media_urls names files", media == [("https://p/1.jpg", "1_photo1.jpg")], f"got {media}")

    check("select scalar", fxtwitter.select_paths(payload, ["status.author.screen_name"]) == "a")
    check("select array walk",
          fxtwitter.select_paths({"results": [{"id": "1"}, {"id": "2"}]}, ["results[].id"]) == ["1", "2"])

    # v1 payloads use `retweets` and carry no `type` discriminator.
    v1 = {"code": 200, "tweet": {"id": "1", "url": "u", "text": "t", "retweets": 9,
                                 "created_timestamp": 0,
                                 "author": {"screen_name": "a", "name": "A"}, "media": {}}}
    check("v1 reposts fallback", "reposts=9" in fxtwitter.format_summary(v1, 600))
    check("v1 collected as status", len(fxtwitter.collect_statuses(v1)) == 1)


def test_live() -> None:
    print("live API")
    client = fxtwitter.FxClient(verbose=False)

    status, payload = client.get(f"/2/status/{SAMPLE_ID}")
    check("GET /2/status/{id}", status == 200 and (payload or {}).get("code") == 200)
    focal = (payload or {}).get("status") or {}
    check("status has text", bool(focal.get("text")))
    check("status has author", bool((focal.get("author") or {}).get("screen_name")))

    _, translated = client.get(f"/2/status/{SAMPLE_ID}", {"lang": "ja"})
    translation = ((translated or {}).get("status") or {}).get("translation") or {}
    check("lang= returns a translation", bool(translation.get("text")), soft=True)

    _, thread = client.get(f"/2/thread/{SAMPLE_ID}")
    check("GET /2/thread/{id}", isinstance((thread or {}).get("thread"), list))

    _, conversation = client.get(f"/2/conversation/{SAMPLE_ID}", {"ranking_mode": "likes"})
    check("GET /2/conversation/{id}", isinstance((conversation or {}).get("replies"), list))

    _, profile = client.get(f"/2/profile/{SAMPLE_HANDLE}")
    check("GET /2/profile/{handle}", bool((profile or {}).get("user")))

    _, about = client.get(f"/2/profile/{SAMPLE_HANDLE}/about")
    check("GET /2/profile/{handle}/about", (about or {}).get("code") == 200, soft=True)

    timeline = client.paginate(f"/2/profile/{SAMPLE_HANDLE}/statuses", {"count": 5}, pages=1)
    check("GET /2/profile/{handle}/statuses", bool(timeline.get("results")), soft=True)
    cursor = timeline.get("cursor") or {}
    check("timeline returns a cursor", bool(cursor.get("bottom")), soft=True)

    _, reposts = client.get(f"/2/status/{SAMPLE_ID}/reposts", {"count": 3})
    check("GET /2/status/{id}/reposts", bool((reposts or {}).get("results")), soft=True)

    _, typeahead = client.get("/2/typeahead", {"q": "nasa"})
    check("GET /2/typeahead", bool((typeahead or {}).get("users")), soft=True)

    _, trends = client.get("/2/trends", {"count": 5})
    check("GET /2/trends", isinstance((trends or {}).get("trends"), list))

    _, search = client.get("/2/search", {"q": "hello", "count": 3})
    check("GET /2/search (known flaky upstream)", bool((search or {}).get("results")),
          "empty results - upstream search refused the guest session", soft=True)

    _, missing = client.get("/2/profile/zzzzqqqqxxxx999")
    check("missing user reports 404 in body", (missing or {}).get("code") == 404)

    _, spec = client.get("/2/openapi.json")
    paths = (spec or {}).get("paths") or {}
    check("spec still lists 16 v2 paths", len(paths) == 16, f"got {len(paths)}")
    documented = set(paths)
    expected = {
        "/2/status/{id}", "/2/status/{id}/reposts", "/2/status/{id}/quotes",
        "/2/thread/{id}", "/2/conversation/{id}", "/2/profile/{handle}",
        "/2/profile/{handle}/about", "/2/profile/{handle}/statuses",
        "/2/profile/{handle}/articles", "/2/profile/{handle}/media",
        "/2/profile/{handle}/followers", "/2/profile/{handle}/following",
        "/2/search", "/2/search/users", "/2/typeahead", "/2/trends",
    }
    check("no undocumented endpoints appeared", documented == expected,
          f"missing={expected - documented} new={documented - expected}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip the live API checks")
    args = parser.parse_args()

    test_parsing()
    test_formatting()
    if not args.offline:
        test_live()

    print()
    print(f"{len(passed)} passed, {len(warned)} warned, {len(failed)} failed")
    for name, detail in warned:
        print(f"  warn: {name} {detail}")
    for name, detail in failed:
        print(f"  fail: {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
