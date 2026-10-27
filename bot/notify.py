"""Phone alerts through ntfy (https://ntfy.sh): free, no account.

Install the ntfy app on your phone, subscribe to the topic printed by
`python set_alerts.py`, and the bot sends a push for every buy, every position
that closes, the end-of-day flatten, the daily loss halt, and errors.
Set NTFY_TOPIC in .env (set_alerts.py does it). Empty = alerts off.
Anyone who knows the topic name can read the alerts, so keep it random.
"""
from __future__ import annotations

import logging
import urllib.request

from .config import Settings

log = logging.getLogger(__name__)


def send(cfg: Settings, title: str, message: str, priority: str = "default") -> bool:
    """Best effort: an alert that fails to send is logged and never stops the bot."""
    if not cfg.ntfy_topic:
        return False
    req = urllib.request.Request(
        f"https://ntfy.sh/{cfg.ntfy_topic}", data=message.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority, "Tags": "chart_with_upwards_trend"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception as e:  # network down, ntfy down: keep trading
        log.warning("Alert not sent (%s): %s", e, title)
        return False
