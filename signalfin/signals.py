"""Signal detection with Chinese reason text. Deduplication via state tracking."""

from __future__ import annotations

import pandas as pd
from signalfin.indicators import calc_ma, calc_macd, calc_rsi, calc_boll, calc_kdj


def detect_signals(kline: pd.DataFrame, symbol: str,
                   prev_state: dict | None = None) -> tuple[list[dict], dict]:
    """Detect technical signals and generate trading reasons.

    Args:
        kline: DataFrame with open/high/low/close/volume columns
        symbol: ticker symbol for display
        prev_state: previous signal state for dedup (None = first run)

    Returns:
        (new_signals, current_state)
        new_signals: list of dicts with keys: type, direction, reason, value
        current_state: dict to pass as prev_state next time
    """
    close = kline["close"]
    high = kline["high"]
    low = kline["low"]
    volume = kline["volume"]
    price = close.iloc[-1]

    state = {}
    signals = []

    # --- MACD ---
    macd = calc_macd(close)
    dif = macd["dif"].iloc[-1]
    dea = macd["dea"].iloc[-1]
    hist = macd["hist"].iloc[-1]
    prev_hist = macd["hist"].iloc[-2] if len(macd["hist"]) >= 2 else 0

    if dif > dea:
        state["macd"] = "golden_above" if dif > 0 else "golden"
    else:
        state["macd"] = "death_below" if dif < 0 else "death"

    if _changed(prev_state, state, "macd"):
        if state["macd"] == "golden_above":
            signals.append({
                "type": "MACD", "direction": "bullish",
                "reason": f"MACD金叉(零轴上方)，DIF={dif:.3f}上穿DEA={dea:.3f}，强势动能",
                "value": f"DIF={dif:.3f}"
            })
        elif state["macd"] == "golden":
            signals.append({
                "type": "MACD", "direction": "bullish",
                "reason": f"MACD金叉，DIF={dif:.3f}上穿DEA={dea:.3f}，动能转多",
                "value": f"DIF={dif:.3f}"
            })
        elif state["macd"] == "death_below":
            signals.append({
                "type": "MACD", "direction": "bearish",
                "reason": f"MACD死叉(零轴下方)，DIF={dif:.3f}，空头加速",
                "value": f"DIF={dif:.3f}"
            })
        elif state["macd"] == "death":
            signals.append({
                "type": "MACD", "direction": "bearish",
                "reason": f"MACD死叉，DIF={dif:.3f}下穿DEA={dea:.3f}，动能衰减",
                "value": f"DIF={dif:.3f}"
            })

    # --- RSI ---
    rsi = calc_rsi(close).iloc[-1]
    if rsi >= 80:
        state["rsi"] = "severe_overbought"
    elif rsi >= 70:
        state["rsi"] = "overbought"
    elif rsi <= 20:
        state["rsi"] = "severe_oversold"
    elif rsi <= 30:
        state["rsi"] = "oversold"
    else:
        state["rsi"] = "neutral"

    if _changed(prev_state, state, "rsi"):
        rsi_msgs = {
            "severe_overbought": (
                "bearish", f"RSI={rsi:.1f} 极度超买，强烈回调风险"),
            "overbought": (
                "bearish", f"RSI={rsi:.1f} 进入超买区，注意回调风险"),
            "severe_oversold": (
                "bullish", f"RSI={rsi:.1f} 极度超卖，关注强力反弹机会"),
            "oversold": (
                "bullish", f"RSI={rsi:.1f} 进入超卖区，关注反弹机会"),
            "neutral": (
                "neutral", f"RSI={rsi:.1f} 回到中性区间"),
        }
        direction, reason = rsi_msgs[state["rsi"]]
        signals.append({
            "type": "RSI", "direction": direction,
            "reason": reason, "value": f"RSI={rsi:.1f}"
        })

    # --- Moving Average Arrangement ---
    ma5 = calc_ma(close, 5).iloc[-1]
    ma20 = calc_ma(close, 20).iloc[-1]
    ma60 = calc_ma(close, 60).iloc[-1] if len(close) >= 60 else None

    if ma60 is not None and price > ma5 > ma20 > ma60:
        state["ma_arr"] = "bullish"
    elif ma60 is not None and price < ma5 < ma20 < ma60:
        state["ma_arr"] = "bearish"
    elif price > ma20:
        state["ma_arr"] = "above_ma20"
    elif price < ma20:
        state["ma_arr"] = "below_ma20"
    else:
        state["ma_arr"] = "neutral"

    if _changed(prev_state, state, "ma_arr"):
        ma_msgs = {
            "bullish": ("bullish", "均线多头排列(价格>MA5>MA20>MA60)，趋势向上"),
            "bearish": ("bearish", "均线空头排列(价格<MA5<MA20<MA60)，趋势向下"),
            "above_ma20": ("bullish", f"站上MA20({ma20:.2f})，短期趋势转强"),
            "below_ma20": ("bearish", f"跌破MA20({ma20:.2f})，短期趋势转弱"),
            "neutral": ("neutral", "均线交织，方向不明"),
        }
        direction, reason = ma_msgs[state["ma_arr"]]
        signals.append({
            "type": "均线", "direction": direction,
            "reason": reason, "value": f"MA5={ma5:.2f} MA20={ma20:.2f}"
        })

    # --- MA20 Crossover (with volume) ---
    if len(close) >= 2:
        prev_close = close.iloc[-2]
        prev_ma20 = calc_ma(close, 20).iloc[-2] if len(close) >= 21 else None
        if prev_ma20 is not None:
            vol_ratio = volume.iloc[-1] / volume.iloc[-5:].mean() if volume.iloc[-5:].mean() > 0 else 1
            crossed_up = prev_close < prev_ma20 and price > ma20
            crossed_down = prev_close > prev_ma20 and price < ma20
            if crossed_up:
                vol_text = f"放量({vol_ratio:.1f}x)" if vol_ratio > 1.2 else "缩量"
                state["ma20_cross"] = "up"
                if _changed(prev_state, state, "ma20_cross"):
                    signals.append({
                        "type": "MA20突破", "direction": "bullish",
                        "reason": f"{vol_text}突破MA20({ma20:.2f})，短期趋势转强",
                        "value": f"MA20={ma20:.2f}"
                    })
            elif crossed_down:
                state["ma20_cross"] = "down"
                if _changed(prev_state, state, "ma20_cross"):
                    signals.append({
                        "type": "MA20跌破", "direction": "bearish",
                        "reason": f"跌破MA20({ma20:.2f})，短期支撑失守",
                        "value": f"MA20={ma20:.2f}"
                    })
            else:
                state["ma20_cross"] = "none"

    # --- Bollinger Bands ---
    boll = calc_boll(close)
    upper = boll["upper"].iloc[-1]
    lower = boll["lower"].iloc[-1]
    band_width = upper - lower
    if band_width > 0:
        position = (price - lower) / band_width
        if position >= 0.95:
            state["boll"] = "upper_touch"
        elif position <= 0.05:
            state["boll"] = "lower_touch"
        else:
            state["boll"] = "mid"

        if _changed(prev_state, state, "boll"):
            if state["boll"] == "upper_touch":
                signals.append({
                    "type": "布林带", "direction": "bearish",
                    "reason": f"触及布林上轨({upper:.2f})，短期超买注意回落",
                    "value": f"上轨={upper:.2f}"
                })
            elif state["boll"] == "lower_touch":
                signals.append({
                    "type": "布林带", "direction": "bullish",
                    "reason": f"触及布林下轨({lower:.2f})，超跌反弹概率大",
                    "value": f"下轨={lower:.2f}"
                })

    # --- Price Spike ---
    if len(close) >= 2:
        daily_change = (price - close.iloc[-2]) / close.iloc[-2] * 100
        if abs(daily_change) >= 3:
            direction = "bullish" if daily_change > 0 else "bearish"
            emoji = "涨" if daily_change > 0 else "跌"
            state["spike"] = f"{emoji}_{abs(daily_change):.0f}"
            if _changed(prev_state, state, "spike"):
                signals.append({
                    "type": "异动", "direction": direction,
                    "reason": f"日内{emoji}幅{daily_change:+.1f}%，异动关注",
                    "value": f"{daily_change:+.1f}%"
                })
        else:
            state["spike"] = "normal"

    # --- KDJ ---
    if len(close) >= 9:
        kdj = calc_kdj(high, low, close)
        k_val = kdj["k"].iloc[-1]
        d_val = kdj["d"].iloc[-1]
        j_val = kdj["j"].iloc[-1]
        if k_val > d_val and j_val > 100:
            state["kdj"] = "overbought"
        elif k_val > d_val and j_val < 20:
            state["kdj"] = "oversold_cross"
        elif k_val > d_val:
            state["kdj"] = "golden"
        elif k_val < d_val:
            state["kdj"] = "death"
        else:
            state["kdj"] = "neutral"

        if _changed(prev_state, state, "kdj"):
            kdj_msgs = {
                "overbought": ("bearish", f"KDJ超买(J={j_val:.0f}>100)，注意短线回调"),
                "oversold_cross": ("bullish", f"KDJ超卖金叉(J={j_val:.0f}<20)，反弹信号"),
                "golden": ("bullish", f"KDJ金叉(K={k_val:.0f}>D={d_val:.0f})"),
                "death": ("bearish", f"KDJ死叉(K={k_val:.0f}<D={d_val:.0f})"),
                "neutral": ("neutral", "KDJ中性"),
            }
            direction, reason = kdj_msgs[state["kdj"]]
            if state["kdj"] != "neutral":
                signals.append({
                    "type": "KDJ", "direction": direction,
                    "reason": reason, "value": f"K={k_val:.0f} D={d_val:.0f} J={j_val:.0f}"
                })

    # --- Summary info (always included in state) ---
    state["_rsi_val"] = round(rsi, 1)
    state["_macd_status"] = state["macd"]
    state["_ma_arr"] = state.get("ma_arr", "neutral")
    state["_price"] = round(price, 3)

    return signals, state


