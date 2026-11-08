from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import aiohttp

from bot.logger import get_logger

logger = get_logger(__name__)

# Matches twitter.com / x.com / mobile.twitter.com status links, with or
# without query strings, http/https, www.
_X_LINK_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)/(?P<user>\w{1,15})/status/(?P<tweet_id>\d+)",
    re.IGNORECASE,
)

_OEMBED_URL = "https://publish.twitter.com/oembed"
_AUTHOR_URL_RE = re.compile(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,15})", re.IGNORECASE)


@dataclass(frozen=True)
class XLink:
    # username is None for "/i/status/..." links, where X itself doesn't
    # expose the poster's handle in the URL. These are still valid, trackable
    # submissions - process_link_submission() will try to resolve the real
    # username via resolve_username_from_tweet() before falling back to
    # treating it as unresolved.
    username: Optional[str]
    tweet_id: str
    canonical_url: str


def extract_x_link(text: str | None) -> Optional[XLink]:
    """Extracts the first valid X/Twitter status link from free text.

    Handles both link forms:
      - https://x.com/<username>/status/<id>   (username known)
      - https://x.com/i/status/<id>             (username unknown)

    Returns None if no valid link is present.
    """
    if not text:
        return None
    match = _X_LINK_RE.search(text)
    if not match:
        return None
    raw_user = match.group("user")
    tweet_id = match.group("tweet_id")

    if raw_user.lower() == "i":
        return XLink(username=None, tweet_id=tweet_id, canonical_url=f"https://x.com/i/status/{tweet_id}")

    return XLink(
        username=raw_user,
        tweet_id=tweet_id,
        canonical_url=f"https://x.com/{raw_user}/status/{tweet_id}",
    )


def contains_x_link(text: str | None) -> bool:
    return extract_x_link(text) is not None


async def resolve_username_from_tweet(tweet_id: str) -> Optional[str]:
    """Best-effort lookup of the poster's X username for an "/i/status/<id>"
    link, using X/Twitter's public oEmbed endpoint (no API key required).

    This is the only way to recover a username from a link that doesn't
    include one. It depends on the tweet being public and X's oEmbed
    endpoint being reachable, so it can legitimately fail (deleted/private
    tweet, rate limiting, network issues) - callers must treat None as
    "couldn't resolve it" rather than an error.
    """
    url = f"https://twitter.com/i/status/{tweet_id}"
    params = {"url": url, "omit_script": "1"}
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_OEMBED_URL, params=params) as resp:
                if resp.status != 200:
                    logger.info("oEmbed lookup for tweet %s returned status %s", tweet_id, resp.status)
                    return None
                data = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        logger.info("oEmbed lookup failed for tweet %s", tweet_id, exc_info=True)
        return None

    author_url = data.get("author_url", "") if isinstance(data, dict) else ""
    match = _AUTHOR_URL_RE.search(author_url)
    if not match:
        return None
    return match.group(1)
