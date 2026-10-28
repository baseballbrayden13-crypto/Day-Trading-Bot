"""Adds the PC bot 4c's open and closed baskets (cloud/carryover_4c.json) to the cloud 4c state, once.
Run from state/ before the maker starts. A "carryover" key in the state file marks it as done."""
import json
from decimal import Decimal
from pathlib import Path

STATE = Path("kalshi_maker_paper_state.json")
CARRY = Path(__file__).with_name("carryover_4c.json")


def merge(state: dict, carry: dict) -> dict:
    if state.get("carryover"):
        return state
    state = {"realized": "0", "open": [], "closed": [], "quotes": [], **state}
    state["realized"] = str(Decimal(state["realized"]) + Decimal(carry["realized"]))
    state["open"] = state["open"] + carry["open"]
    state["closed"] = state["closed"] + carry["closed"]
    state["carryover"] = CARRY.name
    return state


if __name__ == "__main__":
    if CARRY.exists():
        cur = json.loads(STATE.read_text()) if STATE.exists() else {}
        new = merge(cur, json.loads(CARRY.read_text()))
        if new is not cur:
            STATE.write_text(json.dumps(new, indent=1))
            print("Carryover merged into the 4c state.")
