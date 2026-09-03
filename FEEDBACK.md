# Product feedback and friction log

Kept while building rather than reconstructed afterwards, so the timings and the
wrong turns are the real ones. Updated as the project goes on.

---

## MCP Python SDK, `mcp` 1.29.1

**What I used it for.** The whole server. Three tools and one prompt, served
over Streamable HTTP, protocol `2025-11-25`.

**What worked well.** `FastMCP` gets a working tool surface out of ordinary
functions with type hints, and the docstring becomes the tool description, so
the thing the model reads and the thing the maintainer reads cannot drift
apart. That is a good design decision and it is rare.

`mcp.shared.memory.create_connected_server_and_client_session` was the best
thing I found in the package. It runs the real protocol over an in-memory
stream pair, so the test suite exercises tool listing, argument coercion and
serialisation without opening a port. Twelve tests, no socket, no flake.

**What needs work.** Discoverability. I found the in-memory helper by listing
the module by hand, after having already planned to start a server on a port
and poll it. Nothing in the getting-started path suggests that a protocol level
test needs no transport at all, and it is the single most useful thing in the
package for anyone who has to run tests in CI.

`mcp.types.LATEST_PROTOCOL_VERSION` exists and is exactly what a hackathon
entrant needs to check against a rule that names a spec date. There is no
matching `SUPPORTED_PROTOCOL_VERSIONS` on the same object, so answering *does
this version satisfy 2025-11-25 or later* takes more digging than it should.

**Onboarding.** Fifteen minutes from a blank folder to a tool the client could
list. The friction was not the SDK.

**Would I build with it again.** Yes, without hesitating.

---

## openFDA food enforcement API

**What I used it for.** Every recall record the server answers with.
`api.fda.gov/food/enforcement.json`, no key, 240 requests a minute for
anonymous callers.

**What worked well.** No key, no account, no card, and a first useful response
inside a minute. The record set is rich in exactly the fields this product
needs, `product_description`, `reason_for_recall`, `status`, `classification`,
`code_info` for lot numbers. Close to thirty thousand records.

**What needs work.** The query language and the standard library disagree in a
way that reads as a server fault. See the friction log below.

The free text of `product_description` mixes three different things, the
product name, the packaging, and the supply chain, separated only by commas and
not consistently. Any consumer matching against it has to learn that on its own.

**Would I build with it again.** Yes. The absence of a key is worth a lot when
the alternative is a card.

---

## Friction log

### 1. `urlencode` turns an openFDA search into a 500

- **Task.** Fetch every enforcement report in a date range.
- **Steps.** Built the search value `report_date:[20260506+TO+20260903]` and
  passed the parameter dictionary to `urllib.parse.urlencode`.
- **Expected.** A result set.
- **Actual.** `HTTP 500 Internal Server Error`, with no body explaining
  anything. `urlencode` had escaped the plus into `%2B`, and openFDA reads a
  plus as the space of its own query language, so the search became
  syntactically wrong. The service answered with a server error rather than a
  400, which sent me looking at my network before my string.
- **Severity.** Medium. It costs perhaps twenty minutes, and it will cost them
  to every single person whose first instinct is to use the standard encoder.
- **Workaround.** Quote the search value by hand with
  `quote(value, safe=':[]+"()*')` and encode the rest normally.
- **Suggestion.** Answer a malformed search with 400 and a one line reason.
  A 500 tells the caller the problem is yours.

### 2. A green test suite that had never seen a real record

- **Task.** Confirm the matcher refuses to name a product it cannot pin.
- **Steps.** Twelve tests against handwritten records, all passing, then the
  same code against the live feed.
- **Expected.** The same behaviour.
- **Actual.** Every real query came back unclear, and one asked the caller
  `Does yours say per on the pack`. Real descriptions carry sizes that split
  into pseudo-words, `3.17oz` into `3` and `17oz`, packaging nouns that are
  rare and mean nothing, and administrative filler like `per` and `sold` that
  no human will ever say out loud.
- **Severity.** High for the product, none for the API. It would have shipped a
  server that never gives an answer.
- **Workaround.** Strip numeric and unit tokens, drop packaging and logistics
  words, and score only against the product name, meaning what sits before the
  first comma.
- **Suggestion.** Publish a short note on the shape of
  `product_description`, or expose the name and the packaging as separate
  fields. Every consumer of this endpoint is going to rediscover the comma rule
  and most will get it wrong quietly.

### 3. A 404 that means no results

- **Task.** Search for a product term that matches nothing.
- **Expected.** An empty result set.
- **Actual.** `HTTP 404`, which a client will normally treat as the endpoint
  being gone.
- **Severity.** Low, once known.
- **Workaround.** Translate 404 into an empty result set, and only that status.
- **Suggestion.** Return 200 with `meta.results.total` at zero. A 404 on a
  search path is a statement about the URL, not about the data.
