"""Client for the openFDA food enforcement endpoint.

No API key. openFDA allows 240 requests per minute and 1000 per day to
anonymous callers, so every response is cached on disk and the cache is the
normal path, not an optimisation.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ENDPOINT = "https://api.fda.gov/food/enforcement.json"
CACHE = Path.home() / ".cache" / "pulled" / "openfda"
CACHE_TTL = timedelta(hours=6)
USER_AGENT = "pulled/0.1 (+https://github.com/thibaudlepan77-svg/pulled)"


class OpenFdaUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Recall:
    number: str
    initiated: date
    product: str
    reason: str
    status: str
    classification: str
    firm: str
    country: str
    distribution: str
    lot_codes: str

    @property
    def ongoing(self) -> bool:
        return self.status.lower() == "ongoing"


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
    )


def _cache_path(query: str) -> Path:
    safe = urllib.parse.quote(query, safe="")[:150]
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


def search_product(terms: str, limit: int = 50) -> list[Recall]:
    words = [w for w in terms.replace('"', " ").split() if len(w) > 2]
    if not words:
        return []
    search = "+AND+".join(f"product_description:{w}" for w in words)
    payload = _fetch({"search": search, "limit": limit, "sort": "report_date:desc"})
    return [_to_recall(record) for record in payload.get("results", [])]
