import re
from pathlib import Path

import pytest

# Every setting name bot/config.py reads, so a local .env can't change test results.
_SETTINGS = set(re.findall(r'(?:getenv|_float|_int|_bool)\("([A-Z_]+)"', (Path(__file__).parents[1] / "bot" / "config.py").read_text()))


@pytest.fixture(autouse=True)
def ignore_local_env(monkeypatch):
    for name in _SETTINGS:
        monkeypatch.delenv(name, raising=False)
