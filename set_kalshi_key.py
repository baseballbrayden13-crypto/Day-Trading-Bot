"""Save the Kalshi bot's API key into .env.kalshi without opening it. Demo account by default.

Make the key on https://demo.kalshi.co (Account -> API keys). Kalshi shows a Key ID and downloads a
private key file once; give this script both. The key file is copied to kalshi_key.pem next to it.
"""
import shutil
from getpass import getpass
from pathlib import Path

here = Path(__file__).parent
key_id = getpass("Paste the Kalshi Key ID (hidden), then press Enter: ").strip()
src = Path(input("Drag the downloaded private key file here (or paste its path), then press Enter: ").strip().strip('"'))
if not src.exists():
    raise SystemExit(f"Can't find {src}. Nothing was saved.")
shutil.copyfile(src, here / "kalshi_key.pem")

env = here / ".env.kalshi"
lines = env.read_text().splitlines() if env.exists() else ["KALSHI_ENV=demo", "KALSHI_BUDGET=20", "KALSHI_MIN_PROFIT=0.10"]
lines = [l for l in lines if not l.startswith(("KALSHI_KEY_ID=", "KALSHI_KEY_FILE="))]
lines += [f"KALSHI_KEY_ID={key_id}", "KALSHI_KEY_FILE=kalshi_key.pem"]
env.write_text("\n".join(lines) + "\n")
print("Saved. Tell Claude you're done. (You can delete the downloaded copy of the key file now.)")
