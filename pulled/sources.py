"""The two agencies, behind one lookup.

US food recalls are split. The FDA publishes most of the shelf through
openFDA, and meat, poultry and egg products belong to the USDA through FSIS.
A checker wired to one of them is silent on chicken, deli meat and ground beef,
which is where the Class I recalls live.

Neither source is allowed to take the other down. A kitchen question answered
from one feed is worth far more than an error that mentions both.
"""

from __future__ import annotations

from datetime import date

from . import fsis, openfda
from .recall import Recall


def _both(from_fda, from_usda) -> list[Recall]:
    found: list[Recall] = []
    for reach in (from_fda, from_usda):
        try:
            found.extend(reach())
        except Exception:
            continue
    return found


def search_product(terms: str, limit: int = 50) -> list[Recall]:
    return _both(lambda: openfda.search_product(terms, limit),
                 lambda: fsis.search_product(terms, limit))


def since(day: date, limit: int = 100, country: str = "United States") -> list[Recall]:
    found = _both(lambda: openfda.since(day, limit, country),
                  lambda: fsis.since(day, limit))
    return sorted(found, key=lambda recall: recall.initiated, reverse=True)
