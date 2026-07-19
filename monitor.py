#!/usr/bin/env python3
"""signalfin monitor — 价格区间哨兵 main entry point.

盘中每 5 分钟轮询价格,触发预设区间(买入区/减仓线/执行线)或
描述性极端值(RSI≤20/≥80、异常放量)时经 Bark 推送。
决策在 finefin,这里只负责"价格到了叫我"。

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
from signalfin.signals import detect_notes
from signalfin.zones import load_zones, check_zones, check_ah_premium
from signalfin.notify import send_bark
from signalfin.review import send_review

CST = timezone(timedelta(hours=8))

SESSIONS = {
    "asia": {
        "name": "港股/A股",
        "start_hour": 9, "start_min": 20,
        "end_hour": 16, "end_min": 10,
        "tz": CST,
    },
    "us": {
        "name": "美股",
        "start_hour": 21, "start_min": 20,
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


def format_zone_message(alerts: list[dict]) -> str:
    lines = [a["text"] for a in alerts]
    lines.append("")
    lines.append(datetime.now(CST).strftime("%m-%d %H:%M"))
    return "\n".join(lines)


def format_notes_message(results: list[dict]) -> str:
    """Format descriptive notes as plain text for Bark push."""
    lines = []
    for r in results:
        rt = r["realtime"]
        change = rt["change_pct"]
        arrow = "+" if change >= 0 else ""
        name = rt.get("name", "")
        label = f"{r['symbol']} {name}" if name else r["symbol"]
        lines.append(f"【{label}】{rt['price']} ({arrow}{change}%)")
        for note in r["notes"]:
            lines.append(f"— {note['type']}: {note['text']}")
        lines.append("")

    lines.append(datetime.now(CST).strftime("%m-%d %H:%M"))
    return "\n".join(lines)


def run_ah_checks(zones_cfg: dict, state_map: dict,
                  price_cache: dict[str, float]) -> list[dict]:
    """Run all configured A/H premium checks. Returns zone-style alerts."""
    alerts = []
    for pair in zones_cfg.get("ah_premium", []):
        try:
            prices = {}
            for sym in (pair["a"], pair["h"], pair["fx"]):
                if sym not in price_cache:
                    price_cache[sym] = fetch_realtime(sym)["price"]
                prices[sym] = price_cache[sym]

            key = f"_ah_{pair['a']}_{pair['h']}"
            pair_alerts, ah_state = check_ah_premium(
                pair, prices, state_map.get(key))
            state_map[key] = ah_state
            alerts.extend(pair_alerts)
            print(f"[AH] {pair.get('name', pair['h'])} "
                  f"溢价{ah_state['_premium']:+.1f}% ({ah_state['ah']})")
        except Exception as e:
            print(f"[AH] {pair.get('name', '?')} Error: {e}")
    return alerts


def run_once(stocks: list[str], state_map: dict, bark_url: str | None,
             zones_cfg: dict | None = None) -> dict:
    """Run one monitoring cycle. Returns updated state_map."""
    if zones_cfg is None:
        zones_cfg = {"stocks": {}, "ah_premium": []}

    zone_alerts = []
    results_with_notes = []
    all_results = []
    price_cache: dict[str, float] = {}

    for symbol in stocks:
        try:
            rt = fetch_realtime(symbol)
            price_cache[symbol] = rt["price"]

            # Zone triggers (区间提醒 — 决策出处随消息附带)
            stock_cfg = zones_cfg["stocks"].get(symbol)
            if stock_cfg:
                if not stock_cfg.get("name") and rt.get("name"):
                    stock_cfg = {**stock_cfg, "name": rt["name"]}
                zkey = f"_zones_{symbol}"
                alerts, zstate = check_zones(
                    symbol, rt["price"], stock_cfg, state_map.get(zkey))
                state_map[zkey] = zstate
                zone_alerts.extend(alerts)

            # Descriptive notes (纯陈述: RSI 极端值/异常放量)
            kline = fetch_kline(symbol, days=60)
            notes, curr_state = detect_notes(kline, symbol, state_map.get(symbol))
            state_map[symbol] = curr_state

            result = {"symbol": symbol, "realtime": rt, "notes": notes}
            all_results.append(result)
            if notes:
                results_with_notes.append(result)

        except Exception as e:
            print(f"[{symbol}] Error: {e}")

    # A/H premium checks (independent of STOCK_LIST membership)
    zone_alerts.extend(run_ah_checks(zones_cfg, state_map, price_cache))

    # Zone alerts — the important ones, send first
    if zone_alerts:
        msg = format_zone_message(zone_alerts)
        title = f"🎯 区间触发: {len(zone_alerts)}项"
        if bark_url:
            ok = send_bark(bark_url, title, msg)
            print(f"[Zones] {'sent' if ok else 'FAILED'} — {len(zone_alerts)} alerts")
        else:
            print(f"[Zones] {title}\n{msg}")

    # Descriptive notes push
    if results_with_notes:
        msg = format_notes_message(results_with_notes)
        title = f"📋 描述提醒: {len(results_with_notes)}只标的"
        if bark_url:
            ok = send_bark(bark_url, title, msg)
            print(f"[Notes] {'sent' if ok else 'FAILED'} — {len(results_with_notes)} stocks")
        else:
            print(f"[Notes] {title}\n{msg}")

    if not zone_alerts and not results_with_notes:
        now = datetime.now(CST).strftime("%H:%M")
        print(f"[{now}] No triggers for {len(all_results)} stocks")

    return state_map


def main():
    parser = argparse.ArgumentParser(description="signalfin 价格区间哨兵")
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

    zones_cfg = load_zones()
    n_lines = sum(len(c.get("lines", [])) for c in zones_cfg["stocks"].values())
    n_ah = len(zones_cfg["ah_premium"])
    if n_lines or n_ah:
        print(f"Zones: {n_lines} lines / {len(zones_cfg['stocks'])} stocks, "
              f"{n_ah} AH pairs")
    else:
        print("WARNING: no zones configured (set ZONES secret or zones.yaml)")

    # 区间配置的标的必须被监控,即使不在 STOCK_LIST(如候选买入区)
    extra = [s for s in zones_cfg["stocks"] if s not in stocks]
    if extra:
        stocks = stocks + extra
        print(f"Added from zones: {', '.join(extra)}")

    state_map: dict[str, dict] = {}

    if args.once or session == "test":
        run_once(stocks, state_map, bark_url, zones_cfg)
        return

    # Loop until session ends
    print(f"Starting {SESSIONS[session]['name']} session loop (interval={INTERVAL}s)")
    while True:
        if not in_session(session):
            print(f"Session {session} ended, exiting")
            break

        run_once(stocks, state_map, bark_url, zones_cfg)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
