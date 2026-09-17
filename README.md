# pulled

[![tests](https://github.com/thibaudlepan77-svg/pulled/actions/workflows/tests.yml/badge.svg)](https://github.com/thibaudlepan77-svg/pulled/actions/workflows/tests.yml)

An MCP server that lets a voice assistant answer one question in the kitchen.
Has this been recalled, and does it matter to me.

US food recalls are published, free and machine readable, and almost nobody
sees them. The FDA enforcement feed carries close to thirty thousand records
and it is written for regulators, so `Undeclared colors (Yellow #5, Yellow #6,
and/or Red #40)` sits between a parent and the fact that their child should not
eat the thing in their hand. The data is not missing. The last few metres are.

They are also split in two. The FDA covers most of the shelf and the USDA
covers meat, poultry and eggs through a separate feed with a separate shape.
A checker wired to one of them is silent on chicken, deli meat and ground beef.
`pulled` reads both, and neither can take the other down.

## What it does

Three tools and one prompt, over Streamable HTTP, protocol `2025-11-25`.

| tool | for |
| --- | --- |
| `check_item(description)` | the caller describes a food in their own words |
| `recent_recalls(days, only_mine)` | what has been pulled lately that touches this household |
| `set_allergens(allergens)` | what this household reacts to |

`check_item` has three outcomes, not two.

    recalled   a named record, with the reason in the FDA's own words
    unclear    one question, and no verdict
    clear      nothing matched, said as nothing matched and not as it is safe

The middle outcome is the point. A voice assistant that says *yes that is
recalled* about the wrong jar sends someone to bin their dinner, and one that
says *no* about the right jar is worse. So when the record hinges on a word the
caller never said, the server asks about that word instead of answering.

## Asking is part of the protocol, not a field in a payload

When the server is unsure it does not hand a question back and hope the client
asks it. It raises an elicitation, gets the answer, folds it into the
description and decides. One tool call, one round trip to the person, one
verdict.

```citation
> is my Loard's ice cream recalled
Alexa: I found 38 recalls that all match Loard's Ice Cream. What else does the
front of the pack say?
Person: peanut butter fudge
Alexa: Loard's Peanut Butter Fudge Ice Cream was recalled on 15 April 2026. The
reason given is Undeclared Milk, Peanuts. The recall is ongoing, Class II.
```

That exchange is not a contrived one. On 15 April 2026 the FDA published
forty-eight records from one creamery in a single batch, forty-three of them
Loard's ice cream, carrying thirty-one different reasons between them. Peanut
Butter Fudge is undeclared milk and peanuts, Pistachio is milk and pistachios,
Rocky Road is milk, walnuts and eggs. The brand cannot answer the question.
The flavour is the whole answer.

A client that does not support elicitation, or a person who declines to answer,
loses nothing. The outcome stays `unclear` and the same question comes back in
the payload for the client to ask however it likes. Both paths are covered by
tests.

## Seeing it run

    python demo.py --offline

Plays the whole kitchen conversation through the protocol against fixed
records, elicitation included, so a screen recording gives the same take twice.
Drop `--offline` to run it against the live feed. Neither opens a port.

## How the matching works

Every candidate is scored on how much of what the caller said appears in the
record, weighted by how rare each word is inside the candidate pool. Two rules
then stop a confident answer.

- **The near tie.** If other records fit as well as the first, we have found a
  family of products, not a product. Naming one would be a guess, so the server
  names the shared part back and asks for the rest of the label. Forty-three
  flavours of one brand in one batch is what this rule is for.
- **The unsaid word.** If the product name carries a word at least as
  distinctive as anything the caller said, and they did not say it, that word
  is probably the difference between their tub and this one. Ask about it. The
  maker's own name is excluded, because a caller who says Straus should not be
  asked whether their pint says family.

Sizes, weights, packaging and supply chain boilerplate are stripped before any
of this, because `3.17oz`, `pouch` and `per` look rare and mean nothing. That
list grew from running the matcher against the live feed rather than against
fixtures, and the story is in [FEEDBACK.md](FEEDBACK.md).

## What a transcriber does to it

Everything above was built on what people type. Spoken through a speech
engine and transcribed by Whisper, `Loard's ice cream` comes back as `Lord's
ice cream`. No record carries lord and the FDA search asked for every word, so
that side came back empty, and a USDA record for Brazilian pastries won at 0.68
on the word cream. The assistant then asked whether the tub was the one from
WOW Frozen Food.

Three changes.

- A fixed list of words people say around a name, `from`, `shop`,
  `recalled`, is dropped before searching and matching, as packaging words
  already were. It is a list, so it misses some. When the FDA search still finds
  nothing, words that appear on no record in the whole feed are dropped, then
  each remaining word takes its turn being the one left out. What comes back is
  ranked by how many of the caller's words each record carries and capped at
  fifty. A sentence of more than eight searchable words is not retried.
- A heard word that no candidate carries is respelt as the record word one
  letter away from it, when exactly one such word exists, both are at least four
  letters long and they start with the same letter. The respelling changes
  which record ranks first and how well it scores.
- It never makes a yes on its own. A confident answer still has to clear the
  bar on the words that were heard exactly, so `pear puree` against a Peas
  Puree record from Peas Kitchen is a question. And a word that no candidate
  carries at all, perhaps the brand of something never recalled, turns a yes
  into a question, so `zebra pistachio ice cream` does not borrow Loard's
  recall. The cost is more questions, and a brand heard wrong can stay a
  question the caller cannot settle by saying yes.

`python evaluate.py 200` takes 200 records of 2026 from the live FDA
feed, shortens each name the way someone reading a pack would, and asks the
matcher. `--misheard` deletes the third letter of the first word of five letters
or more before asking, loard becoming lord. Measured on 17 September 2026, the
before columns with the package from `5b1a015` and this `evaluate.py`.

| outcome, of 200 records | before, as read | before, misheard | after, as read | after, misheard |
| --- | --- | --- | --- | --- |
| the record came back | 71.0 % | 1.0 % | 72.5 % | 28.0 % |
| still unsure after one question | 23.0 % | 59.0 % | 25.0 % | 70.0 % |
| a different record, named with confidence | 0.5 % | 3.5 % | 0.5 % | 0.0 % |
| nothing came back | 3.5 % | 34.5 % | 0.0 % | 0.0 % |

The row that mattered was the last one. One lost letter used to turn a
recalled product into `no recall matching that` about one time in three, and
on these 200 records it now never does. Most
misheard descriptions now end in a question rather than an answer, which is
the middle outcome doing its job and not a solved problem.

Read these as the easy end of speech. The mutation never touches the first
letter and never substitutes or swaps, a description with no word of five
letters goes through unchanged, and the answer to the follow-up question is
read off the record without being misheard. Four records have a name under two
words and are skipped in every column. And leaving the brand out of `Lord's ice
cream` searches for the fifty newest ice cream recalls, which today still holds
36 of the 43 Loard's records and will hold fewer as newer ones are filed.

## Running it

    pip install -e ".[dev]"
    python -m pulled.server          # http://127.0.0.1:8931/mcp
    pytest                           # 48 tests
    python no_network.py             # the same 48, with the network refused

The suite drives the server through an in-memory client and server pair rather
than a socket, so it listens on nothing and a failing run cannot leave a
listener behind.

`no_network.py` runs the same tests with name resolution and every off-machine
connection refused inside the process. It is there because the claim above is
checkable and a claim nobody checks is decoration. It also corrected the claim.
An earlier wording said the suite opens no socket at all, which is false on
Windows, where the asyncio event loop builds a loopback pair to wake itself.
What is true, and what the check proves, is that nothing here resolves a name
or leaves the machine.

## Data

| source | shape | cached |
| --- | --- | --- |
| `api.fda.gov/food/enforcement.json` | server side search, no key, 240 requests a minute | six hours, per query |
| `fsis.usda.gov/fsis/api/recall/v/1` | one 13 MB document, every record ever, no filtering | six hours, whole feed |

Both are public and unauthenticated. Each cache is also the fallback when its
service is unreachable, and a source that fails is skipped rather than raised,
because an answer from one agency beats an error naming two.

Scope is United States. A clear result means nothing was found in either feed.
It is not a safety certificate, and the wording the server reads aloud says so.

Three things the USDA feed does not give you, all handled here and all written
up in [FEEDBACK.md](FEEDBACK.md).

- **It is published twice, once in Spanish, under the same recall number.**
  789 numbers of 2 023 records are doubled that way, so a matcher that looks
  for a near tie finds one on every query. Deduplicated, the feed holds 1 234
  recalls.
- **Its reason field never names the allergen.** 361 records say
  `Unreported Allergens` and stop. The allergen is lifted out of the press
  release instead, which names it in 354 of them.
- **169 of its records are alerts, not recalls.** This server says so in those
  words rather than telling someone their dinner has been pulled from sale.

## Every number in here is falsifiable

[AFFIRMATIONS.md](AFFIRMATIONS.md) lists each figure quoted in this repository
next to the command that disproves it. A green suite says what the code does,
it says nothing about a sentence in a README.

## Licence

MIT, see [LICENSE](LICENSE).
