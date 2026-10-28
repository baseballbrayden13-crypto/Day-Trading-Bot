"""Paste your Alpaca paper keys into .env (or another file with --file) without opening it. Input is hidden."""
from getpass import getpass
from pathlib import Path

import sys

# python set_keys.py                         -> the ORB bot's .env
# python set_keys.py --file .env.rotation    -> bot 2's own paper account
name = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else ".env"
env = Path(__file__).with_name(name)
if not env.exists():
    env.write_text("ALPACA_API_KEY=\nALPACA_SECRET_KEY=\n")
key = getpass("Paste your Alpaca API key (hidden), then press Enter: ").strip()
secret = getpass("Paste your Alpaca secret key (hidden), then press Enter: ").strip()

lines = []
for line in env.read_text().splitlines():
    if line.startswith("ALPACA_API_KEY="):
        line = f"ALPACA_API_KEY={key}"
    elif line.startswith("ALPACA_SECRET_KEY="):
        line = f"ALPACA_SECRET_KEY={secret}"
    lines.append(line)
env.write_text("\n".join(lines) + "\n")
print("Saved. Tell Claude you're done.")
