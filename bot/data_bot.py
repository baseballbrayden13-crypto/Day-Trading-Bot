"""Scout, the data bot: gathers everything the fleet's bots and their reviewers need, in one place.

    python -m bot.data_bot              # collect now, write fleet_data/
    python -m bot.data_bot --days 60    # look further back for orders and log errors
    python -m bot.data_bot --no-market  # skip prices and news (accounts, logs and Kalshi only)

Read-only: it never places, cancels or closes an order and never edits a .env file. It reads each
bot's own keys (see bot.fleet) only to ask Alpaca for that bot's account, positions and filled
orders. Every source is collected on its own, so one bad key or a network blip shows up as an
error in the snapshot instead of stopping the rest.

Writes, in fleet_data/:
    snapshot.json         everything from this run (accounts, positions, logs, Kalshi, market, errors)
    history/<day>.json    a copy of the day's last snapshot, for trends
    equity.csv            day,bot,equity (same columns as the Strategy Lab equity data), one row per bot per day
    trades.csv            every filled order, all bots, kept across runs
    positions.csv         what each bot holds right now
    market.csv            per symbol: last close, 1-day / 1-month change, above its 200-day average, volatility
    news.csv              last day's headlines for bot 1's stocks
    benchmarks.csv        day,symbol,close for SPY, BTC and ETH: what just holding would have done
Medic, the maintenance bot (python -m bot.maintenance), reads these.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .fleet import Bot, load

ET = ZoneInfo("America/New_York")
OUT = Path("fleet_data")
log = logging.getLogger("data_bot")
LINE_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def keys(bot: Bot) -> tuple[str, str]:
    from dotenv import dotenv_values

    path = bot.path(bot.env_file)
    vals = dotenv_values(path) if path.exists() else {}
    return (vals.get("ALPACA_API_KEY") or "").strip(), (vals.get("ALPACA_SECRET_KEY") or "").strip()


def trading_client(bot: Bot):
    key, secret = keys(bot)
    if not key or not secret:
        raise RuntimeError(f"no Alpaca keys in {bot.env_file}")
    from alpaca.trading.client import TradingClient

    return TradingClient(key, secret, paper=True)  # the fleet is paper only; live keys would just fail here


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _iso(t) -> str:
    return t.isoformat() if hasattr(t, "isoformat") else str(t or "")


# ---------------------------------------------------------------- one Alpaca bot

def account(client) -> dict:
    a = client.get_account()
    number = str(a.account_number)
    return {"account": number[-4:], "equity": _f(a.equity), "last_equity": _f(a.last_equity), "cash": _f(a.cash),
            "status": str(getattr(a, "status", "")).split(".")[-1], "trading_blocked": bool(getattr(a, "trading_blocked", False)),
            "account_blocked": bool(getattr(a, "account_blocked", False))}


def positions(client) -> list[dict]:
    return [{"symbol": p.symbol, "qty": _f(p.qty), "avg_entry": _f(p.avg_entry_price), "market_value": _f(p.market_value),
             "unrealized_pl": _f(p.unrealized_pl)} for p in client.get_all_positions()]


def filled_orders(client, since: datetime) -> list[dict]:
    """Every filled order and bracket leg since `since`, oldest first."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since, limit=500, nested=True, direction="asc"))
    flat = []
    for o in orders:
        flat += [o, *(o.legs or [])]
    out = [{"time": _iso(o.filled_at), "symbol": o.symbol, "side": str(o.side).split(".")[-1].lower(),
            "qty": _f(o.filled_qty), "price": _f(o.filled_avg_price), "type": str(o.order_type).split(".")[-1].lower(),
            "order_id": str(o.id)} for o in flat if o.filled_at and _f(o.filled_qty) > 0]
    return sorted(out, key=lambda r: r["time"])


def equity_history(client) -> list[dict]:
    """Alpaca's own daily equity for the last month (older alpaca-py versions don't have this: returns [])."""
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        h = client.get_portfolio_history(GetPortfolioHistoryRequest(period="1M", timeframe="1D"))
    except (ImportError, AttributeError):
        return []
    return [{"day": datetime.fromtimestamp(t, ET).date().isoformat(), "equity": _f(e)}
            for t, e in zip(h.timestamp or [], h.equity or []) if e is not None]


