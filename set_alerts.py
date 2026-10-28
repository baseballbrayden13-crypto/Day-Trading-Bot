"""Turn on phone alerts: picks a random ntfy topic, saves it as NTFY_TOPIC in .env,
and sends a test alert. Only touches the NTFY_TOPIC line."""
import secrets
from pathlib import Path

env = Path(__file__).with_name(".env")
topic = f"brayden-bot-{secrets.token_hex(6)}"
lines = [l for l in env.read_text().splitlines() if not l.startswith("NTFY_TOPIC=")]
lines.append(f"NTFY_TOPIC={topic}")
env.write_text("\n".join(lines) + "\n")

from bot.config import Settings  # noqa: E402  (reads the .env we just wrote)
from bot.notify import send  # noqa: E402

print(f"Saved. In the ntfy phone app, tap + and subscribe to:  {topic}")
print("Test alert sent." if send(Settings(), "Trading bot", "Alerts are on.") else "Test alert failed; check your internet.")
