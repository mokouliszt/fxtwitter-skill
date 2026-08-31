# FxTwitter API v2 - response schema reference

Field lists for every object the v2 API returns. Derived from
`GET /2/openapi.json` (OpenAPI 3.0.0, `info.version` 2.0.0) and verified against
live responses. Fetch the live spec when something here looks stale:
`python3 scripts/fxtwitter.py spec --raw > openapi.json`.

Nullable is the norm: many fields exist on every response but hold `null` when X
does not expose the value (`views` on old posts, `rank` on trends, `verified_at`).
Treat "present but null" as unavailable, not as zero.

## Contents

- [Envelopes](#envelopes)
- [APITwitterStatus](#apitwitterstatus)
- [Media](#media)
- [Poll, community note, community, article, card](#poll-community-note-community-article-card)
- [APIUser](#apiuser)
- [APIAboutAccount](#apiaboutaccount)
- [APIStatusTombstone](#apistatustombstone)
- [Supporting objects](#supporting-objects)
- [Discriminators](#discriminators)

## Envelopes

### SocialThread - `/2/status/{id}`, `/2/thread/{id}`

| Field | Type | Notes |
| --- | --- | --- |
| `code` | number | mirrors the HTTP status |
| `status` | `APITwitterStatus` \| `APIStatusTombstone` \| null | the focal post |
| `thread` | array of status or tombstone | the author's chain; a single entry for `/2/status` |
| `author` | `APIUser` | |

### SocialConversation - `/2/conversation/{id}`

`code`, `status`, `thread`, `author` as above, plus:

| Field | Type | Notes |
| --- | --- | --- |
| `replies` | array of status, tombstone or `APISubstatus` | replies from other accounts |
| `cursor` | `{ bottom: string }` | no `top` on this endpoint |

### APISearchResults - `/2/search`, `/2/status/{id}/quotes`, `/2/profile/{handle}/{statuses,articles,media}`

| Field | Type |
| --- | --- |
| `code` | number |
| `results` | array of `APITwitterStatus` |
| `cursor` | `{ top: string \| null, bottom: string \| null }` |

### APIGroupedSearchResults - `/2/profile/{handle}/statuses?groupthreads=1`

Same, but `results` is an array of `TimelineEntryTwitter`, a union of
`APITwitterStatus` and:

**TimelineThreadTwitter**

| Field | Type | Notes |
| --- | --- | --- |
| `type` | `"thread"` | discriminator |
| `conversation_id` | string | |
| `statuses` | array of `APITwitterStatus` | the visible slice |
| `all_status_ids` | array of string | every ID in the conversation, when upstream provides it |
| `truncated` | boolean | true when the conversation has more posts than `statuses` |

### APIUserListResults / APIProfileRelationshipList

`/2/status/{id}/reposts`, `/2/search/users`, `/2/profile/{handle}/followers`,
`/2/profile/{handle}/following`.

| Field | Type |
| --- | --- |
| `code` | number |
| `results` | array of `APIUser` |
| `cursor` | `{ top, bottom }` |

### UserAPIResponse - `/2/profile/{handle}`

| Field | Type | Notes |
| --- | --- | --- |
| `code` | number | |
| `message` | string | |
| `user` | `APIUser` | absent on error |
| `reason` | `"suspended"` | present only for suspended accounts |
| `id` | string | numeric user id when upstream includes it |

### ProfileAboutAPIResponse - `/2/profile/{handle}/about`

`code`, `message`, optional `about_account` (`APIAboutAccount`).

### APITypeaheadResponse - `/2/typeahead`

| Field | Type |
| --- | --- |
| `code` | number |
| `query` | string |
| `num_results` | number |
| `users` | array of `APIUser` (sparse - counts are often 0 here) |
| `topics` | array of `{ topic, result_context?: { display_string, redirect_url, types: [{ type }] } }` |
| `events` | array of `{ topic, url?, supporting_text?, primary_image?: { url, width, height } }` |

### APITrendsResponse - `/2/trends`

| Field | Type | Notes |
| --- | --- | --- |
| `code` | number | |
| `message` | string | optional |
| `timeline_type` | string | `trending` |
| `trends` | array of `{ name, rank, context, grouped_topics?: [{ name }] }` | `rank` is usually null; `context` is text like `Sports · Trending` |
| `cursor` | `{ top, bottom }` | |

### ApiQueryError - any `400`

`{ code: 400, message: string }`

## APITwitterStatus

Required: `type`, `id`, `url`, `text`, `created_at`, `created_timestamp`, `likes`,
`reposts`, `quotes`, `replies`, `author`, `media`, `raw_text`, `lang`,
`possibly_sensitive`, `replying_to`, `source`, `embed_card`, `provider`,
`is_note_tweet`, `community_note`, `reposted_by`.

| Field | Type | Notes |
| --- | --- | --- |
| `type` | `"status"` | discriminator |
| `id` | string | snowflake |
| `url` | string | canonical `x.com` permalink |
| `text` | string | display text, entities already expanded |
| `created_at` | string | Twitter format, e.g. `Tue Mar 21 20:50:14 +0000 2006` |
| `created_timestamp` | number | Unix seconds - prefer this for date maths |
| `likes` | number | |
| `reposts` | number | v1 calls this `retweets` |
| `quotes` | number | |
| `replies` | number | |
| `views` | number \| null | null on older posts |
| `bookmarks` | number \| null | |
| `quote` | `APITwitterStatus` \| `APIStatusTombstone` | the quoted post, recursively |
| `poll` | object | see below |
| `author` | `APIUser` | |
| `media` | object | see below; `{}` when there is none |
| `raw_text` | `{ text, display_text_range: [number, number], facets: Facet[] }` | text before entity expansion, with offsets |
| `lang` | string | detected language |
| `translation` | `{ text, source_lang, source_lang_en, target_lang, provider }` | only when `lang` was requested |
| `possibly_sensitive` | boolean | |
| `replying_to` | `APIReplyingTo` \| null | |
| `source` | string | client name, e.g. `Twitter Web App` |
| `embed_card` | `tweet` \| `summary` \| `summary_large_image` \| `player` | |
| `provider` | `"twitter"` | |
| `community` | object | see below |
| `article` | object | see below |
| `is_note_tweet` | boolean | true for long-form posts past the classic limit |
| `community_note` | `{ text, facets: Facet[] }` \| null | Community Notes context |
| `reposted_by` | `APIRepostedBy` \| null | set when the post surfaced via a repost |
| `card` | object | see below; v1 calls this `twitter_card` |

## Media

`status.media` is an object, empty when the post has no attachments.

| Key | Type | Notes |
| --- | --- | --- |
| `all` | array of any media item | everything, in display order - iterate this when you do not care about the kind |
| `photos` | array of Photo | |
| `videos` | array of Video | |
| `mosaic` | Mosaic | present when several photos were combined |
| `external` | `{ type: "video", url, thumbnail_url, height, width }` | externally hosted video |
| `broadcast` | Broadcast | live or ended Spaces / broadcasts |

**Photo**

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `format` | string | |
| `type` | `photo` \| `gif` | |
| `url` | string | already includes `?name=orig`, i.e. full resolution |
| `width`, `height` | number | |
| `transcode_url` | string | |
| `altText` | string | alt text, when the author supplied it - use it for image descriptions |

**Video**

| Field | Type | Notes |
| --- | --- | --- |
| `id`, `format` | string | |
| `type` | `video` \| `gif` | |
| `url` | string | default variant |
| `width`, `height`, `duration`, `filesize` | number | `duration` in seconds |
| `thumbnail_url`, `transcode_url` | string | |
| `formats` | array of `{ container: mp4\|webm\|m3u8, codec: h264\|hevc\|vp9\|av1, bitrate, url, size, width, height }` | pick the highest `bitrate` for best quality; `m3u8` is a playlist, not a downloadable file |
| `publisher` | `APIUser` + extras | when the video is licensed content |

**Mosaic**: `{ id, format, type: "mosaic_photo", url, width, height, formats: { webp, jpeg } }`

**Broadcast**: `{ url, width, height, state: LIVE|ENDED, broadcaster: { username, display_name, id }, stream: { url }, title, source, orientation: landscape|portrait, broadcast_id, media_id, media_key, is_high_latency, thumbnail: { original, small, medium, large, x_large } }`

## Poll, community note, community, article, card

**poll**

```
{ choices: [{ label, count, percentage }], total_votes, ends_at, time_left_en }
```

**community_note**: `{ text, facets: Facet[] }`

**community**

`{ id, name, description, created_at, search_tags: string[], is_nsfw, topic,
admin: APIUser, creator: APIUser, join_policy: Open|Closed,
invites_policy: MemberInvitesAllowed|MemberInvitesDisabled, is_pinned }`

**article** (X Articles / long-form)

| Field | Type |
| --- | --- |
| `id`, `title`, `preview_text` | string |
| `created_at`, `modified_at` | string |
| `cover_media` | `{ id, media_key, media_id, media_info }` |
| `content` | Draft.js-style `{ blocks: [{ key, data, entityRanges, inlineStyleRanges, text, type }], entityMap: [...] }` |
| `media_entities` | array of the same media_info shape |

`content.entityMap` entries are one of `MARKDOWN` (`data.markdown` holds the
rendered source - the easiest way to read an article), `MEDIA`
(`data.mediaItems[].mediaId`), or `TWEET` (`data.tweetId`).

`media_info` is either
`{ __typename: "ApiImage", original_img_height, original_img_width, original_img_url, color_info }`
or
`{ __typename: "ApiVideo"|"ApiGif", type, id, ext_alt_text, media_url_https, original_info, sizes, video_info: { aspect_ratio, duration_millis, variants: [{ bitrate, content_type, url }] } }`.

**card** (link preview)

`{ url, title, description, domain, card_name, image: { width, height, url, alt } }`

## APIUser

Required: `type`, `id`, `name`, `screen_name`, `avatar_url`, `banner_url`,
`description`, `raw_description`, `location`, `url`, `protected`, `followers`,
`following`, `statuses`, `media_count`, `likes`, `joined`, `website`.

| Field | Type | Notes |
| --- | --- | --- |
| `type` | `"profile"` | discriminator |
| `id` | string | numeric user id; reuse as `id:<id>` in `{handle}` |
| `name` | string | display name |
| `screen_name` | string | handle without `@` |
| `avatar_url`, `banner_url` | string \| null | avatar comes back at `_normal` or `_200x200`; swap the suffix for `_400x400` or drop it for the original |
| `description` | string | bio, entities expanded |
| `raw_description` | `{ text, facets: Facet[] }` | |
| `location` | string | free text, often empty |
| `url` | string | profile permalink |
| `protected` | boolean | true means the timeline endpoints will return nothing |
| `followers`, `following`, `statuses`, `media_count`, `likes` | number | counts are 0 in typeahead results |
| `joined` | string | Twitter-format date |
| `website` | `{ url, display_url }` \| null | |
| `birthday` | `{ day, month, year }` | only when public |
| `verification` | `{ verified, type: organization\|government\|individual\|None, verified_at, identity_verified, verified_by }` | |
| `about_account` | `APIAboutAccount` | only when requested |
| `profile_embed` | boolean | |

## APIAboutAccount

The About This Account panel. All fields optional.

| Field | Type | Notes |
| --- | --- | --- |
| `based_in` | string | country X believes the account operates from |
| `location_accurate` | boolean | X's own confidence flag |
| `created_country_accurate` | boolean | |
| `source` | string | e.g. `United States App Store` |
| `username_changes` | `{ count, last_changed_at }` | |

Useful for authenticity checks, but it is X's inference, not ground truth - report
it as such.

## APIStatusTombstone

Returned in place of a status that cannot be shown. Appears as `status`, inside
`thread`/`replies`, or as `quote`.

| Field | Type | Notes |
| --- | --- | --- |
| `type` | `"tombstone"` | discriminator |
| `provider` | `twitter` \| `bluesky` \| `mastodon` \| `tiktok` \| `instagram` \| `threads` | |
| `reason` | `deleted` \| `suspended` \| `private` \| `blocked` \| `unavailable` | |
| `message` | string | human-readable explanation |
| `id`, `url`, `author` | optional | present when known |
| `at_uri`, `cid` | optional | Bluesky only |

Always branch on `type === "tombstone"` before reading `text` or `likes`.

## Supporting objects

**APIReplyingTo**: `{ screen_name, status, url?, profile_url?, display_name? }` -
`status` is the parent post's ID.

**APIRepostedBy**: `{ id, name, screen_name, avatar_url?, url? }`

**Facet** (used by `raw_text.facets`, `community_note.facets`,
`raw_description.facets`): `{ type, indices: [start, end], original, replacement,
display, id }` - lets you re-render mentions, hashtags and links yourself.

**APISubstatus**: a comment-style child post used by the Instagram / TikTok /
Threads providers FxEmbed also serves. Same field set as `APITwitterStatus` minus
`quotes`/`views`/`bookmarks`, plus `type: "substatus"`, `parent_id` and `media_pk`.
It can appear in `SocialConversation.replies`.

**Non-Twitter status types**: the spec also defines `APIBlueskyStatus`,
`APIMastodonStatus`, `APIInstagramStatus`, `APIThreadsStatus` and
`APITikTokStatus`, which the shared envelopes accept. Requests to
`api.fxtwitter.com` return `provider: "twitter"`; the others appear when the same
client is pointed at `api.fxbsky.app` or another FxEmbed host.

## Discriminators

Branch on `type` before reading any object out of a mixed array:

| `type` | Object |
| --- | --- |
| `status` | `APITwitterStatus` (or another provider's status) |
| `substatus` | `APISubstatus` |
| `thread` | `TimelineThreadTwitter` (grouped timeline entry) |
| `tombstone` | `APIStatusTombstone` |
| `profile` | `APIUser` |