def log_health(path: Path, now: datetime, days: int = 7) -> dict:
    """When the log last changed, its newest lines, and the errors in the last `days` days."""
    if not path.exists():
        return {"exists": False}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    since = (now - timedelta(days=days)).astimezone(ET).replace(tzinfo=None)
    day_ago = (now - timedelta(days=1)).astimezone(ET).replace(tzinfo=None)
    errors, errors_24h, last_time = [], 0, None
    for line in lines:
        m = LINE_TIME.match(line)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        last_time = t
        if t >= since and (" ERROR " in line or " CRITICAL " in line):
            errors.append(line[:300])
            errors_24h += t >= day_ago
    modified = datetime.fromtimestamp(path.stat().st_mtime, ET)
    return {"exists": True, "modified": modified.isoformat(timespec="seconds"),
            "last_line_time": last_time.isoformat() if last_time else "",
            "errors": len(errors), "errors_24h": errors_24h, "last_errors": errors[-3:],
            "tail": [l[:300] for l in lines[-5:] if "HTTP Request:" not in l],
            "live_warning": any("*** LIVE ***" in l for l in lines[-500:])}


def _json(path: Path):
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except ValueError as e:
        return {"error": f"unreadable {path.name}: {e}"}


def alpaca_bot(bot: Bot, client, now: datetime, days: int) -> dict:
    out: dict = {"name": bot.name, "label": bot.tag, "kind": bot.kind, "errors": []}
    for key, fn in (("account", lambda: account(client)), ("positions", lambda: positions(client)),
                    ("orders", lambda: filled_orders(client, now - timedelta(days=days))),
                    ("equity_history", lambda: equity_history(client))):
        try:
            out[key] = fn()
        except Exception as e:  # keep going: a 401 on one call shouldn't hide the log check
            out["errors"].append(f"{key}: {type(e).__name__}: {e}"[:300])
    out["log"] = log_health(bot.path(bot.log_file), now, days)
    if bot.num == 2:
        out["rotation_state"] = _json(bot.path("rotation_state.json"))
    if bot.num == 1:
        out["fills"] = fills(bot, client, now, days)
    return out


def fills(bot: Bot, client, now: datetime, days: int) -> dict:
    """Bot 1's real slippage (bot.fills): wanted price vs Alpaca's fill."""
    from .fills import check

    path = bot.path("fills/signals.csv")
    if not path.exists():
        return {"entries": 0}
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if datetime.fromisoformat(r["time"]) >= now - timedelta(days=days)]
    try:
        got = check(rows, lambda oid: client.get_order_by_id(oid, nested=True)) if rows else []
    except Exception as e:
        return {"entries": len(rows), "error": f"{type(e).__name__}: {e}"[:300]}
    bps = [r["entry_bps"] for r in got] + [r["exit_bps"] for r in got if r["exit"] == "stop"]
    return {"entries": len(got), "fills": len(bps), "avg_bps": round(sum(bps) / len(bps), 2) if bps else None}


# ---------------------------------------------------------------- Kalshi

def kalshi_bot(bot: Bot, now: datetime, days: int) -> dict:
    """Kalshi bots write their own state (and the paper bot a summary); Scout only reads them
    (Kalshi is blocked from the cloud anyway)."""
    out: dict = {"name": bot.name, "label": bot.tag, "kind": "kalshi", "start": bot.start_equity, "errors": []}
    for mode, folder, state, logname in bot.runs:
        summary = _json(bot.path(folder) / "summary.json")
        st = _json(bot.path(state))
        lg = log_health(bot.path(logname), now, days)
        if summary is None and st is None and not lg.get("exists"):
            continue
        st = st if isinstance(st, dict) and "error" not in st else {}
        losses = [c for c in st.get("closed", []) if _f(c.get("pnl")) < 0]
        out[mode] = {"summary": summary, "realized": _f(st.get("realized")), "open": len(st.get("open", [])),
                     "closed": len(st.get("closed", [])), "losing_trades": len(losses),
                     "stray": sum(1 for b in st.get("open", []) if b.get("sets", 1) == 0),
                     "quotes": len(st.get("quotes", [])), "log": lg}
    if not any(m in out for m, *_ in bot.runs):
        out["errors"].append(f"no Kalshi summary, state or log files in folder '{bot.home}'")
    return out


CRASH = re.compile(r"Traceback|Error|Exception")
CHATTER = re.compile(r"^\d{4}-\d{2}-\d{2} [\d:,]+ (DEBUG|INFO|WARNING) ")  # normal log lines that landed on stderr


