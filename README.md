# pulled

An MCP server that lets a voice assistant answer one question in the kitchen.
Has this been recalled, and does it matter to me.

US food recalls are published, free and machine readable, and almost nobody
sees them. The FDA enforcement feed carries close to thirty thousand records
and it is written for regulators, so `Undeclared colors (Yellow #5, Yellow #6,
and/or Red #40)` sits between a parent and the fact that their child should not
eat the thing in their hand. The data is not missing. The last few metres are.

## What it does

Three tools, over Streamable HTTP, protocol `2025-11-25`.

| tool | for |
| --- | --- |
| `check_item(description)` | the caller describes a food in their own words |
| `recent_recalls(days, only_mine)` | what has been pulled lately that touches this household |
| `set_allergens(allergens)` | what this household reacts to |

`check_item` has three outcomes, not two.

    recalled   a named record, with the reason in the FDA's own words
    unclear    one question to ask back, and no verdict
    clear      nothing matched, said as nothing matched and not as it is safe

The middle outcome is the point. A voice assistant that says *yes that is
recalled* about the wrong jar sends someone to bin their dinner, and one that
says *no* about the right jar is worse. So when the record hinges on a word the
caller never said, the server hands back a question instead of an answer.

```
> is my dark chocolate coconut almond bites recalled
Dark Chocolate Coconut Almond Bites from Bazzini LLC was recalled on
23 May 2026. The reason given is Undeclared peanuts. The recall is ongoing,
Class I.

> is my tomato sauce recalled
I found a recall that might be yours, but I am not sure.
Does yours say vodka on the pack?
```

## Seeing it run

    python demo.py --offline

Plays a kitchen conversation through the protocol against fixed records, so a
screen recording gives the same take twice. Drop `--offline` to run it against
the live feed. Neither opens a port.

## How the matching works

Every candidate is scored on how much of what the caller said appears in the
record, weighted by how rare each word is inside the candidate pool. Two rules
then stop a confident answer.

- **The near tie.** If a second record fits as well as the first, we have found
  a family of products, not a product, so naming a manufacturer would be a
  guess. Ask which one.
- **The unsaid word.** If the product name carries a word at least as
  distinctive as anything the caller said, and they did not say it, that word
  is probably the difference between their jar and this one. Ask about it.

Sizes, weights, packaging and supply chain boilerplate are stripped before any
of this, because `3.17oz`, `pouch` and `per` look rare and mean nothing. That
list grew from running the matcher against the live feed rather than against
fixtures.

## Running it

    pip install -e ".[dev]"
    python -m pulled.server          # http://127.0.0.1:8931/mcp
    pytest                           # 12 tests, no network, no port opened

The test suite drives the server through an in-memory client and server pair,
so no socket is opened and a failing run cannot leave a listener behind.

## Data

`api.fda.gov/food/enforcement.json`, public, no key, rate limited to 240
requests per minute for anonymous callers. Responses are cached on disk for six
hours and the cache is also the fallback when the API is unreachable.

Scope is United States enforcement reports. A clear result means nothing was
found in that feed. It is not a safety certificate, and the wording the server
reads aloud says so.

## Licence

MIT, see [LICENSE](LICENSE).
