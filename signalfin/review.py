"""Daily session review & next-day trading guidance."""

import os
from datetime import datetime, timezone, timedelta

from signalfin.fetcher import fetch_realtime
from signalfin.notify import send_bark

CST = timezone(timedelta(hours=8))


def _stock_label(symbol: str, holdings: dict, rt: dict) -> str:
    """Format as 【symbol name】following signalfin convention."""
    h_name = holdings.get(symbol, {}).get("name")
    name = h_name or rt.get("name", "")
    if name:
        return f"【{symbol} {name}】"
    return f"【{symbol}】"


def _parse_pipe_kv(env_key: str, val_count: int = 1) -> dict:
    """Parse 'key:v1:v2|key:v1:v2' env vars."""
    raw = os.environ.get(env_key, "")
    if not raw:
        return {}
    result = {}
    for entry in raw.split("|"):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        parts = entry.split(":", val_count)
        if len(parts) < val_count + 1:
            continue
        result[parts[0].strip()] = parts[1:] if val_count > 1 else parts[1].strip()
    return result


def parse_holdings() -> dict[str, dict]:
    """Parse HOLDINGS env var. Format: 'symbol:qty:cost:name|symbol:qty:cost:name'

    Name field is optional.
    """
    raw = os.environ.get("HOLDINGS", "")
    if not raw:
        return {}
    result = {}
    for entry in raw.split("|"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 3:
            continue
        try:
            d = {"qty": float(parts[1]), "cost": float(parts[2])}
            if len(parts) >= 4 and parts[3]:
                d["name"] = parts[3]
            result[parts[0].strip()] = d
        except ValueError:
            pass
    return result


def parse_actions() -> dict[str, str]:
    """Parse ACTIONS env var. Format: 'symbol:action_text|symbol:action_text'"""
    return _parse_pipe_kv("ACTIONS", 1)


def parse_stop_loss() -> dict[str, float]:
    """Parse STOP_LOSS env var. Format: 'symbol:price,symbol:price'"""
    raw = os.environ.get("STOP_LOSS", "")
    if not raw:
        return {}
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        s, p = pair.split(":", 1)
        try:
            result[s.strip()] = float(p.strip())
        except ValueError:
            pass
    return result


def filter_by_session(stocks: list[str], session: str) -> list[str]:
    if session == "asia":
        return [s for s in stocks if s.endswith((".HK", ".SS", ".SZ"))]
    return [s for s in stocks if not s.endswith((".HK", ".SS", ".SZ"))]


def build_review(session: str, stocks: list[str]) -> tuple[str, str] | None:
    """Build daily review message.

    Returns (title, body) or None if no data.
    """
    session_stocks = filter_by_session(stocks, session)
    if not session_stocks:
        return None

    holdings = parse_holdings()
    actions = parse_actions()
    stop_loss = parse_stop_loss()

    results = []
    for symbol in session_stocks:
        try:
            rt = fetch_realtime(symbol)
            results.append(rt)
        except Exception as e:
            print(f"[review] {symbol}: {e}")

    if not results:
        return None

    # Sort by change ascending (worst first)
    results.sort(key=lambda r: r.get("change_pct", 0))

    now = datetime.now(CST)
    session_name = "港A股" if session == "asia" else "美股"
    next_label = "明日" if session == "asia" else "今日"

    lines = [f"{session_name}收盘复盘 {now.strftime('%m/%d %H:%M')}", ""]

    # --- Performance table ---
    lines.append("—— 持仓表现 ——")
    for r in results:
        sym = r["symbol"]
        price = r["price"]
        chg = r.get("change_pct", 0)
        icon = "\U0001f534" if chg < -2 else ("\U0001f7e2" if chg > 2 else "\u26aa")
        label = _stock_label(sym, holdings, r)

        sign = "+" if chg >= 0 else ""
        part = f"{icon} {label} {price} ({sign}{chg:.1f}%)"

        if sym in holdings and holdings[sym]["cost"] > 0:
            h = holdings[sym]
            pnl = (price - h["cost"]) / h["cost"] * 100
            psign = "+" if pnl >= 0 else ""
            part += f" [{psign}{pnl:.0f}%]"

        lines.append(part)

    # --- Big movers (>3%) ---
    movers = [r for r in results if abs(r.get("change_pct", 0)) >= 3]
    if movers:
        lines.extend(["", "—— 异动提醒 ——"])
        for r in movers:
            label = _stock_label(r["symbol"], holdings, r)
            chg = r["change_pct"]
            tag = "大涨" if chg > 0 else "大跌"
            lines.append(f"\u26a1 {label} {tag}{abs(chg):.1f}%")

    # --- Stop-loss proximity (<5%) ---
    sl_items = []
    for r in results:
        if r["symbol"] in stop_loss:
            target = stop_loss[r["symbol"]]
            dist = (r["price"] - target) / target * 100
            if dist < 5:
                label = _stock_label(r["symbol"], holdings, r)
                sl_items.append(f"\u26a0\ufe0f {label} 距止损{target}仅{dist:.1f}%")
    if sl_items:
        lines.extend(["", "—— 止损监控 ——"])
        lines.extend(sl_items)

    # --- Action guidance ---
    action_items = []
    for r in results:
        if r["symbol"] in actions:
            label = _stock_label(r["symbol"], holdings, r)
            action_items.append(f"\u2192 {label}: {actions[r['symbol']]}")
    if action_items:
        lines.extend(["", f"—— {next_label}操作指引 ——"])
        lines.extend(action_items)
    elif not actions:
        lines.extend(["", f"—— {next_label}操作指引 ——", "（未配置，设置ACTIONS环境变量）"])

    worst = results[0]["change_pct"]
    best = results[-1]["change_pct"]
    title = f"\U0001f4ca {session_name}复盘 {worst:+.1f}%~{best:+.1f}%"

    return title, "\n".join(lines)


def send_review(session: str, stocks: list[str], bark_url: str | None) -> bool:
    """Generate and push daily review. Returns True if sent."""
    result = build_review(session, stocks)
    if not result:
        print(f"[review] No data for session '{session}'")
        return False

    title, body = result
    print(f"[review] {title}")
    print(body)

    if bark_url:
        ok = send_bark(bark_url, title, body, group="signalfin-review")
        print(f"[review] push {'sent' if ok else 'FAILED'}")
        return ok
    else:
        print("[review] BARK_URL not set, printed only")
        return False
