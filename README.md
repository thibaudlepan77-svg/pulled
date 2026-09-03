# pulled

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

## Running it

    pip install -e ".[dev]"
    python -m pulled.server          # http://127.0.0.1:8931/mcp
    pytest                           # 34 tests
    python no_network.py             # the same 34, with the network refused

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
