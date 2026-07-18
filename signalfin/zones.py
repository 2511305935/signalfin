"""价格区间哨兵 — zone trigger detection.

Zones are decisions already made in finefin (分批买入区/减仓线/执行线).
This module only answers "价格到了没", never "该不该买卖".
Dedup follows the prev_state mechanism: push once on crossing into a zone
(or on first run of a session if already inside).
"""

from __future__ import annotations

import os

import yaml


def load_zones() -> dict:
    """Load zone config from ZONES env var (YAML string) or local zones.yaml.

    Returns {"stocks": {symbol: {...}}, "ah_premium": [...]}.
    """
    raw = os.environ.get("ZONES", "")
    if raw:
        cfg = yaml.safe_load(raw) or {}
    else:
        path = os.path.join(os.path.dirname(__file__), "..", "zones.yaml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}
    cfg.setdefault("stocks", {})
    cfg.setdefault("ah_premium", [])
    return cfg


def check_zones(symbol: str, price: float, stock_cfg: dict,
                prev_state: dict | None) -> tuple[list[dict], dict]:
    """Check price against configured lines for one stock.

    stock_cfg: {"name": str, "lines": [{"price", "when", "tag", "action", "source"}]}
      when: "below" — trigger when price <= line price (买入区/执行线)
            "above" — trigger when price >= line price (减仓线)

    Returns (alerts, state). State keys "zone_<i>" hold "in"/"out".
    """
    state = {}
    alerts = []
    name = stock_cfg.get("name", "")
    label = f"【{symbol} {name}】" if name else f"【{symbol}】"

    for i, line in enumerate(stock_cfg.get("lines", [])):
        try:
            level = float(line["price"])
        except (KeyError, TypeError, ValueError):
            continue
        when = line.get("when", "below")
        in_zone = price <= level if when == "below" else price >= level
        key = f"zone_{i}"
        state[key] = "in" if in_zone else "out"

        if in_zone and _changed(prev_state, state, key):
            tag = line.get("tag", "区间")
            action = line.get("action", "")
            source = line.get("source", "")
            op = "≤" if when == "below" else "≥"
            text = f"{label}{price} 触发{tag}({op}{level})"
            if action:
                text += f" → {action}"
            if source:
                text += f" [出处: {source}]"
            alerts.append({"symbol": symbol, "tag": tag, "text": text})

    return alerts, state


def check_ah_premium(pair_cfg: dict, prices: dict[str, float],
                     prev_state: dict | None) -> tuple[list[dict], dict]:
    """Check A/H premium for one pair.

    pair_cfg: {"name", "a", "h", "fx", "buy_h_above", "switch_a_below", "note"}
    prices: {a_symbol: price(CNY), h_symbol: price(HKD), fx_symbol: HKD->CNY rate}
    premium = a / (h * fx) - 1, in percent. fx MUST be a live quote
    (7/19 教训: 硬编码汇率曾令结论整个翻转).

    Returns (alerts, state). State key "ah" holds buy_h / mid / switch_a.
    """
    a_sym, h_sym, fx_sym = pair_cfg["a"], pair_cfg["h"], pair_cfg["fx"]
    a_price = prices[a_sym]
    h_price = prices[h_sym]
    fx = prices[fx_sym]
    premium = (a_price / (h_price * fx) - 1) * 100

    buy_h_above = float(pair_cfg.get("buy_h_above", 12))
    switch_a_below = float(pair_cfg.get("switch_a_below", 8))

    state = {}
    if premium > buy_h_above:
        state["ah"] = "buy_h"
    elif premium < switch_a_below:
        state["ah"] = "switch_a"
    else:
        state["ah"] = "mid"
    state["_premium"] = round(premium, 1)

    alerts = []
    if _changed(prev_state, state, "ah") and state["ah"] != "mid":
        name = pair_cfg.get("name", f"{a_sym}/{h_sym}")
        detail = (f"A={a_price} H={h_price} 汇率={fx:.4f} "
                  f"→ 溢价{premium:+.1f}%")
        if state["ah"] == "buy_h":
            text = f"【{name}】溢价{premium:+.1f}% > {buy_h_above}% → 买H。{detail}"
        else:
            text = (f"【{name}】溢价{premium:+.1f}% < {switch_a_below}% "
                    f"→ 评估切回A。{detail}")
        note = pair_cfg.get("note", "")
        if note:
            text += f" [备注: {note}]"
        alerts.append({"symbol": h_sym, "tag": "AH溢价", "text": text})

    return alerts, state


def _changed(prev: dict | None, curr: dict, key: str) -> bool:
    if prev is None:
        return True
    return prev.get(key) != curr.get(key)
