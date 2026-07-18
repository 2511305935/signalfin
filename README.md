# signalfin

价格区间哨兵 for GitHub Actions:盘中每 5 分钟轮询价格,触发预设区间
(买入分批区/减仓线/既定执行线)或描述性极端值(RSI≤20/≥80、异常放量)时,
经 Bark 推送 iPhone。

决策在上游尽调工作台(finefin)完成,这里只负责"价格到了叫我"——
不做方向性技术信号,不做价格止损。

## Secrets

Set these GitHub repository secrets:

```text
STOCK_LIST=600660.SS,3606.HK,...        # 监控标的(yfinance 代码)
BARK_URL=https://api.day.app/YOUR_KEY   # Bark 推送
ZONES=<YAML>                            # 区间配置,格式见 zones.example.yaml
HOLDINGS=symbol:qty:cost:name|...       # 收盘复盘用(可选)
ACTIONS=symbol:action_text|...          # 次日操作指引(可选)
```

## Local test

```bash
pip install -r requirements.txt
cp zones.example.yaml zones.yaml   # 填入真实区间(zones.yaml 已 gitignore)
STOCK_LIST=... python monitor.py --session test --once
STOCK_LIST=... python monitor.py --review asia   # 收盘复盘
```

## GitHub Actions

The workflow runs during Asia and US trading sessions, checking zone triggers
every 5 minutes and pushing only state changes (dedup via prev_state) to
iPhone via Bark. Session-close reviews go out at 16:15 / 04:30 CST.
