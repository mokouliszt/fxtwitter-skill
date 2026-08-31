#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 mokouliszt
"""
fxtwitter.py - a dependency-free command line client for the FxTwitter API v2.

Covers every documented v2 operation plus the legacy v1 routes, with
token-efficient text output for agent use and raw JSON for programmatic use.

Requires only the Python 3.8+ standard library, so it runs unchanged inside the
Claude.ai / Claude mobile sandbox, Claude Code, Codex, or any plain shell.

Run `python3 fxtwitter.py --help` for usage, or read references/endpoints.md.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

__version__ = "1.0.0"

DEFAULT_BASE = "https://api.fxtwitter.com"
DEFAULT_UA = f"fxtwitter-skill/{__version__} (+https://github.com/mokouliszt)"
DEFAULT_TIMEOUT = 30.0

# Exit codes. Callers (including agents) can branch on these without parsing text.
EXIT_OK = 0
EXIT_RUNTIME = 1        # network failure, unparseable body, IO error
EXIT_USAGE = 2          # bad arguments (argparse also uses 2)
EXIT_API_ERROR = 3      # request succeeded but the API reported a non-2xx `code`
EXIT_NO_CONTENT = 4     # HTTP 204, i.e. `--since` matched nothing new

# The API rejects requests with no User-Agent (401), so one is always sent.
# Every list endpoint paginates through `cursor.bottom`.


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class FxError(Exception):
    """Any failure that should end the process with a message rather than a traceback."""

    def __init__(self, message: str, exit_code: int = EXIT_RUNTIME, payload: Any = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.payload = payload


# --------------------------------------------------------------------------- #
# Input normalisation
# --------------------------------------------------------------------------- #

_STATUS_ID_RE = re.compile(r"(?:status(?:es)?|post)/(\d+)")
_BARE_ID_RE = re.compile(r"^\d{1,25}$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")

# Every host that mirrors an x.com permalink. Subdomain modifiers (d., g., m.,
# t., i., o., c., or a two-letter language prefix) are stripped before matching.
_KNOWN_HOSTS = {
    "x.com", "twitter.com", "mobile.twitter.com", "www.x.com", "www.twitter.com",
    "fxtwitter.com", "www.fxtwitter.com", "fixupx.com", "www.fixupx.com",
    "fixvx.com", "twittpr.com", "vxtwitter.com", "fixtweet.com",
    "api.fxtwitter.com", "pxtwitter.com", "girlcockx.com", "stupidpenisx.com",
}


def _strip_modifier_subdomain(host: str) -> str:
    """Drop FxEmbed subdomain flags so d.fxtwitter.com resolves like fxtwitter.com."""
    parts = host.split(".")
    while len(parts) > 2 and len(parts[0]) <= 3:
        parts = parts[1:]
    return ".".join(parts)


def parse_status_id(value: str) -> str:
    """Accept a bare snowflake ID or any X/FxEmbed permalink and return the ID.

    Trailing modifiers such as /photo/2, /video/1, a /{lang} translation suffix,
    a .mp4 / .jpg direct-media suffix, and query strings are all tolerated.
    """
    value = (value or "").strip()
    if not value:
        raise FxError("empty status id", EXIT_USAGE)
    if _BARE_ID_RE.match(value):
        return value
    candidate = value if "//" in value else "https://" + value
    try:
        parsed = urllib.parse.urlparse(candidate)
    except ValueError as exc:
        raise FxError(f"could not parse {value!r} as a URL: {exc}", EXIT_USAGE)
    host = _strip_modifier_subdomain((parsed.netloc or "").lower())
    if host and host not in _KNOWN_HOSTS:
        # Unknown host: still try, self-hosted instances use arbitrary domains.
        pass
    match = _STATUS_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    tail = parsed.path.rstrip("/").split("/")[-1]
    tail = re.sub(r"\.(mp4|jpg|jpeg|png|webp|webm|gif)$", "", tail, flags=re.I)
    if _BARE_ID_RE.match(tail):
        return tail
    raise FxError(f"no status id found in {value!r}", EXIT_USAGE)


def parse_handle(value: str) -> str:
    """Accept @name, name, a profile URL, or `id:<numeric id>` and return the handle.

    The API resolves numeric ids only through the `id:` prefix, so a bare number
    is passed through as `id:<n>` rather than being treated as a username.
    """
    value = (value or "").strip()
    if not value:
        raise FxError("empty handle", EXIT_USAGE)
    if value.lower().startswith("id:"):
        rest = value[3:].strip()
        if not rest.isdigit():
            raise FxError(f"`id:` prefix needs a numeric user id, got {value!r}", EXIT_USAGE)
        return "id:" + rest
    if value.isdigit():
        return "id:" + value
    value = value.lstrip("@")
    if "/" in value or "." in value:
        candidate = value if "//" in value else "https://" + value
        parsed = urllib.parse.urlparse(candidate)
        segments = [s for s in parsed.path.split("/") if s]
        if segments:
            value = segments[-1] if segments[-1] not in ("status", "statuses") else segments[0]
        else:
            value = parsed.netloc
        value = value.lstrip("@")
    if not _HANDLE_RE.match(value):
        raise FxError(
            f"{value!r} is not a valid X handle (1-15 chars, letters/digits/underscore). "
            "Use `id:<numeric id>` to look a user up by id.",
            EXIT_USAGE,
        )
    return value


def truthy_flag(value: bool) -> str:
    """The API treats `1`, `true`, `yes`, `on` and empty string as true."""
    return "1" if value else "0"


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #

class FxClient:
    """Minimal JSON client for FxEmbed-compatible hosts."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        user_agent: str = DEFAULT_UA,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 3,
        sleep_between: float = 0.2,
        verbose: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent or DEFAULT_UA
        self.timeout = timeout
        self.retries = max(0, retries)
        self.sleep_between = max(0.0, sleep_between)
        self.verbose = verbose

    # -- low level ---------------------------------------------------------- #

    def build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        if clean:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(clean, doseq=True)
        return url

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
        """Return (http_status, decoded_json_or_None). 204 decodes to None."""
        url = self.build_url(path, params)
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            if self.verbose:
                print(f"[fxtwitter] GET {url} (attempt {attempt + 1})", file=sys.stderr)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = response.getcode()
                    raw = response.read()
                    return status, self._decode(raw, status, url)
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                status = exc.code
                # 429 and 5xx are worth retrying; 4xx bodies are real answers.
                if status == 429 or 500 <= status < 600:
                    last_error = exc
                    if attempt < self.retries:
                        self._backoff(attempt, exc.headers.get("Retry-After"))
                        continue
                if status == 401 and not raw:
                    raise FxError(
                        "401 Unauthorized - the API requires a User-Agent header. "
                        "Set --user-agent or FXTWITTER_USER_AGENT.",
                        EXIT_API_ERROR,
                    )
                return status, self._decode(raw, status, url)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self._backoff(attempt, None)
                    continue
                raise FxError(f"network error requesting {url}: {exc}", EXIT_RUNTIME)
        raise FxError(f"request to {url} failed after retries: {last_error}", EXIT_RUNTIME)

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = 0.75 * (2 ** attempt)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        if self.verbose:
            print(f"[fxtwitter] retrying in {delay:.1f}s", file=sys.stderr)
        time.sleep(min(delay, 30.0))

    @staticmethod
    def _decode(raw: bytes, status: int, url: str) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            snippet = raw[:200].decode("utf-8", errors="replace")
            raise FxError(
                f"non-JSON response (HTTP {status}) from {url}: {exc}; body starts with {snippet!r}",
                EXIT_RUNTIME,
            )

    # -- pagination --------------------------------------------------------- #

    def paginate(
        self,
        path: str,
        params: Dict[str, Any],
        pages: int = 1,
        max_items: Optional[int] = None,
        items_key: str = "results",
    ) -> Dict[str, Any]:
        """Follow `cursor.bottom` up to `pages` times and merge `items_key`.

        The merged payload keeps the shape of a single page so every formatter
        and every downstream consumer works the same whether or not you paged.
        """
        merged: Optional[Dict[str, Any]] = None
        collected: List[Any] = []
        cursor = params.get("cursor")
        page_count = 0
        last_status = 200

        while page_count < pages:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            status, payload = self.get(path, page_params)
            last_status = status
            if payload is None:
                if merged is None:
                    return {"__http_status__": status, "__no_content__": True}
                break
            if merged is None:
                merged = dict(payload)
            items = payload.get(items_key) or []
            collected.extend(items)
            page_count += 1

            next_cursor = ((payload.get("cursor") or {}).get("bottom")) if isinstance(payload.get("cursor"), dict) else None
            if not items or not next_cursor or next_cursor == cursor:
                cursor = next_cursor
                break
            cursor = next_cursor
            if max_items is not None and len(collected) >= max_items:
                break
            if page_count < pages and self.sleep_between:
                time.sleep(self.sleep_between)

        if merged is None:
            raise FxError(f"no payload returned from {path}", EXIT_RUNTIME)
        if max_items is not None:
            collected = collected[:max_items]
        merged[items_key] = collected
        cursor_obj = merged.get("cursor")
        if isinstance(cursor_obj, dict):
            cursor_obj = dict(cursor_obj)
            cursor_obj["bottom"] = cursor
            merged["cursor"] = cursor_obj
        merged["__http_status__"] = last_status
        merged["__pages_fetched__"] = page_count
        return merged


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def _num(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _iso(status: Dict[str, Any]) -> str:
    ts = status.get("created_timestamp")
    if isinstance(ts, (int, float)):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    return str(status.get("created_at") or "-")


def _clip(text: str, limit: Optional[int]) -> str:
    text = (text or "").strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + f"... [+{len(text) - limit} chars]"
    return text


def _media_summary(status: Dict[str, Any]) -> List[str]:
    media = status.get("media") or {}
    lines: List[str] = []
    for photo in media.get("photos") or []:
        alt = photo.get("altText")
        alt_text = f" alt={alt!r}" if alt else ""
        lines.append(f"  photo {photo.get('width')}x{photo.get('height')} {photo.get('url')}{alt_text}")
    for video in media.get("videos") or []:
        lines.append(
            f"  {video.get('type', 'video')} {video.get('width')}x{video.get('height')} "
            f"{video.get('duration')}s {video.get('url')}"
        )
    external = media.get("external")
    if external:
        lines.append(f"  external {external.get('type')} {external.get('url')}")
    broadcast = media.get("broadcast")
    if broadcast:
        lines.append(f"  broadcast [{broadcast.get('state')}] {broadcast.get('title')} {broadcast.get('url')}")
    mosaic = media.get("mosaic")
    if mosaic and not lines:
        lines.append(f"  mosaic {mosaic.get('url')}")
    return lines


def format_status(status: Dict[str, Any], text_limit: Optional[int], indent: str = "") -> str:
    if status.get("type") == "tombstone":
        return (
            f"{indent}[tombstone] {status.get('reason')} - {status.get('message')} "
            f"({status.get('url') or status.get('id') or 'unknown'})"
        )
    if status.get("type") == "thread":
        # Grouped timeline entry from `--group-threads`.
        head = (
            f"{indent}[thread {status.get('conversation_id')}] "
            f"{len(status.get('statuses') or [])} posts"
            + (" (truncated)" if status.get("truncated") else "")
        )
        body = "\n".join(
            format_status(s, text_limit, indent + "  ") for s in (status.get("statuses") or [])
        )
        return head + ("\n" + body if body else "")

    author = status.get("author") or {}
    handle = author.get("screen_name") or "?"
    name = author.get("name") or ""
    # v1 payloads call this field `retweets`; v2 renamed it to `reposts`.
    reposts = status.get("reposts")
    if reposts is None:
        reposts = status.get("retweets")
    header = (
        f"{indent}[{status.get('id')}] @{handle} ({name}) - {_iso(status)}\n"
        f"{indent}  likes={_num(status.get('likes'))} reposts={_num(reposts)} "
        f"replies={_num(status.get('replies'))} quotes={_num(status.get('quotes'))} "
        f"views={_num(status.get('views'))} bookmarks={_num(status.get('bookmarks'))} "
        f"lang={status.get('lang')}"
    )
    parts = [header]

    text = _clip(status.get("text") or "", text_limit)
    if text:
        parts.append("\n".join(f"{indent}  | {line}" for line in text.splitlines()))

    translation = status.get("translation")
    if translation:
        translated = _clip(translation.get("text") or "", text_limit)
        parts.append(
            f"{indent}  translated ({translation.get('source_lang')} -> "
            f"{translation.get('target_lang')} via {translation.get('provider')}):"
        )
        parts.append("\n".join(f"{indent}  | {line}" for line in translated.splitlines()))

    replying = status.get("replying_to")
    if replying:
        parts.append(f"{indent}  replying_to @{replying.get('screen_name')} ({replying.get('status')})")

    reposted = status.get("reposted_by")
    if reposted:
        parts.append(f"{indent}  reposted_by @{reposted.get('screen_name')}")

    poll = status.get("poll")
    if poll:
        choices = ", ".join(
            f"{c.get('label')}={c.get('percentage')}% ({_num(c.get('count'))})"
            for c in (poll.get("choices") or [])
        )
        parts.append(
            f"{indent}  poll total={_num(poll.get('total_votes'))} ends={poll.get('ends_at')} "
            f"left={poll.get('time_left_en')} :: {choices}"
        )

    note = status.get("community_note")
    if note:
        parts.append(f"{indent}  community_note: {_clip(note.get('text') or '', text_limit)}")

    community = status.get("community")
    if community:
        parts.append(f"{indent}  community: {community.get('name')} ({community.get('id')})")

    article = status.get("article")
    if article:
        parts.append(f"{indent}  article: {article.get('title')} ({article.get('id')})")

    card = status.get("card") or status.get("twitter_card")
    if isinstance(card, dict):
        parts.append(f"{indent}  card: {card.get('title')} <{card.get('url')}> [{card.get('domain')}]")

    media_lines = _media_summary(status)
    if media_lines:
        parts.append("\n".join(indent + line for line in media_lines))

    quote = status.get("quote")
    if quote:
        parts.append(f"{indent}  quoting:")
        parts.append(format_status(quote, text_limit, indent + "    "))

    if status.get("is_note_tweet"):
        parts.append(f"{indent}  (note tweet / long post)")
    if status.get("possibly_sensitive"):
        parts.append(f"{indent}  (possibly sensitive)")

    parts.append(f"{indent}  source={status.get('source')} url={status.get('url')}")
    return "\n".join(p for p in parts if p)


def format_user(user: Dict[str, Any], text_limit: Optional[int]) -> str:
    verification = user.get("verification") or {}
    verified = ""
    if verification.get("verified"):
        verified = f" [verified:{verification.get('type')}]"
    lines = [
        f"@{user.get('screen_name')} ({user.get('name')}) id={user.get('id')}{verified}",
        f"  followers={_num(user.get('followers'))} following={_num(user.get('following'))} "
        f"posts={_num(user.get('statuses'))} media={_num(user.get('media_count'))} "
        f"likes={_num(user.get('likes'))} protected={user.get('protected')}",
        f"  joined={user.get('joined')} location={user.get('location') or '-'}",
    ]
    description = _clip(user.get("description") or "", text_limit)
    if description:
        lines.extend(f"  | {line}" for line in description.splitlines())
    website = user.get("website") or {}
    if website.get("url"):
        lines.append(f"  website={website.get('url')}")
    birthday = user.get("birthday")
    if birthday:
        lines.append(f"  birthday={birthday.get('year')}-{birthday.get('month')}-{birthday.get('day')}")
    about = user.get("about_account")
    if about:
        lines.append("  " + format_about(about).replace("\n", "\n  "))
    lines.append(f"  avatar={user.get('avatar_url')}")
    lines.append(f"  url={user.get('url')}")
    return "\n".join(lines)


def format_about(about: Dict[str, Any]) -> str:
    changes = about.get("username_changes") or {}
    return (
        f"about_account: based_in={about.get('based_in')} "
        f"location_accurate={about.get('location_accurate')} "
        f"created_country_accurate={about.get('created_country_accurate')} "
        f"source={about.get('source')} "
        f"username_changes={changes.get('count')} (last {changes.get('last_changed_at')})"
    )


def format_summary(payload: Dict[str, Any], text_limit: Optional[int]) -> str:
    """Render any v2 or v1 payload as compact plain text."""
    if payload.get("__no_content__"):
        return "204 No Content - nothing newer than the given `since` timestamp."

    out: List[str] = []
    code = payload.get("code")
    message = payload.get("message")
    if code is not None and code != 200:
        out.append(f"!! code={code}" + (f" message={message}" if message else ""))
        reason = payload.get("reason")
        if reason:
            out.append(f"!! reason={reason}")

    # Single status / thread / conversation
    if "status" in payload and payload.get("status") is not None:
        out.append("== focal post")
        out.append(format_status(payload["status"], text_limit))
    if payload.get("thread"):
        thread = payload["thread"]
        if len(thread) > 1 or "status" not in payload:
            out.append(f"== thread ({len(thread)} posts)")
            out.extend(format_status(s, text_limit) for s in thread)
    if payload.get("replies") is not None:
        replies = payload["replies"]
        out.append(f"== replies ({len(replies)})")
        out.extend(format_status(s, text_limit) for s in replies)

    # v1 shape
    if "tweet" in payload and payload.get("tweet") is not None:
        out.append("== tweet (v1)")
        out.append(format_status(payload["tweet"], text_limit))

    # Lists
    if isinstance(payload.get("results"), list):
        results = payload["results"]
        kinds = {r.get("type") for r in results if isinstance(r, dict)}
        label = "users" if kinds == {"profile"} else "results"
        out.append(f"== {label} ({len(results)})")
        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "profile":
                out.append(format_user(item, text_limit))
            else:
                out.append(format_status(item, text_limit))

    # Profile
    if payload.get("user"):
        out.append("== user")
        out.append(format_user(payload["user"], text_limit))
    if payload.get("about_account") and "user" not in payload:
        out.append("== " + format_about(payload["about_account"]))

    # Typeahead
    if "num_results" in payload:
        out.append(f"== typeahead q={payload.get('query')!r} num_results={payload.get('num_results')}")
        for user in payload.get("users") or []:
            verification = (user.get("verification") or {}).get("verified")
            out.append(f"  user @{user.get('screen_name')} ({user.get('name')}) verified={verification}")
        for topic in payload.get("topics") or []:
            out.append(f"  topic {topic.get('topic')}")
        for event in payload.get("events") or []:
            out.append(f"  event {event.get('topic')} - {event.get('supporting_text')} {event.get('url') or ''}")

    # Trends
    if payload.get("trends") is not None:
        out.append(f"== trends ({len(payload['trends'])}) timeline_type={payload.get('timeline_type')}")
        for i, trend in enumerate(payload["trends"], 1):
            grouped = ", ".join(g.get("name", "") for g in (trend.get("grouped_topics") or []))
            suffix = f" [{grouped}]" if grouped else ""
            out.append(f"  {i:>2}. {trend.get('name')} ({trend.get('context')}){suffix}")

    cursor = payload.get("cursor")
    if isinstance(cursor, dict) and cursor.get("bottom"):
        pages = payload.get("__pages_fetched__")
        page_note = f" pages_fetched={pages}" if pages else ""
        out.append(f"== next cursor: {cursor['bottom']}{page_note}")

    if not out:
        out.append(json.dumps(payload, ensure_ascii=False, indent=2))
    return "\n".join(out)


def format_markdown(payload: Dict[str, Any], text_limit: Optional[int]) -> str:
    """Markdown rendering for pasting into notes or reports."""
    lines: List[str] = []

    def status_md(status: Dict[str, Any], level: str = "###") -> None:
        if status.get("type") == "tombstone":
            lines.append(f"{level} (unavailable: {status.get('reason')})\n")
            return
        author = status.get("author") or {}
        lines.append(f"{level} [@{author.get('screen_name')}]({author.get('url')}) - {_iso(status)}")
        lines.append("")
        text = _clip(status.get("text") or "", text_limit)
        for line in text.splitlines():
            lines.append(f"> {line}")
        lines.append("")
        lines.append(
            f"- likes {_num(status.get('likes'))} / reposts {_num(status.get('reposts'))} / "
            f"replies {_num(status.get('replies'))} / views {_num(status.get('views'))}"
        )
        for media_line in _media_summary(status):
            lines.append(f"-{media_line[1:]}" if media_line.startswith(" ") else f"- {media_line}")
        lines.append(f"- <{status.get('url')}>")
        lines.append("")

    for key in ("status", "tweet"):
        if payload.get(key):
            status_md(payload[key], "##")
    for status in payload.get("thread") or []:
        status_md(status)
    for status in payload.get("replies") or []:
        status_md(status)
    for item in payload.get("results") or []:
        if isinstance(item, dict) and item.get("type") == "profile":
            lines.append(f"### @{item.get('screen_name')} ({item.get('name')})")
            lines.append(f"- followers {_num(item.get('followers'))} / posts {_num(item.get('statuses'))}")
            lines.append(f"- <{item.get('url')}>")
            lines.append("")
        elif isinstance(item, dict):
            status_md(item)
    if payload.get("user"):
        user = payload["user"]
        lines.append(f"## @{user.get('screen_name')} ({user.get('name')})")
        lines.append("")
        lines.append(_clip(user.get("description") or "", text_limit))
        lines.append("")
        lines.append(
            f"- followers {_num(user.get('followers'))} / following {_num(user.get('following'))} / "
            f"posts {_num(user.get('statuses'))}"
        )
        lines.append(f"- <{user.get('url')}>")
        lines.append("")
    for i, trend in enumerate(payload.get("trends") or [], 1):
        lines.append(f"{i}. **{trend.get('name')}** - {trend.get('context')}")
    if not lines:
        lines.append("```json")
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
        lines.append("```")
    return "\n".join(lines).strip() + "\n"


def collect_statuses(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten every status-like object in a payload, including grouped threads."""
    found: List[Dict[str, Any]] = []

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        if item.get("type") == "thread":
            for sub in item.get("statuses") or []:
                visit(sub)
            return
        if item.get("type") in ("status", "substatus"):
            found.append(item)
            return
        # Legacy v1 payloads carry no `type` discriminator.
        if "id" in item and "text" in item and item.get("type") != "tombstone":
            found.append(item)

    for key in ("status", "tweet"):
        visit(payload.get(key))
    for key in ("thread", "replies", "results"):
        for item in payload.get(key) or []:
            visit(item)
    return found


def format_urls(payload: Dict[str, Any]) -> str:
    urls = []
    for status in collect_statuses(payload):
        if status.get("url"):
            urls.append(status["url"])
    for item in payload.get("results") or []:
        if isinstance(item, dict) and item.get("type") == "profile" and item.get("url"):
            urls.append(item["url"])
    if payload.get("user", {}).get("url"):
        urls.append(payload["user"]["url"])
    return "\n".join(dict.fromkeys(urls))


def media_urls(payload: Dict[str, Any], kind: str = "all", best: bool = True) -> List[Tuple[str, str]]:
    """Return (url, suggested_filename) pairs for every media item in a payload."""
    out: List[Tuple[str, str]] = []
    for status in collect_statuses(payload):
        media = status.get("media") or {}
        sid = status.get("id") or "unknown"
        if kind in ("all", "photos"):
            for index, photo in enumerate(media.get("photos") or [], 1):
                url = photo.get("url")
                if not url:
                    continue
                ext = _extension_from_url(url, "jpg")
                out.append((url, f"{sid}_photo{index}.{ext}"))
        if kind in ("all", "videos"):
            for index, video in enumerate(media.get("videos") or [], 1):
                url = video.get("url")
                formats = video.get("formats") or []
                if best and formats:
                    ranked = sorted(formats, key=lambda f: (f.get("bitrate") or 0), reverse=True)
                    url = ranked[0].get("url") or url
                if not url:
                    continue
                ext = _extension_from_url(url, "mp4")
                out.append((url, f"{sid}_video{index}.{ext}"))
        if kind == "all" and media.get("external", {}).get("url"):
            out.append((media["external"]["url"], f"{sid}_external"))
    return out


def _extension_from_url(url: str, default: str) -> str:
    path = urllib.parse.urlparse(url).path
    match = re.search(r"\.([A-Za-z0-9]{2,5})$", path)
    if match:
        return match.group(1).lower()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    fmt = (query.get("format") or [None])[0]
    return (fmt or default).lower()


def select_paths(payload: Any, paths: List[str]) -> Any:
    """Project a payload down to dotted paths. `results[].id` walks each element."""

    def walk(node: Any, parts: List[str]) -> Any:
        if not parts:
            return node
        head, rest = parts[0], parts[1:]
        if head.endswith("[]"):
            key = head[:-2]
            container = node.get(key) if isinstance(node, dict) else None
            if not isinstance(container, list):
                return None
            return [walk(item, rest) for item in container]
        if isinstance(node, list):
            return [walk(item, parts) for item in node]
        if isinstance(node, dict):
            return walk(node.get(head), rest)
        return None

    if len(paths) == 1:
        return walk(payload, paths[0].split("."))
    return {path: walk(payload, path.split(".")) for path in paths}


def render(payload: Dict[str, Any], args: argparse.Namespace) -> str:
    text_limit = None if args.full_text else args.text_limit
    fmt = args.format
    if fmt == "json":
        clean = {k: v for k, v in payload.items() if not k.startswith("__")}
        return json.dumps(clean, ensure_ascii=False, indent=None if args.compact else 2)
    if fmt == "jsonl":
        return "\n".join(json.dumps(s, ensure_ascii=False) for s in collect_statuses(payload))
    if fmt == "md":
        return format_markdown(payload, text_limit)
    if fmt == "urls":
        return format_urls(payload)
    if fmt == "media-urls":
        return "\n".join(url for url, _ in media_urls(payload, args.media_kind, not args.no_best_variant))
    return format_summary(payload, text_limit)


# --------------------------------------------------------------------------- #
# Command implementations
# --------------------------------------------------------------------------- #

def common_query(args: argparse.Namespace, *, lang: bool = False, about: bool = False) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if lang and getattr(args, "lang", None):
        params["lang"] = args.lang
    if about and getattr(args, "about_account", False):
        params["about_account"] = "1"
    return params


def list_params(args: argparse.Namespace, *, lang: bool = True) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if getattr(args, "count", None):
        params["count"] = args.count
    if getattr(args, "cursor", None):
        params["cursor"] = args.cursor
    if lang and getattr(args, "lang", None):
        params["lang"] = args.lang
    return params


_ITEM_KEYS = ("results", "trends", "thread", "replies")


def _looks_empty(payload: Dict[str, Any]) -> bool:
    """True for a payload that carries a list container which came back empty.

    The upstream guest-token session occasionally yields an empty timeline or a
    404 for a query that succeeds moments later, so an empty list is worth one
    or two cheap retries before it is reported as a real result.
    """
    if payload.get("__no_content__"):
        return False
    for key in _ITEM_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            if value:
                return False
            if payload.get("status") or payload.get("user") or payload.get("tweet"):
                return False
            return True
    return False


def run_command(args: argparse.Namespace, client: FxClient) -> Dict[str, Any]:
    cmd = args.command
    pages = args.pages if not args.all_pages else max(args.pages, 1000)
    max_items = args.max_items
    retry_empty = max(0, getattr(args, "retry_empty", 0))

    def _with_empty_retry(fetch) -> Dict[str, Any]:
        payload = fetch()
        attempts = 0
        while attempts < retry_empty and _looks_empty(payload):
            attempts += 1
            if args.verbose:
                print(f"[fxtwitter] empty payload, retry {attempts}/{retry_empty}", file=sys.stderr)
            time.sleep(0.6 * attempts)
            payload = fetch()
        return payload

    def single(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        def fetch() -> Dict[str, Any]:
            status, payload = client.get(path, params)
            if payload is None:
                return {"__http_status__": status, "__no_content__": True}
            payload["__http_status__"] = status
            return payload
        return _with_empty_retry(fetch)

    def listing(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return _with_empty_retry(
            lambda: client.paginate(path, params, pages=pages, max_items=max_items)
        )

    if cmd == "status":
        return single(f"/2/status/{parse_status_id(args.target)}",
                      common_query(args, lang=True, about=True))
    if cmd == "thread":
        return single(f"/2/thread/{parse_status_id(args.target)}",
                      common_query(args, lang=True, about=True))
    if cmd == "conversation":
        params = common_query(args, lang=True, about=True)
        params["ranking_mode"] = args.ranking_mode
        if args.cursor:
            params["cursor"] = args.cursor
        # Replies paginate under `replies`, not `results`.
        return _with_empty_retry(lambda: client.paginate(
            f"/2/conversation/{parse_status_id(args.target)}",
            params, pages=pages, max_items=max_items, items_key="replies",
        ))
    if cmd == "reposts":
        return listing(f"/2/status/{parse_status_id(args.target)}/reposts", list_params(args, lang=False))
    if cmd == "quotes":
        return listing(f"/2/status/{parse_status_id(args.target)}/quotes", list_params(args))
    if cmd == "profile":
        return single(f"/2/profile/{parse_handle(args.target)}", common_query(args, about=True))
    if cmd == "about":
        return single(f"/2/profile/{parse_handle(args.target)}/about", {})
    if cmd == "statuses":
        params = list_params(args)
        if args.since is not None:
            params["since"] = args.since
        if args.with_replies:
            params["with_replies"] = "1"
        if args.group_threads:
            params["groupthreads"] = "1"
        return listing(f"/2/profile/{parse_handle(args.target)}/statuses", params)
    if cmd == "articles":
        return listing(f"/2/profile/{parse_handle(args.target)}/articles", list_params(args))
    if cmd == "media":
        return listing(f"/2/profile/{parse_handle(args.target)}/media", list_params(args))
    if cmd == "followers":
        return listing(f"/2/profile/{parse_handle(args.target)}/followers", list_params(args, lang=False))
    if cmd == "following":
        return listing(f"/2/profile/{parse_handle(args.target)}/following", list_params(args, lang=False))
    if cmd == "search":
        params = list_params(args)
        params["q"] = args.query
        params["feed"] = args.feed
        return listing("/2/search", params)
    if cmd == "search-users":
        params = list_params(args)
        params["q"] = args.query
        return listing("/2/search/users", params)
    if cmd == "typeahead":
        params: Dict[str, Any] = {"q": args.query}
        if args.result_type:
            params["result_type"] = args.result_type
        if args.src:
            params["src"] = args.src
        return single("/2/typeahead", params)
    if cmd == "trends":
        return single("/2/trends", {"type": args.type, "count": args.count})
    if cmd == "spec":
        return single("/2/openapi.json", {})
    if cmd == "get":
        params = dict(pair.split("=", 1) for pair in args.param) if args.param else {}
        return single(args.path, params)
    if cmd == "v1":
        handle = parse_handle(args.handle) if args.handle else None
        if args.status:
            sid = parse_status_id(args.status)
            path = f"/{handle}/status/{sid}" if handle else f"/status/{sid}"
            if args.translate:
                path += f"/{args.translate}"
        else:
            if not handle:
                raise FxError("v1 needs either --status or a handle", EXIT_USAGE)
            path = f"/{handle}"
        return single(path, {})
    raise FxError(f"unknown command {cmd!r}", EXIT_USAGE)


def download_media(args: argparse.Namespace, client: FxClient) -> int:
    """Fetch a status (or a whole timeline) and save its media files to disk."""
    if args.from_timeline:
        payload = client.paginate(
            f"/2/profile/{parse_handle(args.target)}/media",
            {"count": args.count} if args.count else {},
            pages=args.pages, max_items=args.max_items,
        )
    else:
        _, payload = client.get(f"/2/status/{parse_status_id(args.target)}", {})
        payload = payload or {}

    pairs = media_urls(payload, args.media_kind, not args.no_best_variant)
    if not pairs:
        print("no media found", file=sys.stderr)
        return EXIT_OK

    out_dir = os.path.abspath(args.out_dir)
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    for url, filename in pairs:
        target = os.path.join(out_dir, filename)
        if args.dry_run:
            print(f"{url} -> {target}")
            continue
        request = urllib.request.Request(url, headers={"User-Agent": client.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=client.timeout) as response, open(target, "wb") as handle:
                handle.write(response.read())
            print(f"saved {target}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"failed {url}: {exc}", file=sys.stderr)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["summary", "json", "jsonl", "md", "urls", "media-urls"],
                        default=os.environ.get("FXTWITTER_FORMAT", "summary"),
                        help="output format (default: summary, the most token-efficient)")
    common.add_argument("--raw", action="store_true", help="alias for --format json")
    common.add_argument("--compact", action="store_true", help="single-line JSON when --format json")
    common.add_argument("--select", action="append", default=[], metavar="PATH",
                        help="project the payload to a dotted path, e.g. results[].id (repeatable)")
    common.add_argument("--text-limit", type=int, default=600,
                        help="truncate post text in summary/md output (default 600, 0 disables)")
    common.add_argument("--full-text", action="store_true", help="never truncate post text")
    common.add_argument("--out", metavar="FILE", help="write output to FILE instead of stdout")
    common.add_argument("--base-url", default=os.environ.get("FXTWITTER_API_BASE", DEFAULT_BASE),
                        help="API host, e.g. a self-hosted instance or https://api.fxbsky.app")
    common.add_argument("--user-agent", default=os.environ.get("FXTWITTER_USER_AGENT", DEFAULT_UA),
                        help="User-Agent header (required by the API)")
    common.add_argument("--timeout", type=float, default=float(os.environ.get("FXTWITTER_TIMEOUT", DEFAULT_TIMEOUT)))
    common.add_argument("--retries", type=int, default=3)
    common.add_argument("--sleep", type=float, default=0.2, help="delay between paginated requests")
    common.add_argument("--pages", type=int, default=1, help="number of pages to fetch (list endpoints)")
    common.add_argument("--all", dest="all_pages", action="store_true",
                        help="follow cursors until exhausted (use with --max-items)")
    common.add_argument("--max-items", type=int, default=None, help="stop after N accumulated items")
    common.add_argument("--retry-empty", type=int, default=2,
                        help="re-request when a list endpoint returns nothing "
                             "(the upstream guest session is occasionally flaky); 0 disables")
    common.add_argument("--media-kind", choices=["all", "photos", "videos"], default="all")
    common.add_argument("--no-best-variant", action="store_true",
                        help="keep the default video URL instead of the highest-bitrate variant")
    common.add_argument("-v", "--verbose", action="store_true", help="log requests to stderr")

    listing = argparse.ArgumentParser(add_help=False)
    listing.add_argument("--count", type=int, help="page size hint, 1-100 (the API may return more)")
    listing.add_argument("--cursor", help="start from a cursor returned by a previous call")

    lang = argparse.ArgumentParser(add_help=False)
    lang.add_argument("--lang", help="translate post text into this language (e.g. ja, en, es, zh-cn)")

    about = argparse.ArgumentParser(add_help=False)
    about.add_argument("--about-account", action="store_true",
                       help="include the About This Account block on the author")

    parser = argparse.ArgumentParser(
        prog="fxtwitter.py",
        description="Command line client for the FxTwitter API v2 (X/Twitter data, no API key).",
        epilog="Docs: references/endpoints.md. MIT licensed.",
    )
    parser.add_argument("--version", action="version", version=f"fxtwitter.py {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, help_text: str, parents: List[argparse.ArgumentParser]):
        return sub.add_parser(name, help=help_text, parents=[common] + parents, description=help_text)

    p = add("status", "GET /2/status/{id} - one post", [lang, about])
    p.add_argument("target", help="snowflake id or any x.com / fxtwitter.com permalink")

    p = add("thread", "GET /2/thread/{id} - a post plus its author's thread", [lang, about])
    p.add_argument("target")

    p = add("conversation", "GET /2/conversation/{id} - thread plus replies from others", [lang, about, listing])
    p.add_argument("target")
    p.add_argument("--ranking-mode", choices=["likes", "recency"], default="likes")

    p = add("reposts", "GET /2/status/{id}/reposts - users who reposted", [listing])
    p.add_argument("target")

    p = add("quotes", "GET /2/status/{id}/quotes - posts quoting this one", [lang, listing])
    p.add_argument("target")

    p = add("profile", "GET /2/profile/{handle} - user profile", [about])
    p.add_argument("target", help="@handle, handle, profile URL, or id:<numeric id>")

    p = add("about", "GET /2/profile/{handle}/about - About This Account block only", [])
    p.add_argument("target")

    p = add("statuses", "GET /2/profile/{handle}/statuses - user timeline", [lang, listing])
    p.add_argument("target")
    p.add_argument("--since", type=float,
                   help="unix seconds (ms if >= 1e12); exits 4 when nothing is newer")
    p.add_argument("--with-replies", action="store_true", help="include the user's replies")
    p.add_argument("--group-threads", action="store_true",
                   help="group consecutive self-replies into thread entries")

    p = add("articles", "GET /2/profile/{handle}/articles - long-form articles", [lang, listing])
    p.add_argument("target")

    p = add("media", "GET /2/profile/{handle}/media - posts with media", [lang, listing])
    p.add_argument("target")

    p = add("followers", "GET /2/profile/{handle}/followers", [listing])
    p.add_argument("target")

    p = add("following", "GET /2/profile/{handle}/following", [listing])
    p.add_argument("target")

    p = add("search", "GET /2/search - search posts", [lang, listing])
    p.add_argument("query", help="X search query, max 512 chars (supports from:, since:, filter: ...)")
    p.add_argument("--feed", choices=["latest", "top", "media"], default="latest")

    p = add("search-users", "GET /2/search/users - search accounts (People tab)", [lang, listing])
    p.add_argument("query")

    p = add("typeahead", "GET /2/typeahead - autocomplete users, topics and events", [])
    p.add_argument("query")
    p.add_argument("--result-type", help="comma-separated: events,users,topics")
    p.add_argument("--src", help="upstream src hint (default search_box)")

    p = add("trends", "GET /2/trends - trending topics", [])
    p.add_argument("--type", default="trending", choices=["trending"])
    p.add_argument("--count", type=int, default=20, help="1-50")

    add("spec", "GET /2/openapi.json - live OpenAPI 3.0 specification", [])

    p = add("get", "call an arbitrary path on the API host (escape hatch)", [])
    p.add_argument("path", help="e.g. /2/status/20 or a full URL")
    p.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")

    p = add("v1", "legacy v1 routes, kept for backward compatibility", [])
    p.add_argument("handle", nargs="?", help="handle for /{handle} or /{handle}/status/{id}")
    p.add_argument("--status", help="status id or URL")
    p.add_argument("--translate", metavar="LANG", help="v1 translation suffix, e.g. ja")

    p = add("download", "download the media attached to a post or a media timeline", [listing])
    p.add_argument("target", help="status id/URL, or a handle when --from-timeline is set")
    p.add_argument("--out-dir", default="./fxtwitter-media")
    p.add_argument("--from-timeline", action="store_true",
                   help="treat target as a handle and pull from /2/profile/{handle}/media")
    p.add_argument("--dry-run", action="store_true", help="print URLs instead of downloading")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "raw", False):
        args.format = "json"
    if getattr(args, "text_limit", None) == 0:
        args.full_text = True

    client = FxClient(
        base_url=args.base_url,
        user_agent=args.user_agent,
        timeout=args.timeout,
        retries=args.retries,
        sleep_between=args.sleep,
        verbose=args.verbose,
    )

    try:
        if args.command == "download":
            return download_media(args, client)

        payload = run_command(args, client)

        if args.select:
            projected = select_paths(payload, args.select)
            text = json.dumps(projected, ensure_ascii=False, indent=None if args.compact else 2)
        else:
            text = render(payload, args)

        if args.out:
            with io.open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(text)

        if payload.get("__no_content__"):
            return EXIT_NO_CONTENT
        code = payload.get("code")
        if isinstance(code, int) and not (200 <= code < 300):
            return EXIT_API_ERROR
        return EXIT_OK
    except FxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
