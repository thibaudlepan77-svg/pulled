"""Protocol level tests, run over an in-memory pair rather than a socket.

No port is opened, so the suite runs the same way on a laptop and in CI, and a
failing test never leaves a listener behind.
"""

import json
from datetime import date

import pytest
import mcp.types as types
from mcp.shared.memory import create_connected_server_and_client_session

from pulled import openfda, server


def recall(product: str, firm: str, reason: str) -> openfda.Recall:
    return openfda.Recall(
        number="F-0042-2026",
        initiated=date(2026, 5, 23),
        product=product,
        reason=reason,
        status="Ongoing",
        classification="Class I",
        firm=firm,
        country="United States",
        distribution="Nationwide",
        lot_codes="Lot 4471",
    )


BITES = recall("Dark Chocolate Coconut Almond Bites, 3.17oz, Plastic Pouch",
               "Sunridge Farms", "Undeclared peanuts")
SAUCE = recall("Vodka Tomato Sauce, NET WT. 24 oz, glass jar",
               "Nonna Rosa", "Label declares cream and cheese, but Milk is not declared")


def payload(result):
    return json.loads(result.content[0].text)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(openfda, "search_product", lambda terms, limit=50: [BITES, SAUCE])
    monkeypatch.setattr(openfda, "since", lambda day, limit=100, country="United States": [BITES, SAUCE])
    monkeypatch.setattr(server, "HOUSEHOLD", tmp_path / "household.json")


@pytest.mark.anyio
async def test_the_server_advertises_its_tools(offline):
    async with create_connected_server_and_client_session(server.server._mcp_server) as client:
        listed = await client.list_tools()
    assert {tool.name for tool in listed.tools} == {"check_item", "recent_recalls", "set_allergens"}


@pytest.mark.anyio
async def test_a_named_product_comes_back_recalled_with_a_line_to_read_out(offline):
    async with create_connected_server_and_client_session(server.server._mcp_server) as client:
        answer = payload(await client.call_tool(
            "check_item", {"description": "dark chocolate coconut almond bites"}))
    assert answer["outcome"] == "recalled"
    assert "Sunridge Farms" in answer["say"]
    assert answer["recall_number"] == "F-0042-2026"


@pytest.mark.anyio
async def test_a_vague_product_comes_back_with_a_question_and_no_verdict(offline):
    async with create_connected_server_and_client_session(server.server._mcp_server) as client:
        answer = payload(await client.call_tool("check_item", {"description": "tomato sauce"}))
    assert answer["outcome"] == "unclear"
    assert answer["ask"]
    assert "say" in answer and "recall_number" not in answer


@pytest.mark.anyio
async def test_a_clear_result_refuses_to_promise_safety(offline):
    async with create_connected_server_and_client_session(server.server._mcp_server) as client:
        answer = payload(await client.call_tool("check_item", {"description": "cheddar crackers"}))
    assert answer["outcome"] == "clear"
    assert "not a guarantee" in answer["say"]


@pytest.mark.anyio
async def test_allergens_narrow_the_recent_list(offline):
    async with create_connected_server_and_client_session(server.server._mcp_server) as client:
        await client.call_tool("set_allergens", {"allergens": ["Peanuts", " "]})
        mine = payload(await client.call_tool("recent_recalls", {"days": 30}))
        everything = payload(await client.call_tool("recent_recalls", {"days": 30, "only_mine": False}))
    assert mine["filtered_by"] == ["peanuts"]
    assert mine["count"] == 1
    assert everything["count"] == 2


def answering(reply: str):
    async def callback(context, params):
        callback.asked = params.message
        return types.ElicitResult(action="accept", content={"answer": reply})
    callback.asked = None
    return callback


async def refusing(context, params):
    return types.ElicitResult(action="decline")


@pytest.mark.anyio
async def test_a_vague_product_is_settled_by_asking_through_the_protocol(offline):
    caller = answering("vodka")
    async with create_connected_server_and_client_session(
            server.server._mcp_server, elicitation_callback=caller) as client:
        answer = payload(await client.call_tool("check_item", {"description": "tomato sauce"}))
    assert caller.asked and "vodka" in caller.asked
    assert answer["outcome"] == "recalled"
    assert "Nonna Rosa" in answer["say"]


@pytest.mark.anyio
async def test_a_caller_who_declines_still_gets_the_question_back(offline):
    async with create_connected_server_and_client_session(
            server.server._mcp_server, elicitation_callback=refusing) as client:
        answer = payload(await client.call_tool("check_item", {"description": "tomato sauce"}))
    assert answer["outcome"] == "unclear"
    assert answer["ask"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
