# ETF CLI

A simple CLI tool for real-time A-share ETF quotes and OTC fund context, designed for AI-assisted long-term trading analysis.

**ETF primary data source**: Eastmoney (东方财富)
**ETF fallback**: Tencent (腾讯)
**OTC fund source**: Tiantian Fund estimate API (天天基金估值接口)
**Holdings-based proxy**: Eastmoney fund detail page (东方财富基金持仓)

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
etf get 562500
etf get 562500 --json
etf get 562500 --ai
```

### Get quote for OTC fund

```bash
etf fund 018344
etf fund 018344 --json
etf fund 018344 --ai
```

### Smart lookup

```bash
etf smart robot
etf smart 562500
etf smart 018344
etf smart robot --copy
```

### Manage ETF / OTC fund pairs

```bash
etf pair add robot 562500 018344
etf pair list
etf pair get robot
etf pair get robot --ai
etf pair remove robot
```

### Manage OTC fund watchlist

```bash
# Add fund with optional reference ETF
etf fundw add 020404 --ref 159540
etf fundw add 009447

# List watchlist
etf fundw list

# Batch intraday estimate for all funds
etf fundw watch
etf fundw watch --json

# Remove fund
etf fundw remove 020404
```

### One-click estimate

```bash
# Show all fund watchlist + all pairs in one view
etf est
```

### Manage ETF watchlist

```bash
etf add 562500
etf list
etf remove 562500
etf watch
```

## How it works

### Exchange-traded ETF vs OTC fund

| Type | Example | What the tool shows |
| --- | --- | --- |
| Exchange-traded ETF | `562500` | Real-time market price from Eastmoney |
| OTC linked fund | `018344` | NAV + estimated NAV from Tiantian Fund |
| Active/mixed fund | `009447` | NAV estimate + holdings-based proxy estimate |

### Holdings-based proxy estimation

For active/mixed funds where Tiantian Fund estimate is unavailable or unreliable:

1. Fetches top 10 holdings and their weights from Eastmoney fund detail page
2. Fetches intraday change for each holding stock
3. Calculates weighted average change as proxy estimate
4. Shows holdings coverage percentage as confidence indicator

Accuracy: directional reference only. Top holdings are from latest quarterly report and may be stale.

### Reference ETF binding

When you add a fund to the watchlist with `--ref`, the tool also shows the reference ETF's intraday change alongside the fund estimate. This helps when:

- The fund estimate is unavailable (e.g. `020404`)
- You want to cross-validate the estimate against the actual traded market

## Data Sources

- **Eastmoney**: ETF quotes (primary), fund holdings data
- **Tencent**: ETF quotes (fallback)
- **Tiantian Fund**: OTC fund NAV and estimated NAV