def get_action(state: dict) -> tuple[str, str]:
    """Generate action recommendation from signal state combination.

    Returns (action_icon, action_text).
    Action categories:
      - 清仓考虑: trend down + no oversold bounce expected
      - 减仓/止损: trend down + moderate weakness
      - 观望持有: mixed or neutral
      - 关注反弹: trend down but oversold
      - 持有: trend up
      - 加仓机会: strong bullish alignment
    """
    macd = state.get("_macd_status", "")
    rsi_state = state.get("rsi", "neutral")
    ma_arr = state.get("_ma_arr", "neutral")
    boll = state.get("boll", "mid")
    kdj = state.get("kdj", "neutral")

    # Score: positive = bullish, negative = bearish
    score = 0
    # MACD
    if macd == "golden_above":
        score += 3
    elif macd == "golden":
        score += 2
    elif macd == "death":
        score -= 2
    elif macd == "death_below":
        score -= 3

    # MA arrangement
    if ma_arr == "bullish":
        score += 2
    elif ma_arr == "above_ma20":
        score += 1
    elif ma_arr == "below_ma20":
        score -= 1
    elif ma_arr == "bearish":
        score -= 2

    # KDJ
    if kdj in ("golden", "oversold_cross"):
        score += 1
    elif kdj in ("death", "overbought"):
        score -= 1

    # RSI modifies the action, not the trend score
    is_oversold = rsi_state in ("oversold", "severe_oversold")
    is_overbought = rsi_state in ("overbought", "severe_overbought")
    is_extreme_oversold = rsi_state == "severe_oversold"
    is_extreme_overbought = rsi_state == "severe_overbought"
    at_boll_lower = boll == "lower_touch"
    at_boll_upper = boll == "upper_touch"

    # Decision matrix
    if score >= 4:
        if is_overbought:
            return "⚠️", "趋势强但超买，持有不追高"
        return "🟢", "多头共振，持有或加仓"
    elif score >= 2:
        if is_overbought:
            return "⚠️", "短线超买，注意回调减仓"
        return "🟢", "趋势偏多，持有"
    elif score >= 0:
        if is_oversold and at_boll_lower:
            return "👀", "超卖+布林下轨，可轻仓博反弹"
        if is_oversold:
            return "👀", "超卖区间，关注反弹机会"
        return "⏸️", "方向不明，观望"
    elif score >= -2:
        if is_extreme_oversold:
            return "👀", "极度超卖，反弹概率大，不宜追空"
        if is_oversold and at_boll_lower:
            return "👀", "超卖+触下轨，短线可能反弹"
        if is_oversold:
            return "👀", "弱势超卖，等企稳信号再操作"
        return "🔴", "趋势偏空，考虑减仓"
    else:  # score <= -3
        if is_extreme_oversold:
            return "👀", "极端超卖，可能有技术反弹，但不接飞刀"
        if is_oversold:
            return "👀", "深度超卖，关注止跌信号"
        if is_extreme_overbought:
            return "🔴", "空头反弹超买，逢高减仓"
        return "🔴", "空头趋势，建议清仓或止损"


def get_status_text(state: dict) -> str:
    """Generate one-line status from current state."""
    rsi = state.get("_rsi_val", 0)
    macd_map = {
        "golden_above": "金叉(零轴上)", "golden": "金叉",
        "death_below": "死叉(零轴下)", "death": "死叉",
    }
    macd_text = macd_map.get(state.get("_macd_status", ""), "—")
    return f"RSI: {rsi} | MACD: {macd_text}"


def check_stop_loss(symbol: str, price: float, stop_price: float,
                    triggered: set) -> dict | None:
    """Check if price hit stop-loss. Returns alert dict or None.

    Only fires once per symbol (tracked via triggered set).
    """
    if symbol in triggered:
        return None
    if price <= stop_price:
        triggered.add(symbol)
        pct = (price - stop_price) / stop_price * 100
        return {
            "symbol": symbol,
            "price": price,
            "stop_price": stop_price,
            "reason": f"⛔ {symbol} 触发止损！现价{price:.3f} ≤ 止损价{stop_price:.3f} ({pct:+.1f}%)",
        }
    return None


def _changed(prev: dict | None, curr: dict, key: str) -> bool:
    if prev is None:
        return True
    return prev.get(key) != curr.get(key)
