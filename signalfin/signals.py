"""Descriptive-only notes: RSI extremes (≤20/≥80) and abnormal volume.

价值框架铁律: 禁止方向性信号与买卖暗示。这里只陈述事实,
决策(买入区/减仓线/否决红线)在 finefin,区间提醒见 zones.py。
Dedup via prev_state, same mechanism as before.
"""

from __future__ import annotations

import pandas as pd

from signalfin.indicators import calc_rsi


def detect_notes(kline: pd.DataFrame, symbol: str,
                 prev_state: dict | None = None) -> tuple[list[dict], dict]:
    """Detect descriptive notes (no direction, no advice).

    Returns (notes, current_state).
    notes: list of {"type", "text"}
    """
    close = kline["close"]
    volume = kline["volume"]

    state = {}
    notes = []

    # --- RSI extremes only (≤20 / ≥80) ---
    rsi = calc_rsi(close).iloc[-1]
    if pd.isna(rsi):
        state["rsi"] = "normal"
    elif rsi <= 20:
        state["rsi"] = "extreme_low"
    elif rsi >= 80:
        state["rsi"] = "extreme_high"
    else:
        state["rsi"] = "normal"

    if state["rsi"] != "normal" and _changed(prev_state, state, "rsi"):
        label = "极端低位(≤20)" if state["rsi"] == "extreme_low" else "极端高位(≥80)"
        notes.append({"type": "RSI", "text": f"RSI={rsi:.1f} {label}"})

    # --- Abnormal volume (vs 20-day average, excluding today) ---
    if len(volume) >= 21:
        avg20 = volume.iloc[-21:-1].mean()
        if avg20 > 0:
            ratio = volume.iloc[-1] / avg20
            state["volume"] = "spike" if ratio >= 2.5 else "normal"
            if state["volume"] == "spike" and _changed(prev_state, state, "volume"):
                notes.append({
                    "type": "放量",
                    "text": f"成交量为20日均量的{ratio:.1f}倍",
                })

    state["_rsi_val"] = None if pd.isna(rsi) else round(float(rsi), 1)
    return notes, state


def _changed(prev: dict | None, curr: dict, key: str) -> bool:
    if prev is None:
        return True
    return prev.get(key) != curr.get(key)
