from datetime import date

from pulled.match import Verdict, best, tokens
from pulled.openfda import Recall


def recall(product: str, firm: str = "Acme Foods", lot: str = "") -> Recall:
    return Recall(
        number="F-0001-2026",
        initiated=date(2026, 5, 23),
        product=product,
        reason="Undeclared peanuts",
        status="Ongoing",
        classification="Class I",
        firm=firm,
        country="United States",
        distribution="Nationwide",
        lot_codes=lot,
    )


POOL = [
    recall("Dark Chocolate Coconut Almond Bites, 3.17oz, Plastic Pouch", "Sunridge Farms"),
    recall("King Harvest brand Spinach Hummus. Product is packed in 10oz plastic tub", "King Harvest"),
    recall("Grade A White In-shell Chicken eggs packaged in cartons", "Country Eggs"),
    recall("Sunridge Pistachio Ice Cream - 32 oz", "Sunridge Creamery"),
]

# Wording taken from real openFDA records, H-0743-2026 and its siblings, all
# published on the same day by the same creamery.
FLAVOURS = [
    recall("Loard's Peanut Butter Fudge Ice Cream - 32 oz", "Silver Moon LP dba Loard's Ice Cream"),
    recall("Loard's Pistachio Ice Cream - 32 oz", "Silver Moon LP dba Loard's Ice Cream"),
    recall("Loard's Rocky Road Ice Cream - 56 oz", "Silver Moon LP dba Loard's Ice Cream"),
    recall("Loard's Egg Nog Ice Cream - 32 oz", "Silver Moon LP dba Loard's Ice Cream"),
]


def test_filler_words_are_dropped():
    assert tokens("the plastic bag of spinach hummus") == ["spinach", "hummus"]


def test_a_distinctive_description_is_matched():
    verdict = best("dark chocolate coconut almond bites", POOL)
    assert verdict.outcome == "recalled"
    assert verdict.recall.firm == "Sunridge Farms"


def test_an_unrelated_product_is_cleared():
    verdict = best("cheddar crackers", POOL)
    assert verdict.outcome == "clear"
    assert verdict.recall is None


def test_a_partial_description_asks_rather_than_guesses():
    verdict = best("ice cream", POOL)
    assert verdict.outcome == "unclear"
    assert verdict.question


def test_a_recalled_family_is_named_back_and_the_rest_of_the_label_asked_for():
    verdict = best("loard's ice cream", FLAVOURS)
    assert verdict.outcome == "unclear"
    assert "Loard's Ice Cream" in verdict.question
    assert "4 recalls" in verdict.question


def test_the_makers_own_name_is_never_the_question():
    # Live descriptions open with the corporate name, and the caller reading
    # the front of the pint has already said the part that is printed on it.
    pool = [recall("STRAUS FAMILY CREAMERY Mint Chip ORGANIC ICE CREAM ONE PINT",
                   "Straus Family Creamery")]
    verdict = best("straus mint chip ice cream", pool)
    assert "family" not in (verdict.question or "").lower()
    assert "creamery" not in (verdict.question or "").lower()


def test_the_flavour_settles_what_the_family_could_not():
    verdict = best("loard's ice cream peanut butter fudge", FLAVOURS)
    assert verdict.outcome == "recalled"
    assert verdict.recall.product.startswith("Loard's Peanut Butter Fudge")


def test_two_equally_good_records_do_not_produce_a_yes():
    twins = [
        recall("Spinach Hummus 10oz tub", "King Harvest"),
        recall("Spinach Hummus 10oz tub", "Green Valley"),
    ]
    verdict = best("spinach hummus", twins)
    assert verdict.outcome == "unclear"
    assert "King Harvest" in verdict.question or "Green Valley" in verdict.question


def test_empty_pool_is_clear_not_an_error():
    assert best("anything at all", []) == Verdict("clear", 0.0, None)


def test_lot_code_is_the_question_when_nothing_else_separates_the_record():
    pool = [recall("Sunridge granola bar", "Sunridge", lot="Lot 4471")]
    verdict = best("sunridge granola bar", pool)
    assert verdict.outcome == "recalled"

    partial = best("sunridge bar", pool)
    assert partial.outcome == "unclear"
    assert "granola" in partial.question
