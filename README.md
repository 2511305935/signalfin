# signalfin

Lightweight stock signal monitor for GitHub Actions.

## Secrets

Set these GitHub repository secrets:

```text
STOCK_LIST=600660.SS,0939.HK,BEKE
PUSHPLUS_TOKEN=your_pushplus_token
```

## Local test

```bash
pip install -r requirements.txt
python monitor.py --session test --once
```

## GitHub Actions

The workflow runs during Asia and US trading sessions, checking signals every 5 minutes and pushing only new signal changes to WeChat via PushPlus.
