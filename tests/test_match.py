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


def test_a_brand_spelt_the_way_it_sounds_still_finds_its_record():
    # A transcriber writes Lord's for Loard's, and no record carries lord.
    verdict = best("lord's peanut butter fudge ice cream", FLAVOURS)
    assert verdict.outcome == "recalled"
    assert verdict.recall.product.startswith("Loard's Peanut Butter Fudge")


def test_a_misheard_brand_still_names_the_family_back():
    verdict = best("lord's ice cream", FLAVOURS)
    assert verdict.outcome == "unclear"
    assert "Loard's Ice Cream" in verdict.question


def test_a_word_two_records_could_be_is_left_as_heard():
    pool = [recall("Lowes Foods sour cream chips", "Lowes Foods"),
            recall("Loves Farm sour cream chips", "Loves Farm")]
    # loes is one letter from both lowes and loves, so neither spelling wins.
    verdict = best("loes sour cream chips", pool)
    assert verdict.recall is None or verdict.outcome != "recalled"


def test_short_words_are_never_respelt():
    pool = [recall("Pea Protein Crisps", "Sunridge Farms")]
    assert best("tea crisps", pool).outcome != "recalled"


def test_a_respelling_never_turns_a_near_word_into_a_yes():
    # Each pair is one letter apart, and the caller said the other word.
    for said, product in (("pear baby food puree", "Peas Baby Food Puree"),
                          ("lime tortilla chips", "Lite Tortilla Chips"),
                          ("meat lasagna", "Meal Lasagna")):
        verdict = best(said, [recall(product, "Acme Foods")])
        assert verdict.outcome != "recalled", said


def test_a_respelling_that_lands_on_the_makers_name_is_still_a_question():
    for said, product, firm in (("pear puree", "Peas Puree", "Peas Kitchen"),
                                ("kind granola", "Granola, 12 oz", "King Snacks")):
        verdict = best(said, [recall(product, firm)])
        assert verdict.outcome == "unclear", said


def test_a_brand_no_record_carries_does_not_borrow_another_brands_recall():
    for said in ("zebra peanut butter fudge ice cream", "zebra pistachio ice cream",
                 "market pantry peanut butter fudge ice cream"):
        assert best(said, FLAVOURS).outcome == "unclear", said

