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
    recall("Vodka Tomato Sauce, NET WT. 24 oz / 680g, glass jar", "Nonna Rosa"),
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
    verdict = best("tomato sauce", POOL)
    assert verdict.outcome == "unclear"
    assert verdict.question


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
