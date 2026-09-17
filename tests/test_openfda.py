from pulled import openfda

TUB = {"recall_number": "H-0743-2026", "recall_initiation_date": "20260415",
       "product_description": "Loard's Peanut Butter Fudge Ice Cream - 32 oz"}


# Words the feed holds somewhere, on some other record.
ELSEWHERE = {"vanilla", "flavor", "chips"}


def answering(carrying):
    """A stand-in for openFDA that only knows the words of one record."""
    asked = []

    def fetch(params):
        words = [part.split(":", 1)[1].lower() for part in params["search"].split("+AND+")]
        label = TUB["product_description"].lower()
        if params.get("limit") == 1 and len(words) == 1:
            return {"results": [TUB] if words[0] in label or words[0] in ELSEWHERE else []}
        asked.append(words)
        return {"results": [TUB] if all(w in label for w in words) and carrying else []}

    return fetch, asked


def test_a_search_that_finds_something_is_asked_once(monkeypatch):
    fetch, asked = answering(True)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    assert [r.number for r in openfda.search_product("loard's peanut fudge")] == ["H-0743-2026"]
    assert len(asked) == 1


def test_a_word_the_label_does_not_carry_is_left_out_in_turn(monkeypatch):
    fetch, asked = answering(True)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    found = openfda.search_product("lord's peanut butter fudge")
    assert [r.number for r in found] == ["H-0743-2026"]
    assert ["peanut", "butter", "fudge"] in asked


def test_a_word_the_feed_knows_is_only_ever_left_out_one_at_a_time(monkeypatch):
    fetch, asked = answering(False)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    assert openfda.search_product("vanilla peanut flavor chips") == []
    assert all(len(words) >= 3 for words in asked)


def test_a_single_word_that_matches_nothing_is_not_retried(monkeypatch):
    fetch, asked = answering(False)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    assert openfda.search_product("nothing") == []
    assert len(asked) == 1


def test_words_no_label_carries_are_not_searched_for(monkeypatch):
    fetch, asked = answering(True)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    openfda.search_product("is this Loard's peanut butter fudge recalled?")
    assert asked[0] == ["loard's", "peanut", "butter", "fudge"]


def test_a_long_search_and_its_shorter_retry_do_not_share_a_cache_file():
    long_query = "search=" + "+AND+".join(f"product_description:word{i}xxxxxxxx" for i in range(6))
    shorter = long_query.rsplit("+AND+", 1)[0]
    assert openfda._cache_path(long_query) != openfda._cache_path(shorter)


def test_a_misheard_word_and_an_extra_one_together_still_find_the_record(monkeypatch):
    fetch, asked = answering(True)
    monkeypatch.setattr(openfda, "_fetch", fetch)
    found = openfda.search_product("Lord's ice cream, peanut butter fudge flavor")
    assert [r.number for r in found] == ["H-0743-2026"]
    assert not any("lord's" in words for words in asked[1:])

