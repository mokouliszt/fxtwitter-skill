# FxEmbed URL modifiers

These are the *embed* side of FxTwitter, not the JSON API. Reach for them when the
user wants a link that renders properly in Discord, Telegram, Slack or similar,
rather than structured data. The API commands in `endpoints.md` are what you want
for extracting information.

## Domains

Replace the host of an X permalink with any of these; the path stays identical.

| Domain | Notes |
| --- | --- |
| `fxtwitter.com` | canonical |
| `fixupx.com` | matches `x.com` muscle memory |
| `fixvx.com`, `twittpr.com`, `girlcockx.com` | aliases |
| `fxbsky.app` | Bluesky equivalent |

`https://x.com/user/status/123` becomes `https://fxtwitter.com/user/status/123`.

## Subdomain flags

Prefix the domain to change how the link renders. They compose with the path
suffixes below.

| Prefix | Effect |
| --- | --- |
| `d.` | Link straight to the media file - `d.fxtwitter.com/...` redirects to the raw image or video. Best for "give me the video file". |
| `m.` | Mosaic: combine several images into one composite so all of them appear in a single embed. |
| `g.` | Gallery: media and author only, no post text. |
| `t.` | Text only: strip media from the embed. |
| `i.` | Telegram Instant View. |
| `o.` | Old-style Discord embed. |

## Path suffixes

| Suffix | Effect |
| --- | --- |
| `/photo/{n}` | Embed a specific image from a multi-image post, e.g. `/photo/2`. |
| `/video/{n}` | Same for video. |
| `/{lang}` | Translate the post text in the embed, e.g. `.../status/20/ja`. This is also the legacy v1 translation route on `api.fxtwitter.com`. |
| `.mp4` / `.jpg` | Direct media, equivalent to the `d.` prefix. |

## Other embed-side features

- **RSS and Atom feeds** are available for accounts and searches on the embed
  domains - useful for monitoring without polling the API.
- **Custom redirect** lets a user set a cookie so X links open in their preferred
  client.
- **Custom embed branding** is available for self-hosted instances.

Refer the user to the FxEmbed documentation for the exact feed and configuration
syntax, which changes more often than the API.

## Choosing between a modifier and the API

| Goal | Use |
| --- | --- |
| Paste a link somewhere that will render it | modifier domain |
| Give someone a direct file link | `d.` prefix or `.mp4` / `.jpg` suffix |
| Read the post text, stats, replies, media list | API (`status`, `thread`, `conversation`) |
| Save files to disk | `fxtwitter.py download` |
| Translate for reading | API `--lang ja` (returns text you can quote) |
| Translate for embedding | `/{lang}` suffix on a modifier domain |

The client normalises every one of these forms, so a `d.fxtwitter.com/user/status/123/photo/2`
link can be passed straight to any command.