def err_logs(bots: list[Bot], now: datetime) -> list[dict]:
    """Every *_err.log next to the bots: a scheduled task sends crashes there (normal output goes to stdout).
    Only Traceback / Error / Exception lines count, each with its byte offset so Medic can tell new from old."""
    out, seen = [], set()
    for home in dict.fromkeys(b.home for b in bots):
        for p in sorted(Path(home).glob("*_err.log")):
            if p.resolve() in seen or not p.stat().st_size:
                continue
            seen.add(p.resolve())
            crashes, offset = [], 0
            with p.open("rb") as f:
                for raw in f:
                    line = raw.decode("utf-8", errors="ignore").rstrip()
                    if CRASH.search(line) and not CHATTER.match(line):
                        crashes.append({"at": offset, "line": line[:300]})
                    offset += len(raw)
            out.append({"home": home, "file": p.name, "size": p.stat().st_size,
                        "modified": datetime.fromtimestamp(p.stat().st_mtime, ET).isoformat(timespec="seconds"),
                        "crashes": crashes[-20:]})
    return out


# ---------------------------------------------------------------- market and news

def market_rows(closes) -> list[dict]:
    """closes: daily close DataFrame, one column per symbol."""
    rows = []
    for sym in closes.columns:
        c = closes[sym].dropna()
        if len(c) < 2:
            continue
        rets = c.pct_change().dropna()
        rows.append({
            "symbol": sym, "day": c.index[-1].date().isoformat() if hasattr(c.index[-1], "date") else str(c.index[-1]),
            "close": round(float(c.iloc[-1]), 4),
            "chg_1d_pct": round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
            "chg_1m_pct": round(float(c.iloc[-1] / c.iloc[-22] - 1) * 100, 2) if len(c) > 22 else None,
            "above_200d": bool(c.iloc[-1] > c.iloc[-200:].mean()) if len(c) >= 200 else None,
            "above_50d": bool(c.iloc[-1] > c.iloc[-50:].mean()) if len(c) >= 50 else None,
            "vol_20d_pct": round(float(rets.iloc[-20:].std() * (252 ** 0.5) * 100), 1) if len(rets) >= 20 else None,
        })
    return rows


def stock_closes(symbols: list[str], key: str, secret: str, now: datetime):
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    df = StockHistoricalDataClient(key, secret).get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbols, timeframe=TimeFrame.Day, adjustment=Adjustment.ALL, feed="iex",
        start=now - timedelta(days=430))).df["close"].unstack(level="symbol")
    df.index = [t.tz_convert(ET) for t in df.index]
    return df.ffill()


def crypto_closes(symbols: list[str], now: datetime):
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    df = CryptoHistoricalDataClient().get_crypto_bars(CryptoBarsRequest(
        symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=now - timedelta(days=430))).df["close"].unstack(level="symbol")
    today = now.astimezone(timezone.utc).date()
    return df[[t.date() < today for t in df.index]].ffill()  # finished days only


def headlines(symbols: list[str], key: str, secret: str, now: datetime) -> list[dict]:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest

    client, out = NewsClient(key, secret), []
    for sym in symbols:
        items = client.get_news(NewsRequest(symbols=sym, start=now - timedelta(hours=24), end=now, limit=5)).data.get("news", [])
        out += [{"symbol": sym, "time": _iso(n.created_at), "headline": n.headline, "source": n.source} for n in items]
    return out


BENCHMARKS = ("SPY", "BTC/USD", "ETH/USD")


def bench_rows(closes, symbols) -> list[dict]:
    return [{"day": (t.date() if hasattr(t, "date") else t).isoformat(), "symbol": sym, "close": round(float(v), 4)}
            for sym in symbols if sym in closes.columns for t, v in closes[sym].dropna().items()]


