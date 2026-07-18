# signalfin 项目工作约定

## 项目定位(2026-07-18 重定义,决策源:finefin)

signalfin = **价格区间哨兵**:GitHub Actions 盘中每 5 分钟轮询持仓/候选价格,触发预设区间时经 Bark 推送 iPhone。它是价值投资框架的**执行提醒工具**,不是交易信号系统。

**上游关系**:finefin(尽调工作台)负责决策——买入分批区、减仓线、否决红线;signalfin 只负责"价格到了叫我"。单向数据流:finefin `scripts/export_watchlist.py` → GitHub Secrets → 本仓库。

## 铁律(价值框架,与 finefin 一致)

- **禁止方向性技术信号推送**:MACD金叉/死叉、均线多空排列、"动能转多/回调风险"等买卖暗示已随 finefin 决策引擎一并废弃(8年回测15组择时全输买入持有)
- **禁止价格止损逻辑**:已尽调持仓的下跌是加仓机会;卖出只由基本面否决+估值锚决定(那些是决策,在 finefin/尽调报告里,不在这里)
- **推送只有两类**:①区间触发(进入买入区/触及减仓线/跌破执行红线,附决策出处)②描述性提醒(RSI≤20/≥80 极端值、异常放量,纯陈述不带建议)

## 技术约束

- 运行环境:GitHub Actions(亚洲+美股时段),本地测试 `python monitor.py --session test --once`
- 数据源:yfinance;推送:Bark(BARK_URL secret)
- Secrets:STOCK_LIST(标的)、ACTIONS(执行提醒)→ 改造后加 ZONES(每股区间配置)
- 信号去重靠 state 跟踪(见 signals.py prev_state 机制),区间提醒沿用同一机制防重复推送
