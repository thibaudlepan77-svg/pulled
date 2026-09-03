"""Play a kitchen conversation through the server, for a screen recording.

    python demo.py                 the live FDA and USDA feeds
    python demo.py --offline       fixed records, for a repeatable take

Everything goes through the MCP protocol on an in-memory stream pair, so what
you see is what a client would get, and no port is opened.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date

import mcp.types as types
from mcp.shared.memory import create_connected_server_and_client_session

from pulled import openfda, server, sources

CONVERSATION = [
    ("set_allergens", {"allergens": ["peanuts", "milk"]},
     "First, tell it what this household reacts to."),
    ("check_item", {"description": "dark chocolate coconut almond bites"},
     "Someone is holding a pouch and reads the front of it out loud."),
    ("check_item", {"description": "loard's ice cream"},
     "Now a tub. The FDA published forty-three Loard's flavours on one day,\n"
     "four of them below, each with its own allergens. The name on the lid\n"
     "cannot answer, so the server asks and settles it."),
    ("check_item", {"description": "power plate meals meatloaf with garlic mashed potatoes"},
     "Now the freezer. Meat, poultry and eggs belong to the USDA, not the FDA,\n"
     "so a checker wired to one feed is silent here."),
    ("check_item", {"description": "cheddar crackers from the corner shop"},
     "And something that is simply not in either feed."),
    ("recent_recalls", {"days": 150},
     "Finally, what has been pulled lately that touches this household."),
]

# Wording, dates and reasons copied from the records named below, five from
# openFDA and one from the USDA, so a viewer can pull the same rows from the
# public endpoints and check them.
FIXTURES = [
    openfda.Recall(
        number="H-1228-2026", initiated=date(2026, 5, 23),
        product="Dark Chocolate Coconut Almond Bites, 3.17oz, Plastic Pouches",
        reason="Undeclared peanuts", status="Ongoing", classification="Class I",
        firm="Bazzini LLC", country="United States", distribution="Nationwide",
        lot_codes="Lot 4471, best by 12/2026"),
    openfda.Recall(
        number="H-0743-2026", initiated=date(2026, 4, 15),
        product="Loard's Peanut Butter Fudge Ice Cream - 32 oz",
        reason="Undeclared Milk, Peanuts", status="Ongoing",
        classification="Class II", firm="Silver Moon LP dba Loard's Ice Cream",
        country="United States", distribution="Northern California",
        lot_codes=""),
    openfda.Recall(
        number="H-0746-2026", initiated=date(2026, 4, 15),
        product="Loard's Pistachio Ice Cream - 32 oz",
        reason="Undeclared Milk, Pistachios, Yellow #5, Blue #1",
        status="Ongoing", classification="Class II",
        firm="Silver Moon LP dba Loard's Ice Cream",
        country="United States", distribution="Northern California",
        lot_codes=""),
    openfda.Recall(
        number="H-0750-2026", initiated=date(2026, 4, 15),
        product="Loard's Rocky Road Ice Cream - 56 oz",
        reason="Undeclared Milk, Walnuts, Eggs", status="Ongoing",
        classification="Class II", firm="Silver Moon LP dba Loard's Ice Cream",
        country="United States", distribution="Northern California",
        lot_codes=""),
    openfda.Recall(
        number="H-0730-2026", initiated=date(2026, 4, 15),
        product="Loard's Coconut Pineapple Ice Cream - 32 oz; 56 oz",
        reason="Undeclared Milk", status="Ongoing", classification="Class II",
        firm="Silver Moon LP dba Loard's Ice Cream", country="United States",
        distribution="Northern California", lot_codes=""),
    openfda.Recall(
        number="008-2026", initiated=date(2026, 6, 18),
        product='13.3-oz. vacuum sealed plastic tray packages containing '
                '"POWER PLATE MEALS MEATLOAF WITH GARLIC MASHED POTATOES"',
        reason="Unreported Allergens, milk", status="Active Recall",
        classification="Class II", firm="Power Plate Meals, LLC",
        country="United States", distribution="Minnesota North Dakota South Dakota",
        lot_codes="", agency="USDA FSIS"),
]


def offline():
    sources.search_product = lambda terms, limit=50: list(FIXTURES)
    sources.since = lambda day, limit=100, country="United States": list(FIXTURES)


# The person in the kitchen, standing in for a real client. When the server
# asks a question through elicitation, this is what answers it.
KITCHEN_REPLIES = {"front of the pack": "peanut butter fudge"}


async def kitchen(context, params):
    for word, reply in KITCHEN_REPLIES.items():
        if word in params.message.lower():
            print(f"  Alexa: {params.message}")
            print(f"  Person: {reply}")
            return types.ElicitResult(action="accept", content={"answer": reply})
    return types.ElicitResult(action="decline")


async def play() -> None:
    async with create_connected_server_and_client_session(
            server.server._mcp_server, elicitation_callback=kitchen) as client:
        listed = await client.list_tools()
        print("tools:", ", ".join(sorted(tool.name for tool in listed.tools)), "\n")
        for tool, arguments, note in CONVERSATION:
            print("─" * 68)
            print(note)
            print(f"  -> {tool}({json.dumps(arguments)})")
            answer = json.loads((await client.call_tool(tool, arguments)).content[0].text)
            if "say" in answer:
                print(f"  Alexa: {answer['say']}")
            if answer.get("ask"):
                print(f"  Alexa: {answer['ask']}")
            if tool == "set_allergens":
                print(f"  stored: {', '.join(answer['allergens'])}")
            if tool == "recent_recalls":
                print(f"  matching this household: {answer['count']}")
                for item in answer["recalls"][:3]:
                    print(f"    - {item['say']}")
            print(f"  [outcome {answer.get('outcome', '-')}"
                  f" confidence {answer.get('confidence', '-')}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    if parser.parse_args().offline:
        offline()
    # The server logs one INFO line per request, which is right for a service
    # and wrong for a screen recording.
    logging.getLogger("mcp").setLevel(logging.WARNING)
    logging.getLogger().setLevel(logging.WARNING)
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(play())
