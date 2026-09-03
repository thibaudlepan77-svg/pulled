"""The USDA feed, over records shaped the way the live service returns them.

No network here. The awkward parts are the shapes, not the transport, so the
fixtures below are trimmed copies of real records rather than inventions.
"""

from pulled import fsis

MEATLOAF = {
    "field_recall_number": "008-2026",
    "field_recall_date": "2026-06-18",
    "field_title": ["Power Plate Meals, LLC Recalls Meatloaf Products Due To "
                    "Misbranding and Undeclared Allergens"],
    "field_product_items": ["13.3-oz. vacuum sealed plastic tray packages containing "
                            "&quot;POWER PLATE MEALS MEATLOAF WITH GARLIC MASHED POTATOES&quot;"],
    "field_recall_reason": ["Unreported Allergens"],
    "field_recall_type": "Active Recall",
    "field_recall_classification": "Class II",
    "field_states": ["Minnesota", "North Dakota"],
    "field_summary": "<p>Power Plate Meals, LLC is recalling frozen meatloaf "
                     "products that contain <b>milk</b>, a known allergen, not "
                     "declared on the label.</p>",
    "field_recall_url": "http://www.fsis.usda.gov/recalls-alerts/power-plate-meals",
}

ALERT = dict(MEATLOAF, field_recall_number="PHA-08082026-01",
             field_recall_type="Public Health Alert",
             field_recall_classification="Public Health Alert",
             field_title=["FSIS Issues Public Health Alert for Jalapeno Products"])

UNDATED = dict(MEATLOAF, field_recall_date="", field_last_modified_date="")


def test_the_allergen_is_lifted_out_of_the_press_release():
    # 603 records carry an allergen reason and not one of them names the
    # allergen in that field, which is what a household filter reads.
    recall = fsis._to_recall(MEATLOAF)
    assert "milk" in recall.reason.lower()
    assert recall.reason.startswith("Unreported Allergens")


def test_html_entities_do_not_survive_into_something_read_aloud():
    assert "&quot;" not in fsis._to_recall(MEATLOAF).product
    assert '"POWER PLATE MEALS MEATLOAF' in fsis._to_recall(MEATLOAF).product


def test_the_firm_is_taken_from_the_title_and_an_alert_has_none():
    assert fsis._to_recall(MEATLOAF).firm == "Power Plate Meals, LLC"
    assert fsis._to_recall(ALERT).firm == ""


def test_an_alert_keeps_its_own_type_rather_than_being_called_a_recall():
    assert fsis._to_recall(ALERT).status == "Public Health Alert"
    assert fsis._to_recall(ALERT).ongoing is False
    assert fsis._to_recall(MEATLOAF).ongoing is True


def test_a_record_without_a_usable_date_is_dropped_rather_than_guessed():
    assert fsis._to_recall(UNDATED) is None


SPANISH_TWIN = dict(MEATLOAF,
                    field_title=["Power Plate Meals, LLC Retira Productos De Pastel De Carne "
                                 "Debido A Un Error De Rotulacion"],
                    field_product_items=["13.3-oz. paquetes de bandeja de plastico"])


def test_the_spanish_edition_of_a_recall_is_dropped():
    # 789 recall numbers of 2 023 records are published twice, and the pair
    # scores as two products unless one of them goes.
    kept = fsis._one_per_recall([MEATLOAF, SPANISH_TWIN])
    assert len(kept) == 1
    assert "Recalls Meatloaf" in fsis._joined(kept[0]["field_title"])


def test_the_spanish_edition_is_kept_when_it_is_the_only_one():
    kept = fsis._one_per_recall([SPANISH_TWIN])
    assert len(kept) == 1


def test_a_record_with_no_number_is_never_folded_into_another():
    numberless = dict(MEATLOAF, field_recall_number="")
    assert len(fsis._one_per_recall([numberless, dict(numberless)])) == 2


def test_records_carrying_every_word_come_before_partial_matches(monkeypatch):
    # Asking about ground beef, 68 records carry both words and only 15 got
    # through a filter that took the first fifty sharing any one of them.
    complet = dict(MEATLOAF, field_recall_number="A",
                   field_product_items=["Ground Beef Patties"])
    partiel = dict(MEATLOAF, field_recall_number="B",
                   field_product_items=["Ground Turkey"])
    autre = dict(MEATLOAF, field_recall_number="C",
                 field_product_items=["Beef Jerky"])
    monkeypatch.setattr(fsis, "_download", lambda: [partiel, autre, complet])

    trouve = fsis.search_product("ground beef")
    assert [r.number for r in trouve][0] == "A"
    assert {r.number for r in trouve} == {"A", "B", "C"}

    serre = fsis.search_product("ground beef", limit=1)
    assert [r.number for r in serre] == ["A"]
