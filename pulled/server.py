"""MCP server exposing US food recalls to a voice assistant.

Streamable HTTP, protocol 2025-11-25.

    python -m pulled.server            serve on http://127.0.0.1:8931/mcp
    PULLED_PORT=9000 python -m pulled.server

Every tool answers in a form that can be read aloud without a screen, and none
of them assert a match they cannot defend. `check_item` has three outcomes and
one of them is a question.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import match, openfda

HOUSEHOLD = Path(os.environ.get("PULLED_HOME", Path.home() / ".config" / "pulled")) / "household.json"

server = FastMCP("pulled", host="127.0.0.1", port=int(os.environ.get("PULLED_PORT", 8931)))


def _household() -> dict:
    if HOUSEHOLD.exists():
        return json.loads(HOUSEHOLD.read_text(encoding="utf-8"))
    return {"allergens": []}


def _save(household: dict) -> None:
    HOUSEHOLD.parent.mkdir(parents=True, exist_ok=True)
    HOUSEHOLD.write_text(json.dumps(household, indent=1), encoding="utf-8")


def _spoken(recall: openfda.Recall) -> str:
    when = recall.initiated.strftime("%d %B %Y")
    danger = recall.reason.rstrip(".")
    return (f"{recall.product.split(',')[0].strip()} from {recall.firm} was recalled on "
            f"{when}. The reason given is {danger}. The recall is {recall.status.lower()}, "
            f"{recall.classification}.")


@server.tool()
def check_item(description: str) -> dict:
    """Say whether a food item the caller describes out loud is under recall.

    Pass what the person actually said, in their words. The answer is one of
    recalled, unclear or clear. When it is unclear the reply carries a single
    question to ask back, because a wrong reassurance and a wrong alarm are
    both harmful.
    """
    pool = openfda.search_product(description)
    verdict = match.best(description, pool)
    if verdict.outcome == "recalled":
        return {
            "outcome": "recalled",
            "say": _spoken(verdict.recall),
            "recall_number": verdict.recall.number,
            "ongoing": verdict.recall.ongoing,
            "lot_codes": verdict.recall.lot_codes,
            "confidence": round(verdict.score, 2),
        }
    if verdict.outcome == "unclear":
        return {
            "outcome": "unclear",
            "say": "I found a recall that might be yours, but I am not sure.",
            "ask": verdict.question,
            "candidate": verdict.recall.product,
            "confidence": round(verdict.score, 2),
        }
    return {
        "outcome": "clear",
        "say": "I found no recall matching that. Recalls only cover what the FDA has "
               "published, so this is not a guarantee that the food is safe.",
        "searched": len(pool),
    }


@server.tool()
def recent_recalls(days: int = 14, only_mine: bool = True, limit: int = 8) -> dict:
    """List recalls published in the last few days, newest first.

    With only_mine, the list is narrowed to recalls whose stated reason names
    one of the household allergens.
    """
    found = openfda.since(date.today() - timedelta(days=max(days, 1)), limit=100)
    allergens = [a.lower() for a in _household()["allergens"]]
    if only_mine and allergens:
        found = [r for r in found
                 if any(word in r.reason.lower() for word in allergens)]
    return {
        "count": len(found),
        "filtered_by": allergens if only_mine else [],
        "recalls": [
            {"say": _spoken(r), "recall_number": r.number, "ongoing": r.ongoing}
            for r in found[:limit]
        ],
    }


@server.tool()
def set_allergens(allergens: list[str]) -> dict:
    """Record what this household reacts to, so alerts stay relevant.

    Use the everyday word, peanuts rather than arachis hypogaea, because the
    recall notices are written that way too.
    """
    household = _household()
    household["allergens"] = sorted({a.strip().lower() for a in allergens if a.strip()})
    _save(household)
    return {"allergens": household["allergens"]}


@server.prompt()
def kitchen_check(item: str) -> str:
    return (
        f"The person is holding {item} and wants to know if it is safe to eat. "
        "Call check_item with their exact words. If the outcome is unclear, ask "
        "them the one question in the reply and nothing else, then call check_item "
        "again with their words plus the answer. Read the say field aloud as it "
        "is written, and never turn a clear result into a promise that the food "
        "is safe."
    )


def main() -> None:
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
