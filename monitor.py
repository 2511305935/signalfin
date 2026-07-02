#!/usr/bin/env python3
"""signalfin monitor — main entry point.

Usage:
    python monitor.py --session auto          # auto-detect Asia or US session
    python monitor.py --session asia          # force Asia session
    python monitor.py --session us            # force US session
    python monitor.py --session test --once   # single run for testing
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from signalfin.fetcher import fetch_kline, fetch_realtime
from signalfin.signals import detect_signals, get_status_text, get_action, check_stop_loss
from signalfin.notify import send_bark
from signalfin.review import send_review

CST = timezone(timedelta(hours=8))

SESSIONS = {
    "asia": {
        "name": "港股/A股",
        "start_hour": 9, "start_min": 25,
        "end_hour": 16, "end_min": 10,
        "tz": CST,
    },
    "us": {
        "name": "美股",
        "start_hour": 21, "start_min": 25,
        "end_hour": 4, "end_min": 5,  # next day
        "tz": CST,
    },
}

INTERVAL = 300  # 5 minutes


def get_stock_list() -> list[str]:
    raw = os.environ.get("STOCK_LIST", "")
    if not raw:
        print("ERROR: STOCK_LIST env var not set")
        sys.exit(1)
    return [s.strip() for s in raw.split(",") if s.strip()]


def get_bark_url() -> str | None:
    return os.environ.get("BARK_URL")


def get_stop_loss_map() -> dict[str, float]:
    """Parse STOP_LOSS env var. Format: '0939.HK:7.5,600660.SS:48'"""
    raw = os.environ.get("STOP_LOSS", "")
    if not raw:
        return {}
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        symbol, price_str = pair.split(":", 1)
        try:
            result[symbol.strip()] = float(price_str.strip())
        except ValueError:
            pass
    return result


def detect_session() -> str:
    now = datetime.now(CST)
    h = now.hour
    # Asia: 9:00-16:30, US: 21:00-04:30
    if 9 <= h < 17:
        return "asia"
    elif h >= 21 or h < 5:
        return "us"
    return "asia"  # default


def in_session(session_name: str) -> bool:
    cfg = SESSIONS[session_name]
    now = datetime.now(cfg["tz"])
    h, m = now.hour, now.minute
    t = h * 60 + m
    start = cfg["start_hour"] * 60 + cfg["start_min"]
    end = cfg["end_hour"] * 60 + cfg["end_min"]

    if end > start:
        return start <= t <= end
    else:  # crosses midnight (US session)
        return t >= start or t <= end


def format_message(results: list[dict]) -> str:
    """Format signal results as plain text for Bark push."""
    lines = []

    for r in results:
        symbol = r["symbol"]
        rt = r["realtime"]
        state = r["state"]
        new_signals = r["signals"]

        change = rt["change_pct"]
        arrow = "+" if change >= 0 else ""
        action_icon, action_text = get_action(state)
        name = rt.get("name", "")
        label = f"{symbol} {name}" if name else symbol
        lines.append(f"【{label}】{rt['price']} ({arrow}{change}%)")
        lines.append(get_status_text(state))
        lines.append(f"{action_icon} 操作: {action_text}")

        for sig in new_signals:
            icon = {"bullish": "▲", "bearish": "▼", "neutral": "—"}.get(
                sig["direction"], "—")
            lines.append(f"{icon} {sig['type']}: {sig['reason']}")

        lines.append("")

    now = datetime.now(CST).strftime("%m-%d %H:%M")
    lines.append(now)
    return "\n".join(lines)


def run_once(stocks: list[str], state_map: dict, bark_url: str | None,
             stop_loss_map: dict[str, float] | None = None,
             stop_triggered: set | None = None) -> dict:
    """Run one monitoring cycle. Returns updated state_map."""
    results_with_signals = []
    all_results = []
    stop_alerts = []

    if stop_loss_map is None:
        stop_loss_map = {}
    if stop_triggered is None:
        stop_triggered = set()

    for symbol in stocks:
        try:
            rt = fetch_realtime(symbol)
            kline = fetch_kline(symbol, days=120)
            prev_state = state_map.get(symbol)
            new_signals, curr_state = detect_signals(kline, symbol, prev_state)
            state_map[symbol] = curr_state

            result = {
                "symbol": symbol,
                "realtime": rt,
                "state": curr_state,
                "signals": new_signals,
            }
            all_results.append(result)
            if new_signals:
                results_with_signals.append(result)

            # Stop-loss check
            if symbol in stop_loss_map:
                alert = check_stop_loss(
                    symbol, rt["price"], stop_loss_map[symbol], stop_triggered)
                if alert:
                    stop_alerts.append(alert)

        except Exception as e:
            print(f"[{symbol}] Error: {e}")

    # Stop-loss alerts — send immediately with urgent tone
    if stop_alerts and bark_url:
        sl_lines = [a["reason"] for a in stop_alerts]
        sl_msg = "\n".join(sl_lines)
        sl_title = f"⛔ 止损触发: {len(stop_alerts)}只标的"
        ok = send_bark(bark_url, sl_title, sl_msg)
        status = "sent" if ok else "FAILED"
        print(f"[STOP-LOSS] {status} — {sl_msg}")
    elif stop_alerts:
        for a in stop_alerts:
            print(f"[STOP-LOSS] {a['reason']}")

    # Regular signal push
    if results_with_signals and bark_url:
        msg = format_message(results_with_signals)
        title = f"signalfin: {len(results_with_signals)}只标的有新信号"
        ok = send_bark(bark_url, title, msg)
        status = "sent" if ok else "FAILED"
        print(f"[Push] {status} — {len(results_with_signals)} stocks with signals")
    elif results_with_signals:
        print(format_message(results_with_signals))
    else:
        now = datetime.now(CST).strftime("%H:%M")
        print(f"[{now}] No new signals for {len(all_results)} stocks")

    return state_map


def main():
    parser = argparse.ArgumentParser(description="signalfin stock monitor")
    parser.add_argument("--session", default="auto",
                        choices=["auto", "asia", "us", "test"])
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit (for testing)")
    parser.add_argument("--review", choices=["asia", "us"],
                        help="Send daily review for session and exit")
    args = parser.parse_args()

    stocks = get_stock_list()
    bark_url = get_bark_url()

    # Review mode: generate and push daily review, then exit
    if args.review:
        send_review(args.review, stocks, bark_url)
        return

    print(f"Monitoring {len(stocks)} stocks: {', '.join(stocks)}")
    if not bark_url:
        print("WARNING: BARK_URL not set, will print to stdout")

    session = args.session
    if session == "auto":
        session = detect_session()
    print(f"Session: {session}")

    state_map: dict[str, dict] = {}
    stop_loss_map = get_stop_loss_map()
    stop_triggered: set[str] = set()

    if stop_loss_map:
        print(f"Stop-loss: {', '.join(f'{s}≤{p}' for s, p in stop_loss_map.items())}")

    if args.once or session == "test":
        run_once(stocks, state_map, bark_url, stop_loss_map, stop_triggered)
        return

    # Loop until session ends
    print(f"Starting {SESSIONS[session]['name']} session loop (interval={INTERVAL}s)")
    while True:
        if not in_session(session):
            print(f"Session {session} ended, exiting")
            break

        run_once(stocks, state_map, bark_url, stop_loss_map, stop_triggered)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
