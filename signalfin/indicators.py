"""Technical indicators: MA, EMA, MACD, RSI, Bollinger Bands, KDJ."""

import numpy as np
import pandas as pd


def calc_ma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26,
              signal: int = 9) -> dict:
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return {"dif": dif, "dea": dea, "hist": hist}


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_boll(close: pd.Series, period: int = 20,
              std_mult: float = 2.0) -> dict:
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return {
        "upper": mid + std_mult * std,
        "mid": mid,
        "lower": mid - std_mult * std,
    }


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
             n: int = 9, m1: int = 3, m2: int = 3) -> dict:
    lowest = low.rolling(window=n).min()
    highest = high.rolling(window=n).max()
    rsv = (close - lowest) / (highest - lowest).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {"k": k, "d": d, "j": j}
