"""Copy bots 2 and 3's paper keys from .env.rotation / .env.crypto into GitHub's secret storage,
so the Cloud bots workflow can run them while the PC is off. Nothing is printed or saved anywhere
else. Needs the GitHub CLI (gh); the first time, it opens the browser to sign in.

    python set_cloud_keys.py               # keys, bot 1's account number, and bot 2's month state
    python set_cloud_keys.py --check       # just say what's set
    python set_cloud_keys.py --move-bot1   # also copy bot 1's .env and switch bot 1 (+ Lab, Reporter) to GitHub
    python set_cloud_keys.py --bot1-back   # bot 1 back to the PC (GitHub stops running it)

Before --move-bot1, turn off the PC's "Trading bot (paper)" task, or bot 1 would run twice.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

REPO = "baseballbrayden13-crypto/Day-Trading-Bot"
HERE = Path(__file__).parent
BOTS = {"BOT2": ".env.rotation", "BOT3": ".env.crypto"}


def gh(*args, input=None, check=True):
    return subprocess.run(["gh", *args], input=input, text=True, capture_output=True, check=check)


def main() -> None:
    if not shutil.which("gh"):
        sys.exit("The GitHub CLI isn't installed. Run:  winget install GitHub.cli   then open a new window and run this again.")
    if gh("auth", "status", check=False).returncode:
        print("Signing in to GitHub (a browser window opens)...")
        subprocess.run(["gh", "auth", "login", "--web", "--git-protocol", "https"], check=True)
    if "--bot1-back" in sys.argv:
        gh("variable", "set", "BOT1_CLOUD", "--repo", REPO, "--body", "off")
        print("Bot 1 is back on the PC: GitHub won't run it. Turn the PC's \"Trading bot (paper)\" task back on.")
        return
    if "--check" in sys.argv:
        print(gh("secret", "list", "--repo", REPO).stdout or "No secrets yet.")
        print(gh("variable", "list", "--repo", REPO).stdout)
        return
    for bot, name in BOTS.items():
        vals = dotenv_values(HERE / name)
        for field in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            value = (vals.get(field) or "").strip()
            if not value:
                sys.exit(f"{name} has no {field}. Nothing was changed for {bot}.")
            gh("secret", "set", f"{bot}_{field}", "--repo", REPO, input=value)  # value goes in on stdin, never the command line
        print(f"{bot}: keys copied from {name}")
    acct = HERE / "bot1_account.txt"
    if acct.exists():
        gh("variable", "set", "BOT1_ACCOUNT", "--repo", REPO, "--body", acct.read_text().strip())
        print("Bot 1's account number saved, so the cloud bots refuse to touch it.")
    seed_state()
    if "--move-bot1" in sys.argv:
        move_bot1()
    print("Done. Tell Claude, and it will start the first cloud run.")


def move_bot1() -> None:
    """Bot 1's whole .env (its settings and keys) as one secret, then switch it on in the cloud."""
    env = HERE / ".env"
    vals = dotenv_values(env) if env.exists() else {}
    if not (vals.get("ALPACA_API_KEY") or "").strip():
        sys.exit(".env has no ALPACA_API_KEY, so bot 1 was not moved.")
    if (vals.get("LIVE_TRADING") or "").strip().lower() in {"1", "true", "yes", "on"}:
        sys.exit(".env has LIVE_TRADING on. The cloud runs paper only, so bot 1 was not moved.")
    gh("secret", "set", "BOT1_ENV", "--repo", REPO, input=env.read_text(encoding="utf-8"))
    gh("variable", "set", "BOT1_CLOUD", "--repo", REPO, "--body", "on")
    print("Bot 1 copied. From the next weekday it runs on GitHub (9:05am and 12:40pm runs). Undo: --bot1-back")


def seed_state() -> None:
    """Bot 2's rotation_state.json (which month it last bought) as a variable; the first cloud run starts from it,
    so it doesn't rebalance again this month."""
    state = HERE / "rotation_state.json"
    if state.exists():
        gh("variable", "set", "BOT2_STATE", "--repo", REPO, "--body", state.read_text().strip())
        print("Bot 2's month state copied, so it won't buy twice.")


if __name__ == "__main__":
    main()
