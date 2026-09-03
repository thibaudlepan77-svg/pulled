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
import re
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from . import match, sources
from .recall import Recall

HOUSEHOLD = Path(os.environ.get("PULLED_HOME", Path.home() / ".config" / "pulled")) / "household.json"

server = FastMCP("pulled", host="127.0.0.1", port=int(os.environ.get("PULLED_PORT", 8931)))


def _household() -> dict:
    if HOUSEHOLD.exists():
        return json.loads(HOUSEHOLD.read_text(encoding="utf-8"))
    return {"allergens": []}


def _save(household: dict) -> None:
    HOUSEHOLD.parent.mkdir(parents=True, exist_ok=True)
    HOUSEHOLD.write_text(json.dumps(household, indent=1), encoding="utf-8")


async def _ask(ctx: Context, question: str) -> str | None:
    """Put one question to the caller through the protocol.

    A client is free not to support elicitation, and an agent client may answer
    on the user's behalf. Both are fine and neither is an error here, so a
    refusal simply leaves the verdict unclear and the question travels back in
    the payload for the caller to ask however it likes.
    """
    try:
        heard = await ctx.elicit(message=question, schema=Clarification)
    except Exception:
        return None
    if heard.action == "accept" and heard.data:
        return heard.data.answer
    return None


def _said_aloud(recall: Recall) -> tuple[str, str]:
    """The product and the maker as a person would name them.

    Two habits of the feed survive into speech badly. Sizes are appended to the
    product with a dash, `Loard's Rocky Road Ice Cream - 56 oz`, and firms are
    filed under their corporate name with the trading name behind a dba,
    `Silver Moon LP dba Loard's Ice Cream`. The tub in the kitchen says neither.
    """
    product = re.split(r" - ", match.spoken_name(recall.product))[0].strip()
    firm = re.split(r"\bdba\b", recall.firm, flags=re.IGNORECASE)[-1].strip()
    return product, firm or recall.firm


def _spoken(recall: Recall) -> str:
    when = recall.initiated.strftime("%d %B %Y")
    danger = recall.reason.rstrip(".")
    product, firm = _said_aloud(recall)
    # Loard's Pistachio Ice Cream from Loard's Ice Cream. The brand is already
    # in the product name often enough that the clause has to earn its place,
    # and 195 of the USDA records carry no firm at all.
    named = match.tokens(firm)
    maker = f" from {firm}" if named and named[0] not in match.tokens(product) else ""
    # An alert is not a recall. 169 of the 1 234 USDA records are alerts, and
    # calling one a recall tells the caller their dinner has been pulled from
    # sale when it has not, which is the wrong alarm this server exists to
    # avoid. openFDA has no alerts and its statuses say ongoing or terminated.
    alert = "alert" in recall.status.lower()
    event = "was covered by a public health alert on" if alert else "was recalled on"
    # The FDA says Ongoing, the USDA says Active Recall, and the second one
    # lands in the sentence as `the recall is active recall`.
    standing = re.sub(r"\s*recall$", "", recall.status.strip(), flags=re.IGNORECASE).lower()
    closing = ("This is a public health alert rather than a recall." if alert
               else f"The recall is {standing}, {recall.classification}.")
    return (f"{product}{maker} {event} {when}. "
            f"The reason given is {danger}. {closing}")


class Clarification(BaseModel):
    answer: str = Field(description="What the person answered, in their own words")


@server.tool()
async def check_item(description: str, ctx: Context | None = None) -> dict:
    """Say whether a food item the caller describes out loud is under recall.

    Pass what the person actually said, in their words. The answer is one of
    recalled, unclear or clear. When it is unclear the server asks one question
    through elicitation and settles the answer itself, because a wrong
    reassurance and a wrong alarm are both harmful. Clients without elicitation
    get the same question back in the payload to ask themselves.
    """
    pool = sources.search_product(description)
    verdict = match.best(description, pool)

    if verdict.outcome == "unclear" and ctx is not None:
        heard = await _ask(ctx, verdict.question)
        if heard:
            description = f"{description} {heard}"
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
        "say": "I found no recall matching that. This only covers what the FDA and "
               "the USDA have published, so it is not a guarantee that the food is safe.",
        "searched": len(pool),
    }


@server.tool()
def recent_recalls(days: int = 14, only_mine: bool = True, limit: int = 8) -> dict:
    """List recalls published in the last few days, newest first.

    With only_mine, the list is narrowed to recalls whose stated reason names
    one of the household allergens.
    """
    found = sources.since(date.today() - timedelta(days=max(days, 1)), limit=100)
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
