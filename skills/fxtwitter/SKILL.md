---
name: fxtwitter
description: Fetch X/Twitter data through the FxTwitter (FxEmbed) v2 JSON API - posts, unrolled threads, full reply conversations, user profiles, timelines, media, followers and following, quotes, reposts, search, typeahead and trends - with no API key and no login. Use this skill whenever the user shares an x.com, twitter.com, fxtwitter.com, fixupx.com or vxtwitter.com link, asks what a post or thread says, wants a post's replies, media, engagement stats, translation or author profile, wants to download a post's images or video, wants to monitor an account's timeline, or mentions fxtwitter, fixupx, vxtwitter or FxEmbed. Also use it during web research whenever search results include an x.com link, a claim traces back to a post, or an account is the primary source, such as breaking news, official announcements or researcher commentary. A plain web fetch of an x.com URL returns a login wall or empty text, but this API does not.
license: MIT
---

# FxTwitter API v2

FxTwitter (part of the FxEmbed project) exposes X/Twitter data as plain JSON with
no API key, no OAuth and no login. This skill wraps the entire v2 surface in one
dependency-free Python CLI.

## Setup

`scripts/fxtwitter.py` needs only the Python 3.8+ standard library, so it runs as-is
in the Claude sandbox, Claude Code, Codex or any shell. No install step.

```bash
python3 scripts/fxtwitter.py --help
```

If a `bash`-style tool is unavailable and only a web-fetch tool exists, request
`https://api.fxtwitter.com/2/status/<id>` directly - the JSON is the same. The
script is preferred because it normalises input, paginates, retries, and prints a
compact form instead of dumping tens of kilobytes of JSON into context.

## Pick the command from what was asked

| The user wants | Command |
| --- | --- |
| What does this post say / its stats / its media | `status <id-or-url>` |
| The whole thread the author wrote | `thread <id-or-url>` |
| The thread plus what other people replied | `conversation <id-or-url>` |
| Who reposted it | `reposts <id-or-url>` |
| Who quote-tweeted it | `quotes <id-or-url>` |
| Who is this account | `profile <handle>` |
| Where is this account based / username history | `about <handle>` |
| This account's recent posts | `statuses <handle>` |
| Only posts with images or video | `media <handle>` |
| Their long-form articles | `articles <handle>` |
| Their followers / who they follow | `followers <handle>` / `following <handle>` |
| Find posts matching a query | `search "<query>"` |
| Find accounts by name | `search-users "<query>"` or `typeahead "<query>"` |
| What is trending right now | `trends` |
| Save the images or video to disk | `download <id-or-url>` |
| Anything not covered above | `get <path> --param k=v` |

Input is forgiving: `status` accepts a bare snowflake ID or any permalink
(`x.com`, `twitter.com`, `fxtwitter.com`, `fixupx.com`, `vxtwitter.com`, `d.`/`g.`/`m.`
subdomain flags, `/photo/2` suffixes, `.mp4` suffixes, query strings). Profile
commands accept `@name`, `name`, a profile URL, or `id:783214` for a numeric ID.

## Using this during web research

X posts are frequently the primary source, and a plain web fetch of an `x.com` URL
returns a login wall rather than the post. When a research task touches X, route it
through this skill instead of giving up on the link or paraphrasing from a
second-hand article.

Reach for it when:

- **A search result is an x.com link.** Fetch it with `status`, or `thread` when the
  result is part of a chain. Quote the post itself rather than a news site's
  summary of it.
- **A claim traces back to a post.** Articles routinely paraphrase, crop or
  misattribute. Retrieve the original and check `replying_to` and `quote` - a reply
  or a quote-tweet read without its parent is the most common way a quotation ends
  up wrong.
- **An account is the source of record.** Agencies, companies, maintainers and
  researchers announce on X first. `statuses <handle>` reads their recent posts
  reliably; `typeahead "<name>"` finds the handle when you only know the name.
- **The question is about something happening now.** `trends` shows what X is
  surfacing; a named account's timeline beats a news aggregator for freshness.

Do not reach for it when X has nothing to do with the question. A skill that fires
on every research task wastes requests and clutters the answer.

Practical notes for research use:

- **Do not plan around `search`.** Topic-level search is the unreliable part of this
  API (see below). Build the plan on specific URLs and specific accounts, which are
  reliable, and treat search as a bonus.
- **Cite the post, not the skill.** Give the `url` and the date. `created_timestamp`
  is Unix seconds, so it converts cleanly.
- **Engagement is not evidence.** A post with 50,000 likes is popular, not correct.
  Report counts as reach, never as corroboration.
- **Check who is speaking.** `author.verification` and `about_account` help, but X's
  verification is purchasable and `about_account` is X's own inference. Weigh a
  claim by the account's actual standing on the topic, not by a badge.
- **One post is one source.** Treat it the way you would treat a single quote:
  attribute it, and corroborate before presenting it as fact.

