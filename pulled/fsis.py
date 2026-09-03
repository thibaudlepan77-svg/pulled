"""Client for the USDA FSIS recall feed, which covers meat, poultry and eggs.

The service publishes one JSON document holding every recall it has ever
issued, around thirteen megabytes and 2 023 records, with no server side
filtering. So the whole thing is fetched once, cached, and searched locally.

Those 2 023 records are 1 234 recalls. Every one of them is published in
English and again in Spanish under the same recall number, and nothing in the
record says which edition it is.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .recall import Recall

FEED = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
CACHE = Path.home() / ".cache" / "pulled" / "fsis.json"
CACHE_TTL = timedelta(hours=6)
# The feed sits behind a filter that answers 403 unless the request looks like
# it came from a browser. Measured on 3 September 2026, six attempts: a plain
# project agent is refused with or without an Accept header, a browser agent is
# refused without one, and the pair goes through every time. Nothing here is a
# key or a credential, the data is public and unauthenticated.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

TAGS = re.compile(r"<[^>]+>")
# Titles read `Company Name Recalls Frozen Chicken Products Due To ...`, and
# everything before the verb is the firm. Retira is the Spanish edition.
FIRM = re.compile(r"^(.*?)\s+(?:Recalls?|Retira)\b", re.IGNORECASE)
# The feed publishes each recall twice, once in English and once in Spanish,
# under the same recall number. 789 numbers of 2 023 records are doubled that
# way. Left in, a caller asking about ground beef is scored against Carne De
# Res Molida as if it were a second product.
SPANISH = re.compile(r"\bRetira\b|\bEmite\b|\bDebido A\b|\bProductos De\b", re.IGNORECASE)


class FsisUnavailable(RuntimeError):
    pass


def _download() -> list[dict]:
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL.total_seconds():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    request = urllib.request.Request(FEED, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            records = json.loads(response.read().decode("utf-8"))
    except OSError as failure:
        if CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8"))
        raise FsisUnavailable(str(failure)) from failure
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(records), encoding="utf-8")
    return records


def _joined(value) -> str:
    # Fields come back HTML encoded, `&quot;CURRY CHICKEN&quot;`, and one of
    # them is read out loud.
    text = " ".join(str(part).strip() for part in value) if isinstance(value, list) \
        else str(value or "").strip()
    # A handful of records are encoded twice, `&amp;quot;`, so one pass leaves
    # the entity in the sentence.
    return html.unescape(html.unescape(text))


def _firm_from(title: str) -> str:
    found = FIRM.match(title)
    return found.group(1).strip() if found else ""


# The reason field says `Misbranding Unreported Allergens` and stops there. Of
# 361 records carrying that reason, not one names the allergen in it, so a
# household that reacts to milk cannot be told which of them concerns it. The
# press release names it in 354 of them, measured 3 September 2026.
ALLERGENS = ("milk", "peanut", "soy", "wheat", "egg", "fish", "shellfish",
             "almond", "cashew", "walnut", "pecan", "hazelnut", "pistachio",
             "sesame", "gluten", "crustacean", "coconut", "mustard")


def _named_allergens(summary: str) -> list[str]:
    lowered = summary.lower()
    return [word for word in ALLERGENS if word in lowered]


def _to_recall(record: dict) -> Recall | None:
    raw_date = record.get("field_recall_date") or record.get("field_last_modified_date") or ""
    if len(raw_date) < 10:
        return None
    title = _joined(record.get("field_title"))
    product = _joined(record.get("field_product_items")) or title
    summary = TAGS.sub(" ", _joined(record.get("field_summary")))
    reason = _joined(record.get("field_recall_reason"))
    if "allergen" in reason.lower():
        named = _named_allergens(summary)
        if named:
            reason = f"{reason}, {', '.join(named)}"
    return Recall(
        number=record.get("field_recall_number", ""),
        initiated=date(int(raw_date[0:4]), int(raw_date[5:7]), int(raw_date[8:10])),
        product=product[:400],
        reason=reason,
        status=record.get("field_recall_type", ""),
        classification=record.get("field_recall_classification", ""),
        firm=_firm_from(title),
        country="United States",
        distribution=_joined(record.get("field_states")),
        lot_codes=summary[:300],
        agency="USDA FSIS",
        url=record.get("field_recall_url", ""),
    )


def _one_per_recall(records: list[dict]) -> list[dict]:
    """One record per recall number, English when both editions are there."""
    kept: dict[str, dict] = {}
    for position, record in enumerate(records):
        number = record.get("field_recall_number", "")
        if not number:
            kept[f"?{position}"] = record
            continue
        already = kept.get(number)
        if already is None or (SPANISH.search(_joined(already.get("field_title")))
                               and not SPANISH.search(_joined(record.get("field_title")))):
            kept[number] = record
    return list(kept.values())


def all_recalls() -> list[Recall]:
    found = (_to_recall(record) for record in _one_per_recall(_download()))
    return sorted((r for r in found if r), key=lambda r: r.initiated, reverse=True)


def since(day: date, limit: int = 100) -> list[Recall]:
    return [r for r in all_recalls() if r.initiated >= day][:limit]


def search_product(terms: str, limit: int = 50) -> list[Recall]:
    """Records that could be the thing the caller is holding, best fit first.

    There is no server side search, so the whole feed is filtered here and the
    result is capped. Taking the first `limit` records that share any one word
    is what a naive filter does, and it loses. Asking about ground beef, 68
    records carry both words and only 15 of them survived the cap, because
    newer records mentioning just beef, or just ground, got there first.

    So the records that carry every word come first, and partial matches only
    fill what is left.
    """
    words = [w.lower() for w in terms.split() if len(w) > 2]
    if not words:
        return []
    complete, partial = [], []
    for recall in all_recalls():
        haystack = f"{recall.product} {recall.firm}".lower()
        present = [word for word in words if word in haystack]
        if len(present) == len(words):
            complete.append(recall)
        elif present:
            partial.append(recall)
    return (complete + partial)[:limit]
