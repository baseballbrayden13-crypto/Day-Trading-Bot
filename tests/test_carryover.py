import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("merge_carryover", Path(__file__).parents[1] / "cloud" / "merge_carryover.py")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)


def test_carryover_merges_once():
    carry = json.loads(mc.CARRY.read_text())
    cloud = {"realized": "-1.19", "open": [], "closed": [], "quotes": [{"event": "E"}]}
    merged = mc.merge(cloud, carry)
    assert merged["realized"] == "-0.9900"
    assert len(merged["open"]) == 2 and len(merged["closed"]) == 1 and merged["quotes"] == [{"event": "E"}]
    assert mc.merge(merged, carry) is merged  # second run changes nothing


def test_carryover_into_empty_state():
    merged = mc.merge({}, json.loads(mc.CARRY.read_text()))
    assert merged["realized"] == "0.2000" and merged["quotes"] == []
