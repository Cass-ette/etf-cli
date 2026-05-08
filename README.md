# ETF CLI

A simple CLI tool for real-time A-share ETF quotes and OTC fund context, designed for AI-assisted long-term trading analysis.

**ETF primary data source**: Eastmoney (东方财富)
**ETF fallback**: Tencent (腾讯)
**OTC fund source**: Tiantian Fund estimate API (天天基金估值接口)

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

### Get quote for single exchange-traded ETF

```bash
# Default: Eastmoney first, Tencent fallback
etf get 562500

# Force specific source
etf get 562500 --source eastmoney
etf get 562500 --source tencent

# JSON output for AI processing
etf get 562500 --json

# AI-friendly markdown
etf get 562500 --ai
```

### Get quote for OTC fund

```bash
# Human readable OTC fund NAV and estimate
etf fund 018344

# JSON output for AI processing
etf fund 018344 --json

# AI-friendly markdown
etf fund 018344 --ai
```

### Smart lookup

`smart` chooses the right output automatically:

1. Pair name first, e.g. `robot` → combined ETF + OTC fund AI context
2. Exchange-traded ETF-like code, e.g. `562500` → ETF AI context
3. Other six-digit code, e.g. `018344` → OTC fund AI context

```bash
etf smart robot
etf smart 562500
etf smart 018344
etf smart robot --json
etf smart robot --copy
```

### Manage ETF / OTC fund pairs

Use pairs when you watch the exchange-traded ETF for real-time market reference but actually buy or hold an OTC linked fund.

```bash
# Add a pair
etf pair add robot 562500 018344

# List pairs
etf pair list

# Human readable combined context
etf pair get robot

# JSON combined context for AI
etf pair get robot --json

# AI-friendly markdown combined context
etf pair get robot --ai

# Remove a pair
etf pair remove robot
```

### Manage ETF watchlist

```bash
# Add ETF to watchlist
etf add 562500
etf add 510300
etf add 159915

# Remove from watchlist
etf remove 562500

# Show watchlist, human readable
etf list

# Show watchlist, AI markdown format
etf watch
```

## Exchange-traded ETF vs OTC fund

| Type | Example | What the tool shows | Meaning |
| --- | --- | --- | --- |
| Exchange-traded ETF / 场内 ETF | `562500` | Real-time market price, open/high/low, volume, amount | Current exchange-traded price during market hours |
| OTC linked fund / 场外联接基金 | `018344` | Latest NAV, NAV date, estimated NAV, estimate time | Fund NAV/estimate; final transaction NAV is normally published after close |

Important notes:

- `etf get 562500` shows the exchange-traded ETF's real-time market price.
- `etf fund 018344` shows OTC fund NAV and estimated NAV. Estimated NAV is not the final transaction NAV.
- `etf pair get robot --ai` combines both so AI can understand: the ETF is the real-time reference, while the OTC fund is the actual trade/holding object.
- For OTC funds, orders before 15:00 usually settle at the current trading day's final NAV, not the intraday estimate.

## Data Provider Notes

- **Eastmoney**: ETF quote primary source; full data including PE/PB where available.
- **Tencent**: ETF fallback source; simplified data, no PE/PB.
- **Tiantian Fund**: OTC fund latest NAV and estimated NAV source.

The tool automatically falls back to Tencent if Eastmoney fails for ETF quotes.

## Example Output

### ETF human readable

```text
机器人ETF华夏 (562500.SH)
最新价: 1.122
涨跌幅: +2.28%
涨跌额: +0.025
今开: 1.094 | 最高: 1.126 | 最低: 1.091
昨收: 1.097 | 振幅: 3.19%
成交: 14,041,248 手 | 156,357 万元
```

### OTC fund human readable

```text
华夏中证机器人ETF发起式联接A (018344)
类型: 场外基金
最新单位净值: 1.3222
净值日期: 2026-05-07
估算净值: 1.3542
估算涨跌幅: +2.42%
估算时间: 2026-05-08 15:00
说明: 估算净值不是最终成交净值，最终净值通常在交易日晚上更新。
```

### Pair AI context

```markdown
# ETF / 场外基金配对行情上下文: robot

## 场内 ETF 参考
...

## 场外基金实际交易对象
...

## 重要说明
- 场内 ETF 是交易所实时价格。
- 场外基金以最终净值成交，估算净值仅供参考。
- 如果是 15:00 前申购/赎回，通常按当日最终净值结算。
```
