import pytest
from app.core.nova.work_revenue.prospect_discovery import parse_candidates,SearchUnavailable

def test_results_are_unwrapped_filtered_and_deduplicated():
    source='''<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fcontact">Contact - Example Travel</a>
    <a class="result__a" href="https://www.example.com/">Duplicate</a>
    <a class="result__a" href="https://yelp.com/business">Directory</a>
    <a class="result__a" href="https://old.com/contact">Existing</a>
    <a class="result__a" href="https://user:password@other.com/">Credential</a>'''
    rows=parse_candidates(source,limit=8,exclude_domains={'old.com'})
    assert rows==[{'name':'Example Travel','url':'https://example.com/contact','search_title':'Contact - Example Travel'}]

def test_verification_challenge_stops_without_results():
    with pytest.raises(SearchUnavailable):parse_candidates('<form class="anomaly-modal">challenge</form>',limit=5,exclude_domains=set())
