from datetime import datetime, timezone
import copy

from analytics.market_universe import fetch_universe


def test_fetch_universe_uses_four_exact_strata_and_fixed_time():
    urls = []
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def get(url):
        urls.append(url)
        return []

    result = fetch_universe(get=get, now=now)
    assert len(urls) == 4
    assert "order=id" in urls[0] and "ascending=true" in urls[0]
    assert "order=id" in urls[1] and "ascending=false" in urls[1]
    assert "order=volume24hr" in urls[2]
    assert "order=endDate" in urls[3]
    assert "end_date_min=2026-01-02T03%3A04%3A05%2B00%3A00" in urls[3]
    assert all("limit=75" in url and "offset=0" in url for url in urls)
    assert result["report"]["requests_count"] == 4


def test_overlap_deduplicates_first_version_and_merges_provenance():
    event = {"id": "same", "title": "raw", "rules": "keep", "markets": [{"id": "m", "rules": "market raw"}]}
    responses = [[event], [event], [], []]
    result = fetch_universe(get=lambda url: responses.pop(0))
    assert len(result["events"]) == 1
    kept = result["events"][0]
    assert kept["rules"] == "keep" and kept["markets"][0]["rules"] == "market raw"
    assert kept["_research_sources"] == ["baseline", "newest"]
    assert kept["markets"][0]["_research_sources"] == ["baseline", "newest"]
    assert result["report"]["deduped_events"] == 1


def test_source_failure_is_partial_and_malformed_response_is_rejected():
    calls = 0

    def get(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("offline")
        if calls == 2:
            return {"events": [{"title": "missing id"}]}
        return []

    result = fetch_universe(get=get)
    assert len(result["report"]["errors"]) == 2
    assert {error["source"] for error in result["report"]["errors"]} == {"baseline", "newest"}
    assert result["report"]["coverage_capped"] is True
    assert result["report"]["universe_complete"] is False


def test_event_views_interleave_without_mutating_raw_inputs():
    views = [[{'id':f'{source}-{i}','markets':[{'id':str(i)}]} for i in range(2)] for source in range(4)]
    original=copy.deepcopy(views)
    pending=iter(views)
    result=fetch_universe(get=lambda url:next(pending))
    assert [e['id'] for e in result['events']]==['0-0','1-0','2-0','3-0','0-1','1-1','2-1','3-1']
    assert views==original


def test_empty_or_malformed_ids_and_market_shapes_are_rejected():
    views=iter([[{'id':''}], [{'id':True}], [{'id':[]}], [{'id':'good','markets':{}}]])
    result=fetch_universe(get=lambda url:next(views))
    assert result['events']==[] and len(result['report']['errors'])==4
