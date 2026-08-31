# fxtwitter skill

[日本語版 README はこちら / Japanese README](README.ja.md)

A [Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
that gives Claude complete access to the **FxTwitter (FxEmbed) API v2** — X/Twitter
posts, threads, conversations, profiles, timelines, media, followers, search, typeahead
and trends — with no API key, no OAuth and no login.

It works in Claude.ai on web and mobile, in Claude Code, in Codex, and as a plain CLI,
because the whole thing is one Python file with **zero dependencies** beyond the
standard library.

## Why

X blocks unauthenticated readers, so `curl https://x.com/user/status/123` returns a
login wall instead of a post. FxEmbed solves this for embeds; its public JSON API
solves it for agents. This skill packages that API into something an LLM can use
correctly on the first try: normalised input, cursor pagination, retries, compact
output that does not blow up the context window, and documentation of the parts of the
API that behave surprisingly.

It also triggers during ordinary web research — when a search result turns out to be an
x.com link, when a claim traces back to a post, or when an account is the primary source
— so a login wall never silently truncates an answer.

## Install

**Claude.ai (web / mobile)** — download `fxtwitter.skill` from the
[releases](../../releases) and upload it in Settings → Capabilities → Skills, or open
the `.skill` file in a chat and press **Save skill**.

**Claude Code / Codex / anything with a filesystem** — clone the repo and point your
skills directory at the skill inside it:

```bash
git clone https://github.com/mokouliszt/fxtwitter-skill.git
ln -s "$PWD/fxtwitter-skill/skills/fxtwitter" ~/.claude/skills/fxtwitter
# or, if you prefer a copy over a symlink:
# cp -r fxtwitter-skill/skills/fxtwitter ~/.claude/skills/fxtwitter
```

**Standalone CLI** — no install at all:

```bash
cd skills/fxtwitter
python3 scripts/fxtwitter.py status https://x.com/jack/status/20
```

Requires Python 3.8 or newer. Nothing else.

## Usage

All examples below run from `skills/fxtwitter/`. From the repository root, prefix the
path instead: `python3 skills/fxtwitter/scripts/fxtwitter.py ...`.

```bash
# One post, translated, with the author's account origin
python3 scripts/fxtwitter.py status https://x.com/jack/status/20 --lang ja --about-account

# Unroll a thread into Markdown
python3 scripts/fxtwitter.py thread <url> --format md --full-text --out thread.md

# Top replies
python3 scripts/fxtwitter.py conversation <url> --ranking-mode likes --max-items 30

# An account's last ~200 posts as JSON Lines
python3 scripts/fxtwitter.py statuses NASA --all --max-items 200 --format jsonl

# Poll for new posts (exit code 4 means nothing new)
python3 scripts/fxtwitter.py statuses NASA --since 1767225600

# Download every image and video from a post, full resolution
python3 scripts/fxtwitter.py download <url> --out-dir ./media

# Project just the fields you need
python3 scripts/fxtwitter.py followers NASA --count 100 --select 'results[].screen_name'
```

Input is forgiving. Any of these work as a post reference:

```
20
https://x.com/jack/status/20
https://twitter.com/jack/status/20/photo/1
d.fxtwitter.com/jack/status/20.mp4
https://vxtwitter.com/jack/status/20?s=46&t=abc
```

And any of these as an account reference: `@NASA`, `NASA`, `https://x.com/NASA`,
`id:11348282`.

## Endpoint coverage

Every documented v2 operation, plus the legacy v1 routes and an escape hatch.

| Endpoint | Command |
| --- | --- |
| `GET /2/status/{id}` | `status` |
| `GET /2/status/{id}/reposts` | `reposts` |
| `GET /2/status/{id}/quotes` | `quotes` |
| `GET /2/thread/{id}` | `thread` |
| `GET /2/conversation/{id}` | `conversation` |
| `GET /2/profile/{handle}` | `profile` |
| `GET /2/profile/{handle}/about` | `about` |
| `GET /2/profile/{handle}/statuses` | `statuses` |
| `GET /2/profile/{handle}/articles` | `articles` |
| `GET /2/profile/{handle}/media` | `media` |
| `GET /2/profile/{handle}/followers` | `followers` |
| `GET /2/profile/{handle}/following` | `following` |
| `GET /2/search` | `search` |
| `GET /2/search/users` | `search-users` |
| `GET /2/typeahead` | `typeahead` |
| `GET /2/trends` | `trends` |
| `GET /2/openapi.json` | `spec` |
| `GET /status/{id}`, `/{handle}/status/{id}[/{lang}]`, `/{handle}` (v1) | `v1` |
| anything else | `get <path> --param k=v` |

## Output formats

| Format | Use |
| --- | --- |
| `summary` (default) | compact plain text, roughly a tenth the size of the JSON |
| `json` / `--raw` | full payload |
| `jsonl` | one JSON object per post |
| `md` | Markdown for reports |
| `urls`, `media-urls` | links only |
| `--select 'results[].id'` | project specific fields |

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | network or runtime failure |
| 2 | bad arguments |
| 3 | the API answered with a non-2xx `code` |
| 4 | HTTP 204 — `statuses --since` found nothing newer |

## Configuration

| Variable | Default |
| --- | --- |
| `FXTWITTER_API_BASE` | `https://api.fxtwitter.com` |
| `FXTWITTER_USER_AGENT` | `fxtwitter-skill/<version>` |
| `FXTWITTER_TIMEOUT` | `30` |
| `FXTWITTER_FORMAT` | `summary` |

Point `FXTWITTER_API_BASE` at a self-hosted FxEmbed instance, or at
`https://api.fxbsky.app` for Bluesky — the response shapes are aligned.

## Known upstream behaviour

- **A `User-Agent` header is required.** The API answers `401` without one. The client
  always sends one.
- **`search`, `search-users` and `quotes` are unreliable on the public instance.** They
  run through X's search backend, which often refuses the shared guest session and
  returns `code: 404` with an empty `results` array. Use `statuses` instead of
  `from:` searches and `typeahead` instead of `search-users`; self-hosting with
  credentials restores them. The client retries empty responses twice by default.
- **`count` is a hint.** Upstream picks the real page size. Use `--max-items`.
- **Deleted, private and suspended posts** return a `tombstone` object rather than an
  error.
- Rate limit: 1000 requests per minute per IP.

## Repository layout

The skill lives under `skills/` so the repository can hold more than one later, and
so it maps directly onto the Claude Code plugin convention (`skills/<name>/SKILL.md`).
Everything the packaged `.skill` needs sits inside `skills/fxtwitter/`.

```
README.md, README.ja.md, LICENSE     repository-level docs and licence
skills/
  fxtwitter/
    SKILL.md                     instructions Claude loads when the skill triggers
    LICENSE                      copy, so the packaged .skill stays self-contained
    scripts/fxtwitter.py         the CLI (stdlib only)
    scripts/smoke_test.py        live check that the API and client still agree
    references/endpoints.md      every endpoint, parameter, default and limit
    references/schemas.md        every response object, field by field
    references/recipes.md        workflows, search operators, troubleshooting
    references/url-modifiers.md  the embed-side d./g./m./t./i./o. flags
```

Paths inside `SKILL.md` are relative to the skill directory, so they are unaffected by
where the repository is checked out.

## Testing

```bash
cd skills/fxtwitter
python3 scripts/smoke_test.py            # hits the live API, ~15 requests
python3 scripts/smoke_test.py --offline  # parsing and formatting only
```

## Packaging

```bash
python3 -m scripts.package_skill skills/fxtwitter dist/
```

using the packager from Anthropic's `skill-creator`, or simply zip
`skills/fxtwitter` with `fxtwitter/` as the archive's top-level directory and rename
the result to `fxtwitter.skill`.

## License

MIT — see [LICENSE](LICENSE).

This is an independent client. It is not affiliated with, endorsed by, or maintained
by the FxEmbed project, X Corp. or Anthropic. [FxEmbed](https://github.com/FxEmbed/FxEmbed)
is a separate MIT-licensed project; please respect its
[rate limits](https://docs.fxembed.com/api/introduction/) and consider self-hosting for
heavy use. Data returned by the API is public information about real people — use it
accordingly.
