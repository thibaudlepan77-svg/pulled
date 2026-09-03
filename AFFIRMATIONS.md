# Every number in this repository, and how to disprove it

A test says what the code does. It says nothing about a sentence in a README.
Each claim below is falsifiable, and the command that falsifies it is next to
it. All were measured on 3 September 2026 against the live services, so the
feeds will have moved on and the shape of the finding is what should hold.

Run these from the repository root, with the package installed.

## The USDA feed

| claim | where it is written | command |
| --- | --- | --- |
| The feed delivers 2 023 records | `pulled/fsis.py`, `FEEDBACK.md` 6 | `python -c "from pulled import fsis; print(len(fsis._download()))"` |
| 789 recall numbers are doubled | `FEEDBACK.md` 6, `README.md` | `python -c "from collections import Counter; from pulled import fsis; print(sum(1 for c in Counter(r.get('field_recall_number','') for r in fsis._download()).values() if c > 1))"` |
| Those 2 023 records are 1 234 recalls | `pulled/fsis.py`, `README.md` | `python -c "from pulled import fsis; print(len(fsis.all_recalls()))"` |
| 361 records carry an allergen reason | `pulled/fsis.py`, `FEEDBACK.md` 7 | `python -c "from pulled import fsis; print(sum(1 for r in fsis.all_recalls() if 'allergen' in r.reason.lower()))"` |
| Not one of them names it in that field | `FEEDBACK.md` 7 | `python -c "from pulled import fsis; print([r.reason for r in fsis.all_recalls() if 'allergen' in r.reason.lower()][:5])"` and read them |
| 354 are recovered from the press release | `pulled/fsis.py`, `README.md` | `python -c "from pulled import fsis; print(sum(1 for r in fsis.all_recalls() if 'allergen' in r.reason.lower() and ',' in r.reason))"` |
| 623 records quote the product name | `FEEDBACK.md` 8 | `python -c "from pulled import fsis, match; print(sum(1 for r in fsis.all_recalls() if match.QUOTED.search(r.product)))"` |
| 169 records are alerts, not recalls | `pulled/server.py`, `README.md` | `python -c "from pulled import fsis; print(sum(1 for r in fsis.all_recalls() if 'alert' in r.status.lower()))"` |
| 195 records carry no manufacturer | `pulled/server.py` | `python -c "from pulled import fsis; print(sum(1 for r in fsis.all_recalls() if not r.firm.strip()))"` |
| The feed 403s a non browser agent | `pulled/fsis.py`, `FEEDBACK.md` 9 | send a GET with `User-Agent: pulled/0.1` and no `Accept` |

## The FDA feed

| claim | where it is written | command |
| --- | --- | --- |
| 48 records were filed on 15 April 2026 by one creamery | `README.md`, `pulled/match.py` | `curl "https://api.fda.gov/food/enforcement.json?search=recalling_firm:%22Silver+Moon%22+AND+recall_initiation_date:%2220260415%22&limit=100"` and read `meta.results.total` |
| 43 of them are Loard's ice cream | `README.md`, `pulled/match.py` | same response, count the descriptions beginning with Loard |
| They carry 31 distinct reasons | `pulled/match.py` | same response, count the distinct `reason_for_recall` |
| A search that matches nothing answers 404 | `FEEDBACK.md` 3 | search for a nonsense term and read the status |

## The suite

| claim | where it is written | command |
| --- | --- | --- |
| The tests reach neither agency | `README.md`, `no_network.py` | `python no_network.py`, which refuses name resolution and every off-machine connection |
| The suite listens on nothing | `README.md` | `netstat` while it runs, or read `tests/`, the protocol is driven over an in-memory pair |
| It passes on a machine that is not mine | `.github/workflows/tests.yml` | the run status on `api.github.com/repos/thibaudlepan77-svg/pulled/actions/runs` |

The last one earned its place. The suite was green here and red on a clean
machine for three runs, because the SDK floor had no ceiling and a fresh
install pulled a major version this was never run against.

## What is not claimed anywhere

That a clear result means the food is safe. The server says the opposite in
the sentence it hands back, and that sentence is covered by a test.

That the matcher is accurate. Nothing here measures precision or recall against
a labelled set, because no such set exists for spoken kitchen descriptions.
What is claimed is narrower and testable, that it refuses to name a product
when the record hinges on a word the caller never said.
