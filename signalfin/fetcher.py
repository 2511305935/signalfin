"""Price data fetcher. yfinance for US/A-shares, Tencent Finance API fallback for HK."""

import requests
import yfinance as yf
import pandas as pd
import numpy as np


def _is_hk(symbol: str) -> bool:
    return symbol.upper().endswith(".HK")


def _hk_code(symbol: str) -> str:
    """Convert '0939.HK' or '1398.HK' to '00939' or '01398'."""
    code = symbol.replace(".HK", "").replace(".hk", "")
    return code.zfill(5)


# --- Tencent Finance API (HK stocks) ---

def _tencent_kline(symbol: str, days: int = 120) -> pd.DataFrame:
    code = _hk_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{code},day,,,{days},qfq"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    bars = data.get("data", {}).get(f"hk{code}", {}).get("day", [])
    if not bars:
        raise ValueError(f"Tencent: no kline data for {symbol}")
    # Each bar: [date, open, close, high, low, volume]
    rows = []
    for bar in bars:
        rows.append({
            "date": bar[0],
            "open": float(bar[1]),
            "close": float(bar[2]),
            "high": float(bar[3]),
            "low": float(bar[4]),
            "volume": float(bar[5]),
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["amount"] = df["close"] * df["volume"]
    return df[["open", "high", "low", "close", "volume", "amount"]]


def _tencent_realtime(symbol: str) -> dict:
    code = _hk_code(symbol)
    url = f"https://qt.gtimg.cn/q=hk{code}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    parts = r.text.split("~")
    if len(parts) < 5:
        raise ValueError(f"Tencent: bad realtime response for {symbol}")
    price = float(parts[3])
    prev_close = float(parts[4])
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
    return {
        "symbol": symbol,
        "price": round(price, 3),
        "prev_close": round(prev_close, 3),
        "change_pct": round(change_pct, 2),
    }


# --- yfinance (US / A-shares) ---

def _yf_history(symbol: str, period: str = "5d") -> pd.DataFrame:
    """Fetch yfinance history with one retry."""
    import time
    for attempt in range(2):
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if not df.empty:
            return df
        if attempt == 0:
            time.sleep(2)
    raise ValueError(f"yfinance: no data for {symbol} (period={period})")


def _yf_kline(symbol: str, days: int = 120) -> pd.DataFrame:
    df = _yf_history(symbol, period=f"{int(days * 1.5)}d")
    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df["amount"] = df["close"] * df["volume"]
    return df[["open", "high", "low", "close", "volume", "amount"]].tail(days)


def _yf_realtime(symbol: str) -> dict:
    hist = _yf_history(symbol, period="5d")
    price = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
    change_pct = (price - prev) / prev * 100 if prev else 0
    return {
        "symbol": symbol,
        "price": round(price, 3),
        "prev_close": round(prev, 3),
        "change_pct": round(change_pct, 2),
    }


# --- Public API ---

def fetch_kline(symbol: str, days: int = 120) -> pd.DataFrame:
    if _is_hk(symbol):
        return _tencent_kline(symbol, days)
    return _yf_kline(symbol, days)


def fetch_realtime(symbol: str) -> dict:
    if _is_hk(symbol):
        return _tencent_realtime(symbol)
    return _yf_realtime(symbol)
