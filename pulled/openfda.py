"""Client for the openFDA food enforcement endpoint.

No API key. openFDA allows 240 requests per minute and 1000 per day to
anonymous callers, so every response is cached on disk and the cache is the
normal path, not an optimisation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from . import match
from .recall import Recall

ENDPOINT = "https://api.fda.gov/food/enforcement.json"
CACHE = Path.home() / ".cache" / "pulled" / "openfda"
CACHE_TTL = timedelta(hours=6)
USER_AGENT = "pulled/0.1 (+https://github.com/thibaudlepan77-svg/pulled)"
# A miss costs up to two requests per word on top of the first, against a
# daily allowance of a thousand. The one word checks repeat across sentences
# and come from the cache, the rest do not. A sentence longer than this is not
# retried at all, and costs one request.
RETRY_WORDS = 8


class OpenFdaUnavailable(RuntimeError):
    pass


def _parse_day(raw: str) -> date:
    return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))


def _to_recall(record: dict) -> Recall:
    return Recall(
        number=record.get("recall_number", ""),
        initiated=_parse_day(record["recall_initiation_date"]),
        product=record.get("product_description", ""),
        reason=record.get("reason_for_recall", ""),
        status=record.get("status", ""),
        classification=record.get("classification", ""),
        firm=record.get("recalling_firm", ""),
        country=record.get("country", ""),
        distribution=record.get("distribution_pattern", ""),
        lot_codes=record.get("code_info", ""),
        agency="FDA",
    )


def _cache_path(query: str) -> Path:
    safe = urllib.parse.quote(query, safe="")
    if len(safe) > 150:
        # Cut at 150, a five word search and the same search without its last
        # word shared a file, so a retry read the empty answer it was retrying.
        safe = safe[:120] + "-" + hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    return CACHE / f"{safe}.json"


def _query_string(params: dict) -> str:
    # openFDA reads +, :, [ ] and quotes as search syntax. urlencode escapes the
    # plus into %2B and the service answers 500, so the search value is quoted
    # by hand and only the rest goes through the standard encoder.
    parts = []
    for key, value in params.items():
        if key == "search":
            parts.append("search=" + urllib.parse.quote(str(value), safe=':[]+"()*'))
        else:
            parts.append(urllib.parse.urlencode({key: value}))
    return "&".join(parts)


def _fetch(params: dict) -> dict:
    query = _query_string(params)
    cached = _cache_path(query)
    if cached.exists():
        age = time.time() - cached.stat().st_mtime
        if age < CACHE_TTL.total_seconds():
            return json.loads(cached.read_text(encoding="utf-8"))

    request = urllib.request.Request(f"{ENDPOINT}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as failure:
        # 404 from openFDA means the search matched nothing, not that the
        # service is down. It is the only status we translate into data.
        if failure.code == 404:
            payload = {"meta": {"results": {"total": 0}}, "results": []}
        else:
            raise OpenFdaUnavailable(f"openFDA returned {failure.code}") from failure
    except OSError as failure:
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        raise OpenFdaUnavailable(str(failure)) from failure

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def since(day: date, limit: int = 100, country: str = "United States") -> list[Recall]:
    # openFDA reads a plus as the space of its own query language.
    search = f'report_date:[{day:%Y%m%d}+TO+{date.today():%Y%m%d}]'
    if country:
        search += '+AND+country:"' + country.replace(" ", "+") + '"'
    payload = _fetch({"search": search, "limit": limit, "sort": "report_date:desc"})
    return [_to_recall(record) for record in payload.get("results", [])]


def _every_word(words: list[str], limit: int) -> list[Recall]:
    search = "+AND+".join(f"product_description:{w}" for w in words)
    payload = _fetch({"search": search, "limit": limit, "sort": "report_date:desc"})
    return [_to_recall(record) for record in payload.get("results", [])]


def _in_feed(word: str) -> bool:
    try:
        return bool(_fetch({"search": f"product_description:{word}", "limit": 1}).get("results"))
    except OpenFdaUnavailable as failure:
        # A refused word is no evidence the word is absent, so it stays in the
        # search. Being throttled is different, and it is not hidden.
        if "429" in str(failure):
            raise
        return True


def search_product(terms: str, limit: int = 50) -> list[Recall]:
    # Only words a label could carry. A caller says `is this Lord's ice cream
    # recalled`, and this and recalled are on no pack, so every search holding
    # either of them comes back empty.
    # Letters, digits and the apostrophe of Loard's. A slash or an ampersand
    # left inside a word makes openFDA answer 500 for the whole search.
    words = [w.strip("'") for w in re.sub(r"[^\w']+", " ", terms).split()]
    words = [w for w in words
             if len(w) > 2 and not set(match.tokens(w)) <= match.FILLER | match.SPOKEN]
    if not words:
        return []
    found = _every_word(words, limit)
    if found or len(words) > RETRY_WORDS:
        return found
    # The search requires every word and openFDA has no fuzzy search, so one
    # word the label does not carry empties the whole answer. Speech makes that
    # common twice over. A transcriber writes Lord's for Loard's, a word no
    # record in the feed contains, and a client adds flavor, a word the feed
    # knows and this label does not. The first kind is dropped outright, then
    # each remaining word takes its turn being the one left out. What comes back
    # is ranked by how many of the caller's words each record carries and
    # capped, as the USDA side does.
    known = [word for word in words if _in_feed(word)]
    if known != words and known:
        found = _every_word(known, limit)
        if found:
            return found
    if not 2 <= len(known) <= RETRY_WORDS:
        return []
    pooled = {}
    for skipped in range(len(known)):
        for recall in _every_word(known[:skipped] + known[skipped + 1:], limit):
            pooled.setdefault(recall.number, recall)
    asked = {token for word in words for token in match.tokens(word)}

    def carried(recall: Recall) -> int:
        return len(asked & set(match.tokens(f"{recall.product} {recall.firm}")))

    return sorted(pooled.values(), key=carried, reverse=True)[:limit]
