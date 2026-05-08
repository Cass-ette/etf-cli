# ETF CLI

A simple CLI tool for real-time A-share ETF quotes.

**Primary data source**: Eastmoney (东方财富)
**Fallback**: Tencent (腾讯)

## Install

```bash
cd etf
pip3 install -r requirements.txt
pip3 install -e .
```

Or use the install script:
```bash
./install.sh
```

## Usage

### Get quote for single ETF

```bash
# Default (auto-select best source)
etf get 562500

# Force specific source
etf get 562500 --source eastmoney
etf get 562500 --source tencent

# JSON output (for AI processing)
etf get 562500 --json

# AI-friendly markdown
etf get 562500 --ai
```

### Manage watchlist

```bash
# Add ETF to watchlist
etf add 562500
etf add 510300
etf add 159915

# Remove from watchlist
etf remove 562500

# Show watchlist (human readable)
etf list

# Show watchlist (AI markdown format)
etf watch
```

## Data Provider Notes

- **Eastmoney**: Full data including PE/PB, most stable
- **Tencent**: Simplified data (no PE/PB), fallback only

The tool automatically falls back to Tencent if Eastmoney fails.

## Example Output

### Human readable
```
机器人ETF华夏 (562500.SH)
最新价: 1.122
涨跌幅: +2.28%
涨跌额: +0.025
今开: 1.094 | 最高: 1.126 | 最低: 1.091
昨收: 1.097 | 振幅: 3.19%
成交: 14,041,248 手 | 156,357 万元
```

### JSON (--json)
```json
{
  "symbol": "562500",
  "name": "机器人ETF华夏",
  "market": "SH",
  "latest": 1.122,
  ...
}
```

### AI Context (--ai)
```markdown
## 机器人ETF华夏 (562500)
- **最新价**: 1.122
- **涨跌幅**: +2.28%
...
```
