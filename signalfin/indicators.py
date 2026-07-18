"""Technical indicators. Only RSI remains — 方向性指标(MACD/均线/KDJ/BOLL)
已随价值框架改造删除(择时信号 8 年回测全输买入持有,决策见 finefin)。"""

import numpy as np
import pandas as pd


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