def market(bots: list[Bot], now: datetime) -> tuple[dict, list[str]]:
    errors: list[str] = []
    key = secret = ""
    for b in bots:  # market data works with any bot's keys
        if b.kind == "alpaca":
            key, secret = keys(b)
            if key:
                break
    stocks = sorted({s for b in bots for s in b.symbols if "/" not in s})
    coins = sorted({s for b in bots for s in b.symbols if "/" in s})
    rows, news, bench = [], [], []
    if key:
        try:
            closes = stock_closes(stocks, key, secret, now)
            rows += market_rows(closes)
            bench += bench_rows(closes, BENCHMARKS)
        except Exception as e:
            errors.append(f"stock prices: {type(e).__name__}: {e}"[:300])
        try:
            news = headlines([s for s in bots[0].symbols if "/" not in s], key, secret, now)
        except Exception as e:
            errors.append(f"news: {type(e).__name__}: {e}"[:300])
    else:
        errors.append("stock prices: no Alpaca keys found in any bot's env file")
    if coins:
        try:
            closes = crypto_closes(coins, now)
            rows += market_rows(closes)
            bench += bench_rows(closes, BENCHMARKS)
        except Exception as e:
            errors.append(f"crypto prices: {type(e).__name__}: {e}"[:300])
    spy = next((r for r in rows if r["symbol"] == "SPY"), None)
    regime = {}
    if spy:
        regime = {"spy_above_200d": spy["above_200d"], "spy_vol_20d_pct": spy["vol_20d_pct"],
                  "calm": spy["vol_20d_pct"] is not None and spy["vol_20d_pct"] < 20}
    return {"symbols": rows, "news": news, "regime": regime, "benchmarks": bench}, errors


def market_clock(client, now: datetime) -> dict:
    c = client.get_clock()
    today = now.astimezone(ET).date()
    try:
        from alpaca.trading.requests import GetCalendarRequest

        cal = client.get_calendar(GetCalendarRequest(start=today, end=today))
        trading_day = any(getattr(d, "date", None) == today for d in cal)
    except Exception:
        trading_day = today.weekday() < 5
    return {"is_open": bool(c.is_open), "next_open": _iso(c.next_open), "next_close": _iso(c.next_close),
            "trading_day": trading_day}


# ---------------------------------------------------------------- Windows scheduled tasks

TASKS_PS = (
    "Get-ScheduledTask | Where-Object { $_.TaskName -match 'bot|kalshi|fleet' } | ForEach-Object { "
    "$i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ name = $_.TaskName; state = [string]$_.State; "
    "last_run = $i.LastRunTime.ToString('o'); last_result = $i.LastTaskResult; next_run = if ($i.NextRunTime) "
    "{ $i.NextRunTime.ToString('o') } else { '' } } } | ConvertTo-Json -Depth 2"
)


def scheduled_tasks(run=None) -> list[dict]:
    """The bots' Windows tasks: state (Running/Ready/Disabled), last run, last result code. [] off Windows."""
    import subprocess
    import sys

    if run is None:
        if sys.platform != "win32":
            return []
        run = lambda: subprocess.run(["powershell", "-NoProfile", "-Command", TASKS_PS], capture_output=True,
                                     text=True, timeout=60).stdout
    text = (run() or "").strip()
    if not text:
        return []
    got = json.loads(text)
    return [got] if isinstance(got, dict) else got


# ---------------------------------------------------------------- run and save

def collect(bots: list[Bot], now: datetime, days: int = 30, with_market: bool = True, client_for=trading_client,
            tasks=scheduled_tasks) -> dict:
    snap: dict = {"taken": now.isoformat(timespec="seconds"), "bots": {}, "errors": []}
    try:
        snap["tasks"] = tasks()
    except Exception as e:
        snap["errors"].append(f"scheduled tasks: {type(e).__name__}: {e}"[:300])
    try:
        snap["err_logs"] = err_logs(bots, now)
    except Exception as e:
        snap["errors"].append(f"crash logs: {type(e).__name__}: {e}"[:300])
    clock_done = False
    for b in bots:
        if b.kind == "kalshi":
            snap["bots"][str(b.num)] = kalshi_bot(b, now, days)
            continue
        try:
            client = client_for(b)
        except Exception as e:
            snap["bots"][str(b.num)] = {"name": b.name, "label": b.tag, "kind": b.kind, "errors": [f"connect: {e}"[:300]],
                                        "log": log_health(b.path(b.log_file), now, days)}
            continue
        snap["bots"][str(b.num)] = alpaca_bot(b, client, now, days)
        if not clock_done:
            try:
                snap["clock"] = market_clock(client, now)
                clock_done = True
            except Exception as e:
                snap["errors"].append(f"clock: {type(e).__name__}: {e}"[:300])
    if with_market:
        snap["market"], errs = market(bots, now)
        snap["errors"] += errs
    return snap


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def bot_equity(snap_bot: dict) -> float | None:
    if "account" in snap_bot:
        return snap_bot["account"]["equity"]
    for mode in ("paper", "maker", "maker_paper", "demo"):  # Kalshi: its summary, else start + settled profit
        m = snap_bot.get(mode)
        if not m:
            continue
        s = m.get("summary") or {}
        return _f(s["equity"]) if "equity" in s else snap_bot.get("start", 0) + m.get("realized", 0)
    return None


