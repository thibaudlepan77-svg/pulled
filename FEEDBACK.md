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

### 4. One brand, one day, forty-eight records and thirty-one different reasons

- **Task.** Answer `is my Loard's ice cream recalled` the way a person asks it.
- **Steps.** `recalling_firm:"Silver Moon" AND recall_initiation_date:"20260415"`
  on the enforcement endpoint, then the matcher over the result.
- **Expected.** A handful of records, resolvable by brand.
- **Actual.** Forty-eight records filed the same day by the same creamery,
  forty-three of them under the Loard's brand, carrying thirty-one distinct
  reasons. Peanut Butter Fudge is undeclared milk and peanuts, Pistachio is
  milk and pistachios, Rocky Road is milk, walnuts and eggs. The brand a caller
  can read off the lid is the one thing that cannot decide the question, and
  the difference between two of these tubs is an allergy.
- **Severity.** High for anyone answering out loud. Naming the top hit here has
  a one in forty-three chance of being the tub in the kitchen, and it looks
  like a confident answer either way.
- **Workaround.** Treat a tie as a family. Name the shared part of the label
  back to the caller, say how many records match it, and ask for the rest.
- **Suggestion.** A batch identifier on records filed together would let a
  client say `this is part of a forty-eight product recall` in one call.
  Today that has to be inferred from the firm and the date.

### 5. The maker's name is inside the product description

- **Task.** Ask the caller for the one word that separates their pint from the
  record.
- **Actual.** `STRAUS FAMILY CREAMERY Mint Chip ORGANIC SUPER PREMIUM ICE
  CREAM ONE PINT` puts the corporate name at the front of the product field,
  and `recalling_firm` repeats it. A caller who says straus was asked whether
  their pint says family.
- **Severity.** Medium. The question is not wrong, it is unanswerable, and an
  unanswerable question reads as a broken assistant.
- **Workaround.** Exclude the words of `recalling_firm` when choosing what to
  ask about, and read the trading name behind `dba` rather than the corporate
  one. `Silver Moon LP dba Loard's Ice Cream` is not what is printed on a tub.
- **Suggestion.** The product description would be far more usable if the
  brand, the variant and the pack size were not concatenated into one free text
  field. Failing that, note in the docs that the firm name frequently appears
  in both fields.

## USDA FSIS, `fsis.usda.gov/fsis/api/recall/v/1`

The other half of US food recalls. One JSON document, no key, no server side
filtering, so it is fetched whole and cached. All counts below were measured on
3 September 2026 against that document.

### 6. The feed is published twice, once in Spanish, under the same number

- **Task.** Count what is actually in the feed before searching it.
- **Expected.** 2 023 records, 2 023 recalls.
- **Actual.** 789 recall numbers appear twice. `009-2025` is
  `Cargill Kitchen Solutions Recalls Liquid Egg Products` and
  `Cargill Kitchen Solutions Retira Productos De Huevo Líquido`, the same event
  in two languages. The feed holds **1 234** distinct recalls.
- **Severity.** High and quiet. A matcher scores the Spanish edition as a
  second product, so anything that looks for a near tie finds one on every
  single query and refuses to answer. Anything that counts recalls overstates
  by two thirds.
- **Workaround.** Group by recall number and keep the English edition. That
  one change took the records carrying no manufacturer from 983 to 195, and
  took the allergen recovery below from 76 per cent to 98, because the Spanish
  editions were the ones failing both.
- **Suggestion.** A language field, or a separate endpoint per language. Right
  now the only way to tell the two apart is to read the title.

### 7. Not one allergen recall names the allergen

- **Task.** Narrow the recent list to what a milk allergic household must
  avoid, across both agencies.
- **Expected.** The reason field carries the allergen, as the FDA one does.
- **Actual.** 361 distinct records carry an allergen reason. **Zero** name the
  allergen in it. The field reads `Misbranding Unreported Allergens` and stops,
  and that is the field any consumer will filter on. The press release does
  name it, in 354 of the 361.
- **Severity.** High. A household filter over this feed either drops every
  allergen recall or keeps all of them, and both are wrong.
- **Workaround.** Scan the summary for allergen names and append them to the
  reason. The summary has to be read in full, the allergen is rarely inside the
  first three hundred characters.
- **Suggestion.** A structured allergen list, or simply the allergen inside the
  reason string. The FDA feed puts it there and the difference is stark.

### 8. Fifty-fifty odds that the product field is packaging

- **Task.** Ask the caller for the one word that identifies their pack.
- **Actual.** The FDA leads with the product name and appends the container.
  The USDA does the opposite, `13.3-oz. vacuum sealed plastic tray packages
  containing "POWER PLATE MEALS MEATLOAF"`. Reading the first words of the
  field, which is right for one agency, made the server ask a caller whether
  their pack said vacuum.
- **Severity.** Medium, and invisible until the two feeds sit side by side.
- **Workaround.** When the description contains a quoted phrase, that is the
  name. 623 of the 1 234 records are quoted that way and none of the FDA sample
  is, so the rule is safe to apply to both.
- **Suggestion.** Publish the product name as its own field. It is already
  delimited by quotes half the time, which suggests it exists upstream.

### 9. A 403 that is not about the agent

- **Task.** Fetch the feed from a script.
- **Actual.** `HTTP 403` for a named project agent, with or without an Accept
  header. A browser shaped agent alone is also refused. The pair goes through
  every time. Six attempts, and the first reading of them was wrong, one
  success looked like it came from the agent when the Accept header was doing
  the work.
- **Severity.** Low once known, high before, because 403 on a public dataset
  reads as an access decision rather than a header check.
- **Workaround.** Send a browser shaped `User-Agent` together with `Accept`.
  Nothing here is a key, the data is public and unauthenticated.
- **Suggestion.** If the filter has to exist, answer with a body saying which
  header is missing. A silent 403 on an open dataset costs every new consumer
  the same afternoon.

### 10. Alerts and recalls share a shape and call for different actions

- **Task.** Tell the caller what happened to their product.
- **Actual.** 169 of the 1 234 records are public health alerts rather than
  recalls. They carry no manufacturer, because the title reads `FSIS Issues
  Public Health Alert for ...` rather than `Company Recalls ...`, and the type
  sits in `field_recall_type` while `field_recall_classification` repeats it
  instead of giving a class. A client that assumes a recall tells someone their
  dinner was pulled from sale when it was not.
- **Severity.** High for anything spoken. The two events call for different
  actions from the person holding the food.
- **Workaround.** Read `field_recall_type`, say alert when it says alert, and
  expect an empty firm on those records.
- **Suggestion.** Keep the firm populated. The company is named in the body of
  every alert we read.
