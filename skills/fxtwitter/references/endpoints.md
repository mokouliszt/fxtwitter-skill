# FxTwitter API v2 - complete endpoint reference

Base URL: `https://api.fxtwitter.com`
Spec: `GET /2/openapi.json` (OpenAPI 3.0.0, `info.version` 2.0.0)
Auth: none. A non-empty `User-Agent` request header is **required**; without it the
API answers `401`.
Rate limit: 1000 requests / minute / IP.
Every response is `application/json` and carries a `code` field mirroring the HTTP
status, so error handling can read the body alone.

FxBluesky (`https://api.fxbsky.app`) exposes an aligned subset with the same
response shapes; pass `--base-url` to reuse this client against it.

## Contents

- [Shared conventions](#shared-conventions)
- [Posts](#posts) - `/2/status/{id}`, `/2/status/{id}/reposts`, `/2/status/{id}/quotes`
- [Threads](#threads) - `/2/thread/{id}`, `/2/conversation/{id}`
- [Profiles](#profiles) - `/2/profile/{handle}` and its five sub-resources
- [Discovery](#discovery) - `/2/search`, `/2/search/users`, `/2/typeahead`, `/2/trends`
- [Legacy v1 routes](#legacy-v1-routes)
- [Endpoint to CLI command map](#endpoint-to-cli-command-map)

## Shared conventions

### Path parameters

| Name | Accepts |
| --- | --- |
| `{id}` | Snowflake ID as a numeric string, e.g. `20` |
| `{handle}` | Username without `@`, or a numeric user id written as `id:783214` (the `id:` prefix is case-insensitive) |

### Shared query parameters

| Name | Type | Default | Applies to | Notes |
| --- | --- | --- | --- | --- |
| `count` | integer 1-100 | 20 (30 for search) | list endpoints | A hint. Upstream timelines pick their own page size and routinely return more items than requested. `/2/trends` caps at 50. |
| `cursor` | string | - | list endpoints | Pass the previous response's `cursor.bottom`. |
| `lang` | string | - | post-bearing endpoints | ISO 639-1 / 639-5 target language (`en`, `es`, `ja`, `zh-cn`). Uses X's inline translation when present, otherwise falls back to a translation provider. Adds a `translation` object to each status. |
| `about_account` / `aboutAccount` | truthy string | off | `/2/status/{id}`, `/2/thread/{id}`, `/2/conversation/{id}`, `/2/profile/{handle}` | Adds the About This Account block to the author object. Both spellings are accepted. |

Truthy values for boolean-ish query parameters: `1`, `true`, `yes`, `on`, or the
parameter present with an empty value.

### Pagination envelope

List endpoints return:

```json
{ "code": 200, "results": [ ... ], "cursor": { "top": "...", "bottom": "..." } }
```

Send `cursor.bottom` back as `cursor` for the next page. A `null` bottom, an
unchanged cursor, or an empty `results` array means the end of the timeline.
`/2/conversation/{id}` is the exception: its items live under `replies` and its
cursor object only has `bottom`.

---

## Posts

### `GET /2/status/{id}` - get post

One post plus its author. Returns the `SocialThread` envelope
(`code`, `status`, `thread`, `author`); for this route `thread` holds just the
focal post.

| Query | Type | Notes |
| --- | --- | --- |
| `about_account` / `aboutAccount` | truthy | account origin metadata on the author |
| `lang` | string | translate the post text |

Responses: `200` post payload, `400` invalid parameters (`ApiQueryError`),
`401` private or unavailable, `404` not found, `500` upstream failure. `401`/`404`
still return a `SocialThread`-shaped body whose `status` may be a tombstone.

CLI: `fxtwitter.py status <id-or-url> [--lang ja] [--about-account]`

### `GET /2/status/{id}/reposts` - list reposters

Users who reposted the status. Envelope `APIUserListResults`
(`code`, `results` of `APIUser`, `cursor`).

| Query | Type | Default |
| --- | --- | --- |
| `count` | integer 1-100 | 20 |
| `cursor` | string | - |

CLI: `fxtwitter.py reposts <id-or-url> [--count 50] [--pages 3]`

### `GET /2/status/{id}/quotes` - list quote posts

Posts quoting the given post. Implemented with X's `quoted_tweet_id:` search
operator against the Latest tab, so it shares the reliability caveat of `/2/search`.
Envelope `APISearchResults` (same shape as search).

| Query | Type | Default |
| --- | --- | --- |
| `count` | integer 1-100 | 20 |
| `cursor` | string | - |
| `lang` | string | - |

CLI: `fxtwitter.py quotes <id-or-url>`

---

## Threads

### `GET /2/thread/{id}` - unrolled thread

Same envelope as `/2/status/{id}`, but `thread` contains the author's full
self-reply chain when one exists. Use this for "unroll this thread".

Query: `about_account` / `aboutAccount`, `lang`.

CLI: `fxtwitter.py thread <id-or-url> [--format md --full-text]`

### `GET /2/conversation/{id}` - thread and replies

Walks the conversation to its root, returns the author's chain in `thread`, and
replies from other people in `replies`. Envelope `SocialConversation`
(`code`, `status`, `thread`, `replies`, `author`, `cursor.bottom`).

| Query | Type | Default | Notes |
| --- | --- | --- | --- |
| `ranking_mode` | `likes` \| `recency` | `likes` | how replies are ordered |
| `cursor` | string | - | paginate deeper into replies |
| `about_account` / `aboutAccount` | truthy | off | |
| `lang` | string | - | |

Replies may include `APISubstatus` objects (comment-style children used by the
non-Twitter providers FxEmbed also serves).

CLI: `fxtwitter.py conversation <id-or-url> [--ranking-mode recency] [--max-items 50]`

---

## Profiles

### `GET /2/profile/{handle}` - user profile

Envelope `UserAPIResponse`: `code`, `message`, optional `user` (`APIUser`),
optional `reason`, optional `id`. A suspended account returns `code: 404` with
`reason: "suspended"` and `message: "User is suspended"`; a missing account
returns `404` without `reason`.

Query: `about_account` / `aboutAccount`.

CLI: `fxtwitter.py profile <handle> [--about-account]`

### `GET /2/profile/{handle}/about` - About This Account

The `about_account` block alone, without the cost of a full profile fetch.
Envelope `ProfileAboutAPIResponse`: `code`, `message`, optional `about_account`.
The block is omitted when upstream has none.

CLI: `fxtwitter.py about <handle>`

### `GET /2/profile/{handle}/statuses` - user timeline

Envelope `APISearchResults`, or `APIGroupedSearchResults` when `groupthreads` is
set. The richest endpoint of the set.

| Query | Type | Default | Notes |
| --- | --- | --- | --- |
| `count` | integer 1-100 | 20 | |
| `cursor` | string | - | |
| `since` | number >= 0 | - | Unix time. Values >= 1e12 are read as milliseconds, smaller ones as seconds. Without `cursor`, returns **HTTP 204 with no body** when no post in the page is strictly newer. Ideal for polling. |
| `with_replies` | truthy | off | include the user's replies, via alternate upstream timelines |
| `groupthreads` | truthy | off | `results` becomes a mix of `type: "status"` and `type: "thread"` entries |
| `lang` | string | - | |

CLI: `fxtwitter.py statuses <handle> [--since 1767225600] [--with-replies] [--group-threads]`

### `GET /2/profile/{handle}/articles` - long-form articles

Envelope `APISearchResults`; each result carries an `article` object. Most accounts
have none, so an empty `results` here is usually genuine.

Query: `count`, `cursor`, `lang`.

CLI: `fxtwitter.py articles <handle>`

### `GET /2/profile/{handle}/media` - posts with media

Envelope `APISearchResults`, filtered to posts carrying photos or video. The most
reliable way to enumerate an account's images.

Query: `count`, `cursor`, `lang`.

CLI: `fxtwitter.py media <handle>` / `fxtwitter.py download <handle> --from-timeline`

### `GET /2/profile/{handle}/followers` and `GET /2/profile/{handle}/following`

Envelope `APIProfileRelationshipList` (`code`, `results` of `APIUser`, `cursor`).

Query: `count`, `cursor`.

CLI: `fxtwitter.py followers <handle>` / `fxtwitter.py following <handle>`

---

## Discovery

### `GET /2/search` - search posts

| Query | Type | Default | Notes |
| --- | --- | --- | --- |
| `q` | string, required, 1-512 chars | - | X search syntax; see `recipes.md` |
| `feed` | `latest` \| `top` \| `media` | `latest` | which search tab |
| `count` | integer 1-100 | 30 | |
| `cursor` | string | - | |
| `lang` | string | - | |

Envelope `APISearchResults`. An empty `q` or one over 512 characters returns `400`.

**Reliability:** X's search backend often refuses the public instance's guest
session, in which case the API returns `code: 404` with `results: []`. Treat that as
"search unavailable", not "no matches". See `recipes.md` for fallbacks.

CLI: `fxtwitter.py search "<query>" [--feed top]`

### `GET /2/search/users` - search people

The People tab. Envelope `APIUserListResults`. Same reliability caveat as
`/2/search`. `/2/typeahead` is the lighter, unpaginated alternative over the same
corpus and is far more reliable.

Query: `q` (required, max 512), `count` (1-100, default 30), `cursor`, `lang`.

CLI: `fxtwitter.py search-users "<query>"`

### `GET /2/typeahead` - autocomplete

Envelope `APITypeaheadResponse`: `code`, `query`, `num_results`, `users`, `topics`,
`events`. Not paginated.

| Query | Type | Notes |
| --- | --- | --- |
| `q` | string, required | prefix or full query |
| `result_type` | string | comma-separated subset of `events`, `users`, `topics`; defaults to all three. Unknown values are ignored. Hashtags surface under `topics`. |
| `src` | string | upstream hint, default `search_box` |

CLI: `fxtwitter.py typeahead "<query>" [--result-type users,topics]`

### `GET /2/trends` - trending topics

Envelope `APITrendsResponse`: `code`, optional `message`, `timeline_type`,
`trends`, `cursor`.

| Query | Type | Default | Notes |
| --- | --- | --- | --- |
| `type` | `trending` | `trending` | only value currently supported |
| `count` | integer 1-50 | 20 | |

Occasionally returns an empty `trends` array on an otherwise `200` response; retry.

CLI: `fxtwitter.py trends [--count 30]`

---

## Legacy v1 routes

Still served for backward compatibility. They do not support the newer parameters,
and they name the repost counter `retweets` (v2 calls it `reposts`) and the card
`twitter_card` (v2 calls it `card`). Prefer v2 for new work.

| Route | Returns |
| --- | --- |
| `GET /status/{id}` | `{ code, message, tweet }` |
| `GET /{handle}/status/{id}` | `{ code, message, tweet }` |
| `GET /{handle}/status/{id}/{lang}` | same, with `tweet.translation` populated |
| `GET /{handle}` | `{ code, message, user }` |

CLI: `fxtwitter.py v1 <handle> --status <id> [--translate ja]`, or
`fxtwitter.py v1 <handle>` for the profile.

---

## Endpoint to CLI command map

| Endpoint | CLI command |
| --- | --- |
| `/2/status/{id}` | `status` |
| `/2/status/{id}/reposts` | `reposts` |
| `/2/status/{id}/quotes` | `quotes` |
| `/2/thread/{id}` | `thread` |
| `/2/conversation/{id}` | `conversation` |
| `/2/profile/{handle}` | `profile` |
| `/2/profile/{handle}/about` | `about` |
| `/2/profile/{handle}/statuses` | `statuses` |
| `/2/profile/{handle}/articles` | `articles` |
| `/2/profile/{handle}/media` | `media` |
| `/2/profile/{handle}/followers` | `followers` |
| `/2/profile/{handle}/following` | `following` |
| `/2/search` | `search` |
| `/2/search/users` | `search-users` |
| `/2/typeahead` | `typeahead` |
| `/2/trends` | `trends` |
| `/2/openapi.json` | `spec` |
| legacy v1 | `v1` |
| anything else | `get <path> --param k=v` |
