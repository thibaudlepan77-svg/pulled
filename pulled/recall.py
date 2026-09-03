"""The one shape both agencies are flattened into.

Food recalls in the United States are split between two bodies. The FDA covers
most of the shelf, and meat, poultry and egg products belong to the USDA. A
checker that knows only one of them is silent on deli meat and on chicken,
which is where the dangerous ones live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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
    agency: str = "FDA"
    url: str = ""

    @property
    def ongoing(self) -> bool:
        return self.status.lower() in ("ongoing", "active recall")