def save(snap: dict, out: Path = OUT) -> None:
    out.mkdir(exist_ok=True)
    (out / "history").mkdir(exist_ok=True)
    text = json.dumps(snap, indent=1, default=str)
    (out / "snapshot.json").write_text(text)
    day = datetime.fromisoformat(snap["taken"]).astimezone(ET).date().isoformat()
    (out / "history" / f"{day}.json").write_text(text)

    # equity.csv: Alpaca's own daily history fills gaps; today's row is replaced by the latest reading
    rows = {(r["day"], r["bot"]): r for r in _read_csv(out / "equity.csv")}
    for num, b in snap["bots"].items():
        for h in b.get("equity_history", []):
            if h["equity"] <= 0:  # Alpaca reports $0 for days before the account was funded
                continue
            rows.setdefault((h["day"], num), {"day": h["day"], "bot": num, "equity": h["equity"]})
        eq = bot_equity(b)
        if eq is not None:
            rows[(day, num)] = {"day": day, "bot": num, "equity": round(eq, 2)}
    _write_csv(out / "equity.csv", sorted(rows.values(), key=lambda r: (r["day"], int(r["bot"]))), ["day", "bot", "equity"])

    trades = {r["order_id"]: r for r in _read_csv(out / "trades.csv")}
    for num, b in snap["bots"].items():
        for o in b.get("orders", []):
            trades[o["order_id"]] = {**o, "bot": num}
    _write_csv(out / "trades.csv", sorted(trades.values(), key=lambda r: r["time"]),
               ["time", "bot", "symbol", "side", "qty", "price", "type", "order_id"])

    _write_csv(out / "positions.csv", [{**p, "bot": num} for num, b in snap["bots"].items() for p in b.get("positions", [])],
               ["bot", "symbol", "qty", "avg_entry", "market_value", "unrealized_pl"])
    m = snap.get("market", {})
    _write_csv(out / "market.csv", m.get("symbols", []),
               ["symbol", "day", "close", "chg_1d_pct", "chg_1m_pct", "above_50d", "above_200d", "vol_20d_pct"])
    _write_csv(out / "news.csv", m.get("news", []), ["symbol", "time", "headline", "source"])
    bench = {(r["day"], r["symbol"]): r for r in _read_csv(out / "benchmarks.csv")}
    bench.update({(r["day"], r["symbol"]): r for r in m.get("benchmarks", [])})
    _write_csv(out / "benchmarks.csv", sorted(bench.values(), key=lambda r: (r["day"], r["symbol"])), ["day", "symbol", "close"])


def describe(snap: dict) -> str:
    lines = [f"Scout: fleet data at {snap['taken']}"]
    for num, b in snap["bots"].items():
        eq = bot_equity(b)
        held = ", ".join(p["symbol"] for p in b.get("positions", [])) or "nothing"
        bits = [f"equity ${eq:,.2f}" if eq is not None else "no equity reading", f"holds {held}"]
        if b.get("orders") is not None:
            bits.append(f"{len(b['orders'])} fills")
        if b.get("errors"):
            bits.append(f"{len(b['errors'])} errors")
        lines.append(f"  Bot {b.get('label', num)} {b['name']}: " + ", ".join(bits))
    if snap.get("market", {}).get("regime"):
        r = snap["market"]["regime"]
        lines.append(f"  Market: SPY {'above' if r['spy_above_200d'] else 'below'} its 200-day average, "
                     f"20-day volatility {r['spy_vol_20d_pct']}%")
    for e in snap["errors"]:
        lines.append(f"  ! {e}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Scout, the data bot: collect fleet data (read-only)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-market", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    snap = collect(load(), datetime.now(timezone.utc), args.days, not args.no_market)
    save(snap)
    print(describe(snap))
    print(f"\nSaved to {OUT.resolve()}")


if __name__ == "__main__":
    main()
