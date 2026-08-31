# Recipes and troubleshooting

Practical patterns for the CLI in `scripts/fxtwitter.py`. Endpoint parameters live
in `endpoints.md`; response fields in `schemas.md`.

## Contents

- [Reading a link someone shared](#reading-a-link-someone-shared)
- [Unrolling threads and conversations](#unrolling-threads-and-conversations)
- [Timelines, monitoring and archiving](#timelines-monitoring-and-archiving)
- [Media](#media)
- [Search operators](#search-operators)
- [When search returns nothing](#when-search-returns-nothing)
- [Pagination patterns](#pagination-patterns)
- [Projecting fields to save context](#projecting-fields-to-save-context)
- [Self-hosting and other hosts](#self-hosting-and-other-hosts)
- [Troubleshooting](#troubleshooting)

## Reading a link someone shared

```bash
python3 scripts/fxtwitter.py status "https://x.com/user/status/123?s=46&t=abc"
```

Query strings, `/photo/2` and `.mp4` suffixes, and subdomain flags are all stripped
automatically. Add `--lang ja` for a translation, `--about-account` for the author's
account origin.

If the post is a reply and the context matters, use `thread` instead - it returns
the author's whole chain in one call. If the user asked what people said back, use
`conversation`.

## Unrolling threads and conversations

```bash
# The author's own chain, as Markdown, untruncated
python3 scripts/fxtwitter.py thread <url> --format md --full-text --out thread.md

# Top 50 replies from other people
python3 scripts/fxtwitter.py conversation <url> --ranking-mode likes --max-items 50

# Chronological replies instead
python3 scripts/fxtwitter.py conversation <url> --ranking-mode recency --pages 3
```

`conversation` walks to the root of the conversation, so passing any post in a
thread gets you the whole thing. Replies paginate under `replies`, and the client
merges pages for you.

## Timelines, monitoring and archiving

```bash
# Recent posts, compact
python3 scripts/fxtwitter.py statuses NASA --count 40

# Including their replies to other people
python3 scripts/fxtwitter.py statuses NASA --with-replies

# Self-reply chains grouped into single entries
python3 scripts/fxtwitter.py statuses NASA --group-threads

# Roughly the last 200 posts as one JSON object per post
python3 scripts/fxtwitter.py statuses NASA --all --max-items 200 --format jsonl --out feed.jsonl
```

**Polling for new posts.** `--since` takes Unix seconds (or milliseconds if the
value is at least 1e12) and exits with code `4` and no output when nothing is
newer, which makes a cron-style loop trivial:

```bash
LAST=$(date -d '1 hour ago' +%s)
python3 scripts/fxtwitter.py statuses NASA --since "$LAST" --format jsonl
case $? in
  0) echo "new posts above" ;;
  4) echo "nothing new" ;;
  *) echo "error" >&2 ;;
esac
```

`--since` only short-circuits when `--cursor` is not also set.

## Media

```bash
# List what a post carries, without downloading
python3 scripts/fxtwitter.py status <url> --format media-urls

# Download everything at full resolution
python3 scripts/fxtwitter.py download <url> --out-dir ./media

# Only the video, only the highest-bitrate variant (default)
python3 scripts/fxtwitter.py download <url> --media-kind videos

# Pull media from a whole account timeline
python3 scripts/fxtwitter.py download NASA --from-timeline --pages 3 --out-dir ./nasa
```

Notes:

- Photo URLs already carry `?name=orig`, so they are the original upload.
- Videos expose several `formats`; the client picks the highest `bitrate` unless
  `--no-best-variant` is passed. An `m3u8` entry is a streaming playlist, not a
  file - skip it if you need a single download.
- `altText` on photos is the author's own alt text. Prefer quoting it over
  describing an image yourself.
- `--dry-run` prints URL to destination pairs so you can confirm before writing.

## Search operators

`q` accepts X's search syntax (max 512 characters). The ones that matter most:

| Operator | Effect |
| --- | --- |
| `from:handle` / `to:handle` | authored by / replying to |
| `"exact phrase"` | phrase match |
| `-term` | exclude |
| `OR` | disjunction (uppercase) |
| `#hashtag` / `$cashtag` | tag match |
| `url:example.com` | posts linking to a domain |
| `since:2026-01-01` / `until:2026-02-01` | date range |
| `min_faves:100` / `min_retweets:50` / `min_replies:10` | engagement floors |
| `filter:media` / `filter:images` / `filter:videos` / `filter:links` | attachment kind |
| `filter:replies` / `-filter:replies` | include or drop replies |
| `lang:ja` | language |
| `conversation_id:123` | everything in one conversation |
| `quoted_tweet_id:123` | quotes of a post (this is what `quotes` uses internally) |

`--feed top` ranks by engagement, `--feed latest` by time, `--feed media` restricts
to posts with attachments.

## When search returns nothing

`search`, `search-users` and `quotes` all go through X's search backend, which
frequently refuses the public instance's guest session. The symptom is `code: 404`
with `results: []` on an otherwise healthy API. The client already retries twice
(`--retry-empty`, default 2).

Fallbacks, in order of preference:

1. **Posts by a specific account** - use `statuses <handle>` rather than
   `search "from:handle"`. It uses a different backend and is reliable.
2. **Finding an account by name** - use `typeahead "<name>"`, which is reliable and
   returns handles, display names and verification status. Then feed the handle to
   `profile` or `statuses`.
3. **Filtering a known timeline locally** - pull `statuses --all --max-items N
   --format jsonl` and grep, instead of asking the search backend to filter.
4. **Quotes of a post** - no reliable substitute; report it as unavailable.
5. **Self-hosting** with credentials configured restores the search endpoints.

Be explicit about which of these happened. "Search is currently unavailable on the
public FxTwitter instance" is a different statement from "no posts matched", and
conflating them produces a wrong answer.

## Pagination patterns

```bash
# One page, note the cursor
python3 scripts/fxtwitter.py followers NASA --count 100

# Three pages merged
python3 scripts/fxtwitter.py followers NASA --pages 3

# Drain the timeline, but stop at 500 accounts
python3 scripts/fxtwitter.py followers NASA --all --max-items 500

# Resume from a cursor you saved earlier
python3 scripts/fxtwitter.py followers NASA --cursor 'DAABCgABHQ...'
```

`--count` is a hint. Upstream decides the real page size and often returns 20 items
for `--count 2`. Control volume with `--max-items`, not `--count`.

`--all` is `--pages 1000` with a safety net; always pair it with `--max-items`.
Between pages the client sleeps `--sleep` seconds (default 0.2) to stay well inside
the 1000 requests/minute limit.

## Projecting fields to save context

Full payloads are large - a single status with media can exceed 8 KB of JSON.
Project instead of dumping:

```bash
# Just the IDs
python3 scripts/fxtwitter.py statuses NASA --select 'results[].id' --compact

# Handle and follower count for a list of accounts
python3 scripts/fxtwitter.py followers NASA --count 100 \
  --select 'results[].screen_name' --select 'results[].followers'

# One scalar
python3 scripts/fxtwitter.py profile jack --select user.followers
```

`[]` maps over an array; plain dots walk objects. One `--select` prints the bare
value, several print an object keyed by path.

For reading rather than processing, the default `summary` format is already an
order of magnitude smaller than the JSON and keeps every field that matters.

## Self-hosting and other hosts

```bash
export FXTWITTER_API_BASE=https://api.example.workers.dev
python3 scripts/fxtwitter.py status 20

# FxBluesky shares the response shapes
python3 scripts/fxtwitter.py --help  # then:
python3 scripts/fxtwitter.py profile someone.bsky.social --base-url https://api.fxbsky.app
```

FxEmbed runs on Cloudflare Workers and needs no database or X API key. A
self-hosted instance with credentials configured restores the search endpoints and
removes the shared rate limit. See the FxEmbed deployment docs.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `401` with an empty body | No `User-Agent`. The script always sends one; a hand-rolled `curl` must too. |
| `code: 400` `tweet ID must be a numeric snowflake` | The ID was not extracted from the URL. Pass the bare snowflake. |
| `code: 404` `User not found` | Wrong handle, or the account was renamed. Try `typeahead` to find the current handle. |
| `code: 404` with `reason: suspended` | Account suspended; nothing to fetch. |
| `code: 401` on a status | Protected account or the post requires login. |
| Empty `results` from `search` / `quotes` | Upstream search refusal - see the section above. |
| Empty `trends` on HTTP 200 | Transient; the client retries twice automatically. |
| Post text is truncated with `[+N chars]` | Summary truncation at 600 chars. Use `--full-text`. |
| A thread entry has no `text` | It is a tombstone; read `reason`. |
| `views` is null | X does not expose view counts on older posts. Report as unavailable. |
| Timeline of a protected account is empty | `protected: true` on the profile - unauthenticated reads cannot see it. |
| Rate limited (`429`) | 1000 req/min per IP. The client backs off and retries; lower `--pages` or raise `--sleep`. |
| Fields differ from this doc | Compare with the live spec: `python3 scripts/fxtwitter.py spec --raw > openapi.json`. |
