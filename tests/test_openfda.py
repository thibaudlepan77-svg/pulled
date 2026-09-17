from pulled import openfda


def test_a_long_search_and_its_shorter_retry_do_not_share_a_cache_file():
    long_query = "search=" + "+AND+".join(f"product_description:word{i}xxxxxxxx" for i in range(6))
    shorter = long_query.rsplit("+AND+", 1)[0]
    assert openfda._cache_path(long_query) != openfda._cache_path(shorter)
