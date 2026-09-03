"""Match a spoken product description against recall records.

A wrong yes and a wrong no are both dangerous, so the matcher has three
outcomes rather than two. Anything between the two thresholds comes back as a
question the assistant can ask out loud, not as an answer.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass

from .openfda import Recall

CONFIDENT = 0.62
WORTH_ASKING = 0.30

# Words that appear in most descriptions and separate nothing.
FILLER = {
    "the", "a", "an", "and", "of", "with", "in", "for", "my", "our", "some",
    "that", "this", "those", "brand", "product", "products", "item", "items",
    "net", "wt", "oz", "lb", "lbs", "g", "kg", "ml", "count", "ct", "pack",
    "packed", "package", "packaged", "case", "box", "bag", "bags", "plastic",
    "retail", "unit", "units", "upc", "size", "sizes", "food", "foods",
    # Packaging says nothing about which product is in the hand. Leaving these
    # in made the matcher demand that the caller recite the word pouch.
    "pouch", "pouches", "tub", "tubs", "jar", "jars", "carton", "cartons",
    "bottle", "bottles", "can", "cans", "tray", "trays", "sleeve", "wrapper",
    "container", "containers", "cup", "cups", "tin", "tins",
    # Boilerplate seen in live openFDA descriptions. Left in, it produced
    # questions like `does yours say per on the pack`.
    "per", "each", "sold", "labeled", "label", "marked", "printed", "code",
    "codes", "lot", "lots", "best", "use", "date", "dates", "exp", "sku",
    "distributed", "manufactured", "packs", "inner", "outer", "master",
    "assorted", "variety", "individually", "wrapped", "frozen", "fresh",
    "approximately", "approx", "gross", "weight", "weights", "nos", "number",
}
SPLIT = re.compile(r"[^a-z0-9]+")
# 3.17oz splits into 3 and 17oz, and 17oz then looks like a rare, meaningful
# word. Weights and counts are stripped so they never carry the decision.
MEASURE = re.compile(r"^\d+[a-z]*$")


@dataclass(frozen=True)
class Verdict:
    outcome: str  # "recalled", "unclear", "clear"
    score: float
    recall: Recall | None
    question: str | None = None


def name_of(description: str) -> list[str]:
    """The product name, without the packaging and logistics tail.

    openFDA descriptions read `Vodka Tomato Sauce, NET WT. 24 oz, glass jar,
    UPC 0123`. Everything after the first comma describes the container and the
    supply chain, and a caller holding the jar will never recite it.
    """
    return tokens(description.split(",")[0])[:6]


def tokens(text: str) -> list[str]:
    return [w for w in SPLIT.split(text.lower())
            if len(w) > 2 and w not in FILLER and not MEASURE.match(w)]


def _rarity(pool: list[Recall]) -> dict[str, float]:
    seen = Counter()
    for recall in pool:
        seen.update(set(tokens(recall.product)))
    total = max(len(pool), 1)
    return {word: math.log(total / count) + 1.0 for word, count in seen.items()}


def _score(spoken: list[str], recall: Recall, rarity: dict[str, float]) -> float:
    described = set(tokens(recall.product) + tokens(recall.firm))
    if not spoken or not described:
        return 0.0
    heard = sum(rarity.get(word, 1.0) for word in spoken if word in described)
    ceiling = sum(rarity.get(word, 1.0) for word in spoken)
    return heard / ceiling if ceiling else 0.0


def _unsaid(spoken: list[str], recall: Recall, rarity: dict[str, float]) -> str | None:
    """The word this record hinges on that the caller never said.

    Every word of `tomato sauce` matches the vodka tomato sauce record, and the
    jar in the caller's hand is almost certainly a different tomato sauce. What
    settles it is not how much of the sentence matched, it is whether the word
    that singles this record out was spoken at all.

    The bar is relative on purpose. Rarity is computed inside the pool, so an
    absolute threshold would mean something different for four candidates and
    for four hundred. A word vetoes when it is at least as distinctive as the
    least distinctive word the caller did say.
    """
    said = set(spoken)
    absent = [(rarity.get(word, 1.0), word)
              for word in name_of(recall.product) if word not in said]
    if not absent:
        return None
    heard = [rarity.get(word, 1.0) for word in said]
    if not heard:
        return None
    weight, word = max(absent)
    return word if weight >= statistics.median(heard) else None


def _clarifier(recall: Recall, spoken: list[str], unsaid: str | None = None) -> str:
    if unsaid:
        return f"Does yours say {unsaid} on the pack?"
    firm_words = [w for w in tokens(recall.firm) if w not in spoken]
    if firm_words:
        return f"Is it the one from {recall.firm}?"
    if recall.lot_codes.strip():
        return "What is the lot code printed on the pack?"
    return f"Is yours the {recall.product.split(',')[0].strip()}?"


def best(spoken_description: str, pool: list[Recall]) -> Verdict:
    spoken = tokens(spoken_description)
    if not spoken or not pool:
        return Verdict("clear", 0.0, None)

    rarity = _rarity(pool)
    ranked = sorted(((_score(spoken, r, rarity), r) for r in pool),
                    key=lambda pair: pair[0], reverse=True)
    score, recall = ranked[0]

    if score >= CONFIDENT:
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        # Two records that fit equally well means we have identified a family,
        # not a product. Saying yes here would name the wrong manufacturer.
        if score - runner_up < 0.05 and len(ranked) > 1:
            return Verdict("unclear", score, recall, _clarifier(recall, spoken))
        unsaid = _unsaid(spoken, recall, rarity)
        if unsaid:
            return Verdict("unclear", score, recall, _clarifier(recall, spoken, unsaid))
        return Verdict("recalled", score, recall)
    if score >= WORTH_ASKING:
        return Verdict("unclear", score, recall, _clarifier(recall, spoken))
    return Verdict("clear", score, None)
