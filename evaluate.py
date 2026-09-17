"""Measure what the matcher does on real records, instead of asserting it.

There is no labelled set of spoken kitchen descriptions, so this builds the
only honest thing available, a round trip. Take a real recall, shorten its
product name the way somebody reading the front of a pack would, ask
`check_item` about it, and see whether the record comes back.

    python evaluate.py            120 records from the live FDA feed
    python evaluate.py 300        a bigger sample
    python evaluate.py --misheard  the same, one letter lost from a long word

To measure the matcher as it was before a change, run this file next to the
old package without touching the checkout, for example
`git archive 5b1a015 pulled | tar -x -C ../before` and copy this file there.

Four outcomes are counted, and only one of them is a failure of the promise
this project makes.

    found    the record we started from came back
    asked    unclear, with a question. Not an error, this is the design
    other    a DIFFERENT record came back, named confidently. The wrong yes
    clear    nothing came back at all. The wrong no

`other` is the number that matters. A recall checker that names the wrong
product with confidence is worse than one that says it does not know.

WHAT THIS DOES NOT MEASURE, and it should be read before the numbers are
quoted anywhere. The spoken descriptions are derived FROM the records, by rule,
so they carry the record's own vocabulary and never a brand a person
misremembers, a phonetic spelling, or a word the label does not use. Real
speech is harder than this. Treat the result as a ceiling, not a score.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter

from pulled import fsis, match, openfda

FEED = ("https://api.fda.gov/food/enforcement.json"
        "?search=report_date:[20260101+TO+20261231]&limit=%d&skip=%d")
AGENT = {"User-Agent": "pulled/0.1 (+https://github.com/thibaudlepan77-svg/pulled)"}


def sample(wanted: int) -> list[dict]:
    records: list[dict] = []
    while len(records) < wanted:
        page = urllib.request.Request(FEED % (min(100, wanted - len(records)), len(records)),
                                      headers=AGENT)
        batch = json.load(urllib.request.urlopen(page, timeout=60))["results"]
        if not batch:
            break
        records.extend(batch)
    return records


def as_spoken(product: str) -> str:
    """What somebody holding the thing would say, at most four words.

    The packaging tail and the logistics are dropped by the same rule the
    matcher uses, then the first few words of the name are kept, because a
    person reads the front of the pack and stops.
    """
    return " ".join(match.tokens(match.spoken_name(product))[:4])


def reads_on(product: str, spoken: str) -> str:
    """The next words of the name, the ones a person reads when asked for more."""
    said = set(spoken.split())
    return " ".join([w for w in match.name_of(product) if w not in said][:2])


def misheard(spoken: str) -> str:
    """The same words with the third letter of the first word of five or more
    letters deleted, loard becoming lord.

    A crude stand-in for a transcriber that spells a brand the way it sounds.
    It is deterministic, so two runs compare, and it is narrow. It never touches
    the first letter, never substitutes or swaps letters, and leaves a
    description with no word that long unchanged. The follow-up answer read
    off the pack is not misheard. Treat the result as the easy end of speech.
    """
    words = spoken.split()
    for i, word in enumerate(words):
        if len(word) >= 5:
            words[i] = word[:2] + word[3:]
            break
    return " ".join(words)


def main(wanted: int = 120, garbled: bool = False) -> int:
    tally = Counter()
    wrong = []
    for record in sample(wanted):
        product = record.get("product_description", "")
        number = record.get("recall_number", "")
        spoken = as_spoken(product)
        if garbled:
            spoken = misheard(spoken)
        if len(spoken.split()) < 2:
            tally["skipped, under two words"] += 1
            continue

        # Not sources.search_product, which swallows a failing feed. Here a
        # throttled request would be counted as `clear`, so it stops the run.
        pool = openfda.search_product(spoken) + fsis.search_product(spoken)
        verdict = match.best(spoken, pool)
        if verdict.outcome == "unclear":
            tally["asked at least once"] += 1
            # The person is holding the pack, so they can read more of it.
            # This is what check_item does with an elicitation answer, it
            # folds the words into the description and decides again.
            verdict = match.best("%s %s" % (spoken, reads_on(product, spoken)), pool)

        if verdict.outcome == "clear":
            tally["clear"] += 1
        elif verdict.outcome == "unclear":
            tally["still unsure after one question"] += 1
        elif verdict.recall is not None and verdict.recall.number == number:
            tally["found"] += 1
        else:
            tally["other"] += 1
            wrong.append((spoken, product[:60], verdict.recall.product[:60]))

    # A record that was asked about is also counted under its final outcome,
    # so the records are everything except that line.
    total = sum(tally.values()) - tally["asked at least once"]
    print("%d records from the live feed%s\n" % (total, ", misheard" if garbled else ""))
    for name in ("found", "still unsure after one question", "other", "clear",
                 "skipped, under two words", "asked at least once"):
        if tally[name]:
            print("  %-32s %4d   %5.1f %%" % (name, tally[name], 100 * tally[name] / total))

    print("\nthe one that matters, a confident answer naming a different record")
    print("  %d of %d, %.1f %%" % (tally["other"], total, 100 * tally["other"] / total))
    for spoken, asked_about, answered in wrong[:8]:
        print("    heard   %s" % spoken)
        print("    was     %s" % asked_about)
        print("    said    %s\n" % answered)
    return 0


if __name__ == "__main__":
    numbers = [a for a in sys.argv[1:] if a.isdigit()]
    raise SystemExit(main(int(numbers[0]) if numbers else 120, "--misheard" in sys.argv))
