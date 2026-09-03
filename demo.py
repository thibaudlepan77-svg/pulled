"""Play a kitchen conversation through the server, for a screen recording.

    python demo.py                 live openFDA data
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

from pulled import openfda, server

CONVERSATION = [
    ("set_allergens", {"allergens": ["peanuts", "milk"]},
     "First, tell it what this household reacts to."),
    ("check_item", {"description": "dark chocolate coconut almond bites"},
     "Someone is holding a pouch and reads the front of it out loud."),
    ("check_item", {"description": "tomato sauce"},
     "Now something vague. The server asks one question and settles it."),
    ("check_item", {"description": "cheddar crackers from the corner shop"},
     "And something that is simply not in the feed."),
    ("recent_recalls", {"days": 45},
     "Finally, what has been pulled lately that touches this household."),
]

FIXTURES = [
    openfda.Recall(
        number="F-0918-2026", initiated=date(2026, 5, 23),
        product="Dark Chocolate Coconut Almond Bites, 3.17oz, Plastic Pouch",
        reason="Undeclared peanuts", status="Ongoing", classification="Class I",
        firm="Bazzini LLC", country="United States", distribution="Nationwide",
        lot_codes="Lot 4471, best by 12/2026"),
    openfda.Recall(
        number="F-1102-2026", initiated=date(2026, 7, 23),
        product="Vodka Tomato Sauce, NET WT. 24 oz / 680g, glass jar",
        reason="Label declares cream and cheese, but Milk is not declared",
        status="Ongoing", classification="Class II", firm="Sheandro LLC",
        country="United States", distribution="NY, NJ, CT", lot_codes="0725"),
]


def offline():
    openfda.search_product = lambda terms, limit=50: list(FIXTURES)
    openfda.since = lambda day, limit=100, country="United States": list(FIXTURES)


# The person in the kitchen, standing in for a real client. When the server
# asks a question through elicitation, this is what answers it.
KITCHEN_REPLIES = {"vodka": "vodka"}


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
            print(f"  -> {tool}({json.dumps(arguments)[:70]})")
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