## Reading the output

The default `summary` format is compact plain text designed to be read directly.
Prefer it. Reach for other formats only when the task needs them:

- `--format json` (or `--raw`) - full payload, for programmatic follow-up work
- `--format jsonl` - one JSON object per post, good for piping into scripts
- `--format md` - Markdown for a report or notes
- `--format urls` / `--format media-urls` - just the links
- `--select 'results[].id' --select status.author.followers` - project specific
  fields; `[]` walks an array. Cheaper than dumping the whole payload.
- `--text-limit N` caps post text (default 600 chars); `--full-text` disables it.

Pagination: list commands return one page plus a cursor. Use `--pages N` to follow
the cursor automatically, `--all --max-items N` to drain it with a safety stop, or
pass `--cursor` yourself to resume. `--count` is a hint only - the upstream
timeline decides the real page size and often returns more than asked.

Exit codes let you branch without parsing text: `0` success, `1` network or runtime
failure, `2` bad arguments, `3` the API answered with a non-2xx `code`, `4` HTTP 204
(only from `statuses --since`, meaning nothing newer).

## Things that will otherwise waste your time

**A User-Agent is mandatory.** The API answers `401` to requests without one. The
script always sends one; if you hand-roll a request with `curl` or a fetch tool,
set `-H 'User-Agent: ...'`.

**`code` is inside the body.** Every response carries a `code` field mirroring the
HTTP status, so check it even on HTTP 200.

**The search-backed endpoints are unreliable on the public instance.** `search`,
`search-users` and `quotes` all run through X's search backend, which frequently
refuses the guest session and returns `code: 404` with an empty `results` array.
This is upstream behaviour, not a bug in the request. When it happens:

- for "posts by @user", use `statuses <handle>` instead of `search "from:user"`
- for finding an account, use `typeahead "<name>"`, which uses a different backend
  and is reliable
- say plainly that search is unavailable rather than reporting "no results found",
  because an empty result here does not mean the query matched nothing
- a self-hosted instance with credentials configured restores these endpoints

Transient empty responses also affect `trends` occasionally. The script already
re-requests twice on an empty list (`--retry-empty`, default 2).

**Deleted, private and suspended posts** come back as a `tombstone` object with a
`reason` rather than an error. Quoted posts and thread entries can each be
tombstones while the rest of the payload is fine.

**Rate limit** is 1000 requests per minute per IP - generous, but `--all` on a large
follower list will burn through it. Keep `--max-items` set.

**Do not invent data.** If a field is absent (X hides `views` on old posts, for
example) report it as unavailable rather than estimating.

## Common flows

```bash
# What does this link say, in Japanese, with the author's account origin
python3 scripts/fxtwitter.py status https://x.com/jack/status/20 --lang ja --about-account

# Unroll a long thread into Markdown for a report
python3 scripts/fxtwitter.py thread <url> --format md --full-text --out thread.md

# Top replies to a post
python3 scripts/fxtwitter.py conversation <url> --ranking-mode likes --max-items 30

# Last ~100 posts from an account, links only
python3 scripts/fxtwitter.py statuses NASA --all --max-items 100 --format urls

# Poll an account for new posts since a timestamp (exit code 4 = nothing new)
python3 scripts/fxtwitter.py statuses NASA --since 1767225600 --format jsonl

# Grab every image and video from a post at full resolution
python3 scripts/fxtwitter.py download <url> --out-dir ./media

# Point at a self-hosted instance or at FxBluesky (same response shapes)
python3 scripts/fxtwitter.py status <id> --base-url https://api.fxbsky.app
```

Environment variables `FXTWITTER_API_BASE`, `FXTWITTER_USER_AGENT`,
`FXTWITTER_TIMEOUT` and `FXTWITTER_FORMAT` set the defaults for all of the above.

## Reference files

Read these when the task goes past the table above:

- `references/endpoints.md` - every v2 endpoint with all parameters, defaults,
  limits and response envelopes, plus the legacy v1 routes
- `references/schemas.md` - full field list for every response object (status,
  user, media, poll, article, community note, tombstone, cursor)
- `references/recipes.md` - X search operator syntax, pagination and monitoring
  patterns, media variant selection, troubleshooting
- `references/url-modifiers.md` - the embed-side subdomain flags (`d.`, `g.`,
  `m.`, `t.`, `i.`, `o.`) and URL suffixes, for when the user wants a link that
  renders well rather than JSON

Verify against the live spec when something looks off:
`python3 scripts/fxtwitter.py spec --select 'paths' --compact`

## Privacy and courtesy

This API reads public data only; it cannot see protected accounts, DMs or anything
behind a login. Treat what it returns as personal data about real people: use it
for the task at hand, do not compile profiles of private individuals, and do not
use follower or timeline dumps to build surveillance or harassment tooling.
