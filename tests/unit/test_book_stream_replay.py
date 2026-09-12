import copy
import json
import pytest
from analytics.book_stream_replay import replay, main


def row(seq, payload, received=None, mono=None):
    return {"sequence": seq, "received_at_ms": received or seq, "monotonic_elapsed": mono if mono is not None else float(seq), "raw_frame": payload}


def book(token="1", market="m", timestamp="1"):
    return {"event_type": "book", "asset_id": token, "market": market, "timestamp": timestamp,
            "bids": [{"price": "0.40", "size": "2"}], "asks": [{"price": "0.60", "size": "3"}]}


def change(token="1", price="0.40", size="4", side="BUY", timestamp="2", **extra):
    item = {"asset_id": token, "price": price, "size": size, "side": side, "timestamp": timestamp}
    item.update(extra)
    return {"event_type": "price_change", "market": "m", "timestamp": timestamp, "price_changes": [item]}


def test_insert_change_delete_and_atomic_bbo():
    records = [row(1, [book()]), row(2, change(price="0.50", size="1", best_bid="0.50", best_ask="0.60")),
               row(3, change(price="0.50", size="0", side="BUY", timestamp="3"))]
    result = replay(records, ["1"])
    assert result["valid"]
    assert result["final_books"]["1"]["bids"] == {"0.40": "2"}
    assert result["matched_bbo_checks"] == 2


def test_bbo_mismatch_companion_delta_is_ignored():
    frame = {"event_type": "price_change", "market": "m", "timestamp": "2", "price_changes": [
        {"asset_id": "1", "price": "0.40", "size": "2", "side": "BUY", "timestamp": "2", "best_bid": "0.40", "best_ask": "0.60"},
        {"asset_id": "2", "price": "0.20", "size": "1", "side": "BUY", "timestamp": "2"}]}
    result = replay([row(1, book()), row(2, frame)], ["1"])
    assert result["valid"]
    assert result["ignored_unrequested_deltas"] == 1

    bad = replay([row(1, book()), row(2, change(best_bid="0.41", best_ask="0.60"))], ["1"])
    assert not bad["valid"] and "bbo mismatch" in bad["errors"]


def test_missing_initial_order_and_malformed_numeric_are_invalid():
    assert not replay([row(1, change())], ["1"])["valid"]
    bad = replay([row(1, book()), row(2, change(price="NaN"))], ["1"])
    assert not bad["valid"]
    assert any("nonfinite" in reason for reason in bad["errors"])


def test_history_is_immutable_and_receive_regression_invalid():
    first = row(1, book(), received=20)
    second = row(2, change(size="5"), received=10)
    result = replay([first, second], ["1"])
    assert not result["valid"]
    assert result["snapshots"][0]["books"]["1"]["bids"] == {"0.40": "2"}
    result["snapshots"][1]["books"]["1"]["bids"]["0.40"] = "99"
    assert result["final_books"]["1"]["bids"]["0.40"] == "5"


@pytest.mark.parametrize('tokens', [[], ['1','1'], [None], [['1']], ['١']])
def test_invalid_subscription_never_enables_simulation(tokens):
    result = replay([], tokens)
    assert not result['valid'] and not result['simulation_allowed']


def test_missing_book_and_metadata_are_invalid():
    assert not replay([row(1,book())],['1','2'])['simulation_allowed']
    for key in ['sequence','received_at_ms','monotonic_elapsed']:
        r = row(1,book()); del r[key]
        assert not replay([r],['1'])['valid']
    r = row(1,book()); r['monotonic_elapsed'] = float('nan')
    assert not replay([r],['1'])['valid']


def test_source_order_last_bbo_and_inputs_preserved():
    events = [change(price='0.5',best_bid='0.5',best_ask='0.6'),
              change(price='0.55',best_bid='0.55',best_ask='0.6')]
    records = [row(1,book()),row(2,events)]
    original = copy.deepcopy(records)
    result = replay(records,['1'])
    assert result['valid'] and result['bbo_checks'] == 2
    assert result['final_books']['1']['bids']['0.55'] == '4'
    assert records == original
    result = replay([row(1,book()), row(2,[events[0],book(timestamp='3')])],['1'])
    assert result['valid'] and result['final_books']['1']['bids'] == {'0.40':'2'}
    assert result['bbo_checks'] == 0


def test_zero_level_duplicates_and_timestamp_regression_rejected():
    b = book(); b['bids'] = [{'price':'0.4','size':'0'},{'price':'0.40','size':'2'}]
    assert not replay([row(1,b)],['1'])['valid']
    assert not replay([row(1,book(timestamp='9')),row(2,change(timestamp='8'))],['1'])['valid']
    for timestamp in ['²', '١', '', True, None]:
        assert not replay([row(1,book(timestamp=timestamp))],['1'])['valid']


def test_cli_incomplete_manifest_disables_simulation(tmp_path):
    path = tmp_path/'capture.jsonl'
    path.write_text(json.dumps(row(1,book()))+'\n',encoding='utf-8')
    manifest = {'requested_tokens':['1'],'complete':False,'message_count':1,'bytes':path.stat().st_size}
    (tmp_path/'capture.jsonl.summary.json').write_text(json.dumps(manifest),encoding='utf-8')
    out = tmp_path/'report.json'
    assert main([str(path),'--output',str(out)]) == 1
    report=json.loads(out.read_text(encoding='utf-8'))
    assert not report['valid'] and not report['simulation_allowed']
