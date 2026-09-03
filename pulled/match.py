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

from .recall import Recall

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
QUOTED = re.compile(u'[“”"]([^“”"]{3,120})[“”"]')
# 3.17oz splits into 3 and 17oz, and 17oz then looks like a rare, meaningful
# word. Weights and counts are stripped so they never carry the decision.
MEASURE = re.compile(r"^\d+[a-z]*$")


@dataclass(frozen=True)
class Verdict:
    outcome: str  # "recalled", "unclear", "clear"
    score: float
    recall: Recall | None
    question: str | None = None


def spoken_name(description: str) -> str:
    """The part of the record a person holding the thing would read out.

    The two agencies bury the name in opposite places. openFDA leads with it
    and appends the container, `Banana Ice Cream - 32 oz (4 labels: Mollie
    Stone's), UPC 8-12017-00903`. The USDA leads with the container and puts
    the name in quotes, `13.3-oz. vacuum sealed plastic tray packages
    containing "POWER PLATE MEALS MEATLOAF"`. Half the USDA records are quoted
    that way and none of the FDA ones are, so the quotes decide when they are
    there and the comma decides when they are not.
    """
    quoted = QUOTED.search(description)
    return quoted.group(1) if quoted else description.split(",")[0]


def name_of(description: str) -> list[str]:
    return tokens(spoken_name(description))[:6]


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

    Every word of `chicken eggs` matches a grade A white in-shell chicken eggs
    record, and the carton in the caller's hand is almost certainly a different
    one. What settles it is not how much of the sentence matched, it is whether
    the word that singles this record out was spoken at all.

    The bar is relative on purpose. Rarity is computed inside the pool, so an
    absolute threshold would mean something different for four candidates and
    for four hundred. A word vetoes when it is at least as distinctive as the
    least distinctive word the caller did say.

    The words of the manufacturer's name are never the question. Live
    descriptions open with the firm, `STRAUS FAMILY CREAMERY Mint Chip ...`, so
    a caller who says straus gets asked whether their pint says family. They
    have already identified the maker, and the pack in their hand says the
    trading name rather than the corporate one.
    """
    said = set(spoken)
    maker = set(tokens(recall.firm))
    absent = [(rarity.get(word, 1.0), word) for word in name_of(recall.product)
              if word not in said and word not in maker]
    if not absent:
        return None
    heard = [rarity.get(word, 1.0) for word in said]
    if not heard:
        return None
    weight, word = max(absent)
    return word if weight >= statistics.median(heard) else None


def _family(tied: list[Recall]) -> str:
    """The part of the name every tied record shares, in the top record's casing.

    On 15 April 2026 the FDA published forty-three Loard's ice cream flavours
    in one go, with thirty-one different sets of allergens between them.
    `loard's ice cream` matches all of them perfectly, so the shared part is
    the whole of what the caller has told us, and the flavour is the answer.
    """
    names = [set(name_of(r.product)) for r in tied]
    common = set.intersection(*names)
    # When the names are word for word the same, nothing on the pack separates
    # them and the caller would be sent to read a label that cannot answer.
    # What differs then is the manufacturer, so leave it to the clarifier.
    if not common or all(name == common for name in names):
        return ""
    kept, said = [], set()
    for word in spoken_name(tied[0].product).split():
        spelt = tokens(word)
        # Live descriptions repeat the creamery name inside the product line,
        # so the same word can arrive twice and the question stutters.
        if spelt and spelt[0] in common and spelt[0] not in said:
            said.add(spelt[0])
            kept.append(word)
    return " ".join(kept)


def _crowded(tied: list[Recall], spoken: list[str]) -> str:
    """What to ask when several records fit the sentence equally well.

    Naming the family back is the strongest form, it tells the caller we heard
    them and that their own words are not enough. Failing that, the honest
    thing is to say how many are open and ask for more of the label. Only a
    small tie is worth resolving by manufacturer, because a caller who has to
    pick between fifteen firms is being asked to do our work.
    """
    shared = _family(tied)
    if shared:
        return (f"I found {len(tied)} recalls that all match {shared}. "
                "What else does the front of the pack say?")
    if len(tied) > 2:
        return (f"I found {len(tied)} open recalls that fit what you said. "
                "What else does the front of the pack say?")
    return _clarifier(tied[0], spoken)


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
        tied = [r for fit, r in ranked if score - fit < 0.05]
        # Records that fit equally well mean we have identified a family, not a
        # product. Saying yes here would name the wrong flavour or the wrong
        # manufacturer, and in this feed those carry different allergens.
        if len(tied) > 1:
            return Verdict("unclear", score, recall, _crowded(tied, spoken))
        unsaid = _unsaid(spoken, recall, rarity)
        if unsaid:
            return Verdict("unclear", score, recall, _clarifier(recall, spoken, unsaid))
        return Verdict("recalled", score, recall)
    if score >= WORTH_ASKING:
        return Verdict("unclear", score, recall, _clarifier(recall, spoken))
    return Verdict("clear", score, None)
