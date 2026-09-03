"""Two agencies behind one lookup, and neither allowed to sink the other."""

from datetime import date

import pytest

from pulled import fsis, openfda, sources
from pulled.recall import Recall


def recall(product: str, agency: str, day: date) -> Recall:
    return Recall(number="X-1", initiated=day, product=product, reason="Undeclared milk",
                  status="Ongoing", classification="Class I", firm="Acme",
                  country="United States", distribution="Nationwide", lot_codes="",
                  agency=agency)


SHELF = recall("Dark Chocolate Almond Bites", "FDA", date(2026, 5, 23))
FREEZER = recall("Frozen Meatloaf With Garlic Mashed Potatoes", "USDA FSIS", date(2026, 6, 18))


@pytest.fixture
def both(monkeypatch):
    monkeypatch.setattr(openfda, "search_product", lambda terms, limit=50: [SHELF])
    monkeypatch.setattr(fsis, "search_product", lambda terms, limit=50: [FREEZER])
    monkeypatch.setattr(openfda, "since", lambda day, limit=100, country="United States": [SHELF])
    monkeypatch.setattr(fsis, "since", lambda day, limit=100: [FREEZER])


def test_a_search_reaches_both_agencies(both):
    found = sources.search_product("anything")
    assert {r.agency for r in found} == {"FDA", "USDA FSIS"}


def test_the_recent_list_is_ordered_across_agencies(both):
    assert [r.agency for r in sources.since(date(2026, 1, 1))] == ["USDA FSIS", "FDA"]


def test_one_agency_down_still_answers_from_the_other(monkeypatch, both):
    def refuse(*_args, **_kwargs):
        raise fsis.FsisUnavailable("HTTP Error 403: Forbidden")

    monkeypatch.setattr(fsis, "search_product", refuse)
    found = sources.search_product("anything")
    assert [r.agency for r in found] == ["FDA"]


def test_both_agencies_down_is_an_empty_answer_and_not_a_crash(monkeypatch, both):
    def refuse(*_args, **_kwargs):
        raise OSError("network is down")

    monkeypatch.setattr(fsis, "search_product", refuse)
    monkeypatch.setattr(openfda, "search_product", refuse)
    assert sources.search_product("anything") == []
