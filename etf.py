#!/usr/bin/env python3
"""
etf - A simple CLI for A-share ETF real-time quotes
Primary: Eastmoney API (verified stable)
Fallback: Tencent API
"""

import json
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, asdict
from functools import wraps
import time

import click
import requests
import plotext as plt
import builtins

CONFIG_DIR = Path.home() / ".etf"
CONFIG_FILE = CONFIG_DIR / "watchlist.json"
FUND_PAIR_FILE = CONFIG_DIR / "pairs.json"
FUND_WATCH_FILE = CONFIG_DIR / "fund_watchlist.json"
HOLDINGS_FILE = CONFIG_DIR / "holdings.json"
SNAPSHOTS_FILE = CONFIG_DIR / "snapshots.jsonl"
CONTEXT_FILE = CONFIG_DIR / "context.md"

# API endpoints
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_BATCH_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TIANTIAN_FUND_URL = "https://fundgz.1234567.com.cn/js"
EASTMONEY_FUND_DETAIL_URL = "https://fund.eastmoney.com/pingzhongdata/{}.js"
EASTMONEY_STOCK_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# Data provider registry
DATA_PROVIDERS = {}


def display_width(text: str) -> int:
    """Return terminal display width, treating East Asian wide chars as width 2."""
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
    return width


def truncate_display(text: str, width: int) -> str:
    result = ""
    current = 0
    for ch in str(text):
        ch_width = 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
        if current + ch_width > width:
            break
        result += ch
        current += ch_width
    return result


def pad_display(text: str, width: int, align: str = "left") -> str:
    text = truncate_display(str(text), width)
    padding = max(width - display_width(text), 0)
    if align == "right":
        return " " * padding + text
    return text + " " * padding


def register_provider(name: str):
    """Decorator to register a data provider"""
    def decorator(func: Callable):
        DATA_PROVIDERS[name] = func
        return func
    return decorator


def with_fallback(primary: str, fallback: str, max_retries: int = 1):
    """
    Decorator to add fallback logic to a data fetch function.
    If primary provider fails, automatically try fallback.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            primary_func = DATA_PROVIDERS.get(primary)
            fallback_func = DATA_PROVIDERS.get(fallback)

            # Try primary
            for attempt in range(max_retries + 1):
                try:
                    result = primary_func(*args, **kwargs) if primary_func else None
                    if result:
                        return result
                except Exception:
                    if attempt < max_retries:
                        time.sleep(0.5)
                        continue

            # Try fallback
            if fallback_func:
                try:
                    return fallback_func(*args, **kwargs)
                except Exception:
                    pass

            return None
        return wrapper
    return decorator


@dataclass
class ETFQuote:
    symbol: str
    name: str
    market: str  # SH or SZ
    latest: float
    open: float
    high: float
    low: float
    prev_close: float
    change_amount: float
    change_pct: float
    volume: int  # 手 (100 shares)
    amount: int  # 元
    pe: Optional[float] = None
    pb: Optional[float] = None
    turnover: Optional[float] = None
    total_cap: Optional[float] = None
    float_cap: Optional[float] = None

    @property
    def is_up(self) -> bool:
        return self.change_amount >= 0

    @property
    def intraday_range(self) -> float:
        if self.prev_close == 0:
            return 0
        return (self.high - self.low) / self.prev_close * 100

    def to_dict(self) -> dict:
        return asdict(self)

    def to_ai_context(self) -> str:
        pe = f"{self.pe:.2f}" if self.pe is not None else "N/A"
        pb = f"{self.pb:.2f}" if self.pb is not None else "N/A"
        return f"""## {self.name} ({self.symbol})

- **类型**: 场内 ETF / Exchange-traded ETF
- **价格类型**: 交易所实时价格
- **最新价**: {self.latest:.3f}
- **涨跌幅**: {self.change_pct:+.2f}%
- **涨跌额**: {self.change_amount:+.3f}
- **今开**: {self.open:.3f}
- **最高**: {self.high:.3f}
- **最低**: {self.low:.3f}
- **昨收**: {self.prev_close:.3f}
- **振幅**: {self.intraday_range:.2f}%
- **成交量**: {self.volume:,} 手 ({self.volume * 100:,} 股)
- **成交额**: {self.amount:,.0f} 元
- **市盈率**: {pe}
- **市净率**: {pb}
"""


@dataclass
class OTCFundQuote:
    symbol: str
    name: str
    latest_nav: float
    latest_nav_date: str
    estimated_nav: Optional[float]
    estimated_change_pct: Optional[float]
    estimate_time: Optional[str]
    source: str = "tiantian"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_ai_context(self) -> str:
        estimated_nav = f"{self.estimated_nav:.4f}" if self.estimated_nav is not None else "N/A"
        estimated_change = f"{self.estimated_change_pct:+.2f}%" if self.estimated_change_pct is not None else "N/A"
        estimate_time = self.estimate_time or "N/A"
        return f"""## {self.name} ({self.symbol})

- **类型**: 场外基金 / OTC fund
- **价格类型**: 基金净值/估算净值
- **最新单位净值**: {self.latest_nav:.4f}
- **净值日期**: {self.latest_nav_date}
- **估算净值**: {estimated_nav}
- **估算涨跌幅**: {estimated_change}
- **估算时间**: {estimate_time}
- **说明**: 估算净值不是最终成交净值，最终净值通常在交易日晚上更新。
"""


def normalize_symbol(symbol: str) -> tuple[str, str, str]:
    """
    Normalize ETF symbol.
    Returns (secid, market_code, tencent_code)
    """
    symbol = symbol.strip().upper()

    if symbol.startswith(("SH", "SZ")):
        symbol = symbol[2:]

    if symbol.startswith(("51", "56", "58", "60", "68", "69")):
        return f"1.{symbol}", "SH", f"sh{symbol.lower()}"
    else:
        return f"0.{symbol}", "SZ", f"sz{symbol.lower()}"


# ============ Data Providers ============

@register_provider("eastmoney")
def fetch_eastmoney_quote(symbol: str) -> Optional[ETFQuote]:
    """Fetch quote from Eastmoney (primary source)"""
    secid, market, _ = normalize_symbol(symbol)

    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f116,f117,f162,f167,f168"
    }

    resp = requests.get(EASTMONEY_QUOTE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data")

    if not data:
        return None

    def price(field):
        val = data.get(field)
        return val / 1000 if val else 0.0

    def pct(field):
        val = data.get(field)
        return val / 100 if val else 0.0

    return ETFQuote(
        symbol=data.get("f57", symbol),
        name=data.get("f58", "Unknown"),
        market=market,
        latest=price("f43"),
        high=price("f44"),
        low=price("f45"),
        open=price("f46"),
        prev_close=price("f60"),
        change_amount=price("f169"),
        change_pct=pct("f170"),
        volume=data.get("f47", 0),
        amount=data.get("f48", 0),
        pe=data.get("f162"),
        pb=data.get("f167"),
        turnover=pct("f168") if data.get("f168") else None,
        total_cap=data.get("f116"),
        float_cap=data.get("f117")
    )


@register_provider("tencent")
def fetch_tencent_quote(symbol: str) -> Optional[ETFQuote]:
    """Fetch quote from Tencent (fallback source). Returns simplified quote."""
    _, market, tencent_code = normalize_symbol(symbol)

    url = f"{TENCENT_QUOTE_URL}{tencent_code}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    content = resp.text.strip()
    if not content.startswith("v_"):
        return None

    start = content.find('"') + 1
    end = content.rfind('"')
    if start <= 0 or end <= start:
        return None

    data_str = content[start:end]
    fields = data_str.split("~")

    if len(fields) < 35:
        return None

    try:
        name = fields[1]
        code = fields[2]
        latest = float(fields[3])
        prev_close = float(fields[4])
        open_price = float(fields[5])
        high = float(fields[33])
        low = float(fields[34])
        volume_shares = int(fields[36])
        amount = float(fields[37])
        change_pct = float(fields[32])

        volume_lots = volume_shares // 100
        change_amount = latest - prev_close

        return ETFQuote(
            symbol=code,
            name=name,
            market=market,
            latest=latest,
            high=high,
            low=low,
            open=open_price,
            prev_close=prev_close,
            change_amount=change_amount,
            change_pct=change_pct,
            volume=volume_lots,
            amount=int(amount),
            pe=None,
            pb=None,
            turnover=None,
            total_cap=None,
            float_cap=None
        )
    except (ValueError, IndexError):
        return None


# ============ Public API with Fallback ============

@with_fallback("eastmoney", "tencent")
def fetch_quote(symbol: str) -> Optional[ETFQuote]:
    """Fetch real-time quote. Tries Eastmoney first, falls back to Tencent."""
    pass


def fetch_fund_quote(symbol: str) -> Optional[OTCFundQuote]:
    """Fetch OTC fund NAV and estimated NAV from Tiantian Fund."""
    symbol = symbol.strip()
    url = f"{TIANTIAN_FUND_URL}/{symbol}.js"
    params = {"rt": int(time.time() * 1000)}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text.startswith("jsonpgz(") or not text.endswith(");"):
            return None

        data = json.loads(text[len("jsonpgz("):-2])
        return OTCFundQuote(
            symbol=data.get("fundcode", symbol),
            name=data.get("name", "Unknown"),
            latest_nav=float(data.get("dwjz") or 0),
            latest_nav_date=data.get("jzrq", ""),
            estimated_nav=float(data["gsz"]) if data.get("gsz") else None,
            estimated_change_pct=float(data["gszzl"]) if data.get("gszzl") else None,
            estimate_time=data.get("gztime") or None,
        )
    except Exception:
        return None


def load_fund_watchlist() -> list:
    if not FUND_WATCH_FILE.exists():
        return []
    return json.loads(FUND_WATCH_FILE.read_text())


def save_fund_watchlist(watchlist: list) -> None:
    FUND_WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    FUND_WATCH_FILE.write_text(json.dumps(watchlist, indent=2, ensure_ascii=False))


def fetch_fund_holdings(fund_code: str) -> Optional[dict]:
    """Fetch top holdings and stock ratio from Eastmoney fund detail page."""
    import re
    url = EASTMONEY_FUND_DETAIL_URL.format(fund_code)
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text

        name_m = re.search(r'var fS_name = "([^"]+)";', text)
        name = name_m.group(1) if name_m else "Unknown"

        asset_m = re.search(r'var Data_assetAllocation = ({.*?});', text, re.S)
        stock_ratio = None
        if asset_m:
            try:
                asset_data = json.loads(asset_m.group(1))
                series = asset_data.get("series", [])
                for s in series:
                    if s.get("name") == "股票占净比" and s.get("data"):
                        stock_ratio = s["data"][-1]
            except Exception:
                pass

        stock_m = re.search(r'var stockCodesNew = (\[.*?\]);', text, re.S)
        holdings = []
        if stock_m:
            try:
                raw = json.loads(stock_m.group(1))
                for item in raw[:10]:
                    if isinstance(item, str) and "," in item:
                        parts = item.split(",")
                        if len(parts) >= 3:
                            holdings.append({
                                "code": parts[0],
                                "name": parts[1],
                                "weight": float(parts[2]) if parts[2] else None,
                            })
            except Exception:
                pass

        return {
            "name": name,
            "stock_ratio": stock_ratio,
            "holdings": holdings,
        }
    except Exception:
        return None


def fetch_stock_quote_pct(code: str) -> Optional[float]:
    """Fetch a single stock's intraday change pct from Eastmoney."""
    code = code.strip()
    if code.startswith(("6", "9")):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"
    try:
        resp = requests.get(EASTMONEY_STOCK_QUOTE_URL, params={
            "secid": secid,
            "fields": "f170",
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data")
        if data and data.get("f170") is not None:
            return data["f170"] / 100
    except Exception:
        pass
    return None


def estimate_fund_by_holdings(fund_code: str) -> Optional[dict]:
    """Estimate fund's intraday change using top holdings weighted change."""
    info = fetch_fund_holdings(fund_code)
    if not info or not info["holdings"]:
        return None

    weighted_sum = 0.0
    total_weight = 0.0
    holding_details = []

    for h in info["holdings"][:10]:
        weight = h.get("weight")
        if weight is None or weight <= 0:
            continue
        pct = fetch_stock_quote_pct(h["code"])
        if pct is not None:
            weighted_sum += weight * pct
            total_weight += weight
            holding_details.append({
                "code": h["code"],
                "name": h["name"],
                "weight": weight,
                "change_pct": round(pct, 2),
            })

    if total_weight == 0:
        return None

    estimated_pct = weighted_sum / total_weight

    return {
        "fund_code": fund_code,
        "fund_name": info["name"],
        "estimated_change_pct": round(estimated_pct, 2),
        "holdings_coverage": round(total_weight, 1),
        "stock_ratio": info.get("stock_ratio"),
        "holdings": holding_details,
    }


def load_holdings() -> list:
    if not HOLDINGS_FILE.exists():
        return []
    return json.loads(HOLDINGS_FILE.read_text())


def save_holdings(holdings: list) -> None:
    HOLDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLDINGS_FILE.write_text(json.dumps(holdings, indent=2, ensure_ascii=False))


def resolve_holding_estimate(code: str) -> Optional[dict]:
    """Resolve best available intraday estimate for a holding."""
    fund_watch = {item["code"]: item for item in load_fund_watchlist()}
    item = fund_watch.get(code, {"code": code, "name": code})

    if code.lower() in {"cash", "repo", "reverse_repo", "逆回购", "现金"}:
        return {
            "code": code,
            "name": "现金/国债逆回购",
            "change_pct": 0.0,
            "source": "cash",
        }

    # Exchange-traded ETF: use real-time quote directly
    if is_exchange_traded_etf_code(code):
        etf_q = fetch_quote(code)
        if etf_q:
            return {
                "code": code,
                "name": etf_q.name,
                "change_pct": etf_q.change_pct,
                "source": "etf",
            }

    # OTC fund: try official estimate first
    fund_q = fetch_fund_quote(code)
    if fund_q and fund_q.estimated_change_pct is not None:
        return {
            "code": code,
            "name": fund_q.name,
            "change_pct": fund_q.estimated_change_pct,
            "source": "official",
        }

    ref_etf = item.get("ref_etf")
    if ref_etf:
        ref_q = fetch_quote(ref_etf)
        if ref_q:
            return {
                "code": code,
                "name": fund_q.name if fund_q else item.get("name", code),
                "change_pct": ref_q.change_pct,
                "source": f"ref:{ref_etf}",
            }

    proxy = estimate_fund_by_holdings(code)
    if proxy:
        return {
            "code": code,
            "name": proxy["fund_name"],
            "change_pct": proxy["estimated_change_pct"],
            "source": f"holdings:{proxy['holdings_coverage']:.0f}%",
        }

    return None


def build_portfolio_pnl() -> Optional[dict]:
    holdings = load_holdings()
    if not holdings:
        return None

    items = []
    total_amount = 0.0
    risk_amount = 0.0
    cash_amount = 0.0
    total_gain = 0.0
    for h in holdings:
        amount = float(h["amount"])
        estimate = resolve_holding_estimate(h["code"])
        if estimate:
            pct = estimate["change_pct"]
            gain = amount * pct / 100
            is_cash = estimate["source"] == "cash"
            total_gain += gain
            if is_cash:
                cash_amount += amount
            else:
                risk_amount += amount
            items.append({
                "code": h["code"],
                "name": estimate["name"],
                "amount": amount,
                "change_pct": pct,
                "gain": gain,
                "source": estimate["source"],
                "is_cash": is_cash,
            })
        else:
            risk_amount += amount
            items.append({
                "code": h["code"],
                "name": h["code"],
                "amount": amount,
                "change_pct": None,
                "gain": None,
                "source": "missing",
                "is_cash": False,
            })
        total_amount += amount

    total_pct = total_gain / total_amount * 100 if total_amount else 0.0
    risk_pct = total_gain / risk_amount * 100 if risk_amount else 0.0
    return {
        "total_amount": total_amount,
        "risk_amount": risk_amount,
        "cash_amount": cash_amount,
        "total_gain": total_gain,
        "total_pct": total_pct,
        "risk_pct": risk_pct,
        "items": items,
    }


def load_pairs() -> dict:
    """Load ETF/fund pairs from config."""
    if not FUND_PAIR_FILE.exists():
        return {}
    return json.loads(FUND_PAIR_FILE.read_text())


def is_exchange_traded_etf_code(key: str) -> bool:
    """Return true when a key looks like an exchange-traded ETF code."""
    code = key.strip().upper()
    if code.startswith(("SH", "SZ")):
        code = code[2:]
    return len(code) == 6 and code.isdigit() and code.startswith(("15", "16", "18", "50", "51", "56", "58"))


def save_pairs(pairs: dict) -> None:
    """Save ETF/fund pairs to config."""
    FUND_PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    FUND_PAIR_FILE.write_text(json.dumps(pairs, indent=2, ensure_ascii=False))


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using a platform clipboard command."""
    commands = [
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
    ]

    for command in commands:
        if shutil.which(command[0]):
            subprocess.run(command, input=text, text=True, check=True)
            return True

    if shutil.which("clip"):
        subprocess.run("clip", input=text, text=True, check=True, shell=True)
        return True

    return False


def fetch_batch_quotes(symbols: list[str]) -> list[ETFQuote]:
    """Fetch quotes for multiple ETFs. Falls back to individual fetches if batch fails."""
    try:
        secids = []
        for symbol in symbols:
            secid, _, _ = normalize_symbol(symbol)
            secids.append(secid)

        params = {
            "secids": ",".join(secids),
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f116,f117,f162,f167,f168"
        }

        resp = requests.get(EASTMONEY_BATCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data_list = resp.json().get("data", {}).get("diff", [])

        quotes = []
        for data in data_list:
            def price(field):
                val = data.get(field)
                return val / 1000 if val else 0.0

            def pct(field):
                val = data.get(field)
                return val / 100 if val else 0.0

            code = data.get("f57", "")
            market = "SH" if code.startswith(("51", "56", "58", "60")) else "SZ"

            quotes.append(ETFQuote(
                symbol=code,
                name=data.get("f58", "Unknown"),
                market=market,
                latest=price("f43"),
                high=price("f44"),
                low=price("f45"),
                open=price("f46"),
                prev_close=price("f60"),
                change_amount=price("f169"),
                change_pct=pct("f170"),
                volume=data.get("f47", 0),
                amount=data.get("f48", 0),
                pe=data.get("f162"),
                pb=data.get("f167"),
                turnover=pct("f168") if data.get("f168") else None,
                total_cap=data.get("f116"),
                float_cap=data.get("f117")
            ))

        return quotes

    except Exception:
        quotes = []
        for symbol in symbols:
            quote = fetch_quote(symbol)
            if quote:
                quotes.append(quote)
        return quotes


# CLI Commands

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """ETF - Real-time A-share ETF quotes for AI analysis"""
    pass


@cli.command()
@click.argument("symbol")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
@click.option("--ai", "output_ai", is_flag=True, help="Output AI-friendly markdown context")
@click.option("--source", help="Force data source (eastmoney/tencent)")
def get(symbol: str, output_json: bool, output_ai: bool, source: Optional[str]):
    """Get real-time quote for a single ETF"""

    if source:
        provider = DATA_PROVIDERS.get(source)
        if not provider:
            click.echo(f"Unknown source: {source}", err=True)
            sys.exit(1)
        quote = provider(symbol)
    else:
        quote = fetch_quote(symbol)

    if not quote:
        click.echo(f"Failed to fetch quote for {symbol}", err=True)
        sys.exit(1)

    if output_json:
        click.echo(json.dumps(quote.to_dict(), indent=2, ensure_ascii=False))
    elif output_ai:
        click.echo(quote.to_ai_context())
    else:
        color = "green" if quote.is_up else "red"
        sign = "+" if quote.is_up else ""

        click.echo(f"\n{click.style(quote.name, bold=True)} ({quote.symbol}.{quote.market})")
        click.echo(f"最新价: {click.style(f'{quote.latest:.3f}', fg=color, bold=True)}")
        click.echo(f"涨跌幅: {click.style(f'{sign}{quote.change_pct:.2f}%', fg=color)}")
        click.echo(f"涨跌额: {sign}{quote.change_amount:.3f}")
        click.echo(f"今开: {quote.open:.3f} | 最高: {quote.high:.3f} | 最低: {quote.low:.3f}")
        click.echo(f"昨收: {quote.prev_close:.3f} | 振幅: {quote.intraday_range:.2f}%")
        click.echo(f"成交: {quote.volume:,} 手 | {quote.amount/10000:,.0f} 万元")


@cli.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("--days", "days", default=5, help="Number of trading days to show (default 5)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
def hist(symbols, days: int, output_json: bool):
    """Fetch historical daily data for one or more ETF codes.

    Example:
      etf hist 159887 159842 159928
      etf hist 159887 --days 10
    """
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    results = {}
    # ETF 在深交所，secid 前缀 0；港股前缀 116；美股前缀 105
    for symbol in symbols:
        secid = f"0.{symbol}"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",  # daily
            "fqt": "1",
            "beg": "19900101",
            "end": "20991231",
        }
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Referer": "https://quote.eastmoney.com/",
            }
            data = None
            for attempt in range(3):
                try:
                    r = requests.get(url, params=params, timeout=10, headers=headers)
                    data = r.json()
                    break
                except Exception:
                    time.sleep(0.5 * (attempt + 1))
            if data is None:
                results[symbol] = {"error": "request failed after retries"}
                continue
            klines = (data.get("data") or {}).get("klines", [])
            rows = []
            for k in klines:
                parts = k.split(",")
                # date, open, close, high, low, volume, amount, amplitude, pct, change, turnover
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "pct": float(parts[8]) if len(parts) > 8 and parts[8] else None,
                })
            results[symbol] = rows[-days:] if days > 0 else rows
        except Exception as e:
            results[symbol] = {"error": str(e)}

    if output_json:
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return

    # Markdown 表格输出
    click.echo(f"\n最近 {days} 个交易日历史数据\n")
    for symbol, rows in results.items():
        if isinstance(rows, dict) and "error" in rows:
            click.echo(f"❌ {symbol}: {rows['error']}")
            continue
        click.echo(f"### {symbol}")
        click.echo("日期         收盘价     涨跌幅")
        for r in rows:
            pct_str = f"{r['pct']:+.2f}%" if r['pct'] is not None else "N/A"
            click.echo(f"{r['date']}   {r['close']:<10.4f} {pct_str}")
        click.echo("")


@cli.command()
@click.argument("symbol")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
@click.option("--ai", "output_ai", is_flag=True, help="Output AI-friendly markdown context")
def fund(symbol: str, output_json: bool, output_ai: bool):
    """Get NAV and estimate for an OTC fund"""
    quote = fetch_fund_quote(symbol)

    if not quote:
        click.echo(f"Failed to fetch fund quote for {symbol}", err=True)
        sys.exit(1)

    if output_json:
        click.echo(json.dumps(quote.to_dict(), indent=2, ensure_ascii=False))
    elif output_ai:
        click.echo(quote.to_ai_context())
    else:
        color = "green" if (quote.estimated_change_pct or 0) >= 0 else "red"
        sign = "+" if (quote.estimated_change_pct or 0) >= 0 else ""
        estimated_nav = f"{quote.estimated_nav:.4f}" if quote.estimated_nav is not None else "N/A"
        estimated_change = f"{sign}{quote.estimated_change_pct:.2f}%" if quote.estimated_change_pct is not None else "N/A"

        click.echo(f"\n{click.style(quote.name, bold=True)} ({quote.symbol})")
        click.echo("类型: 场外基金")
        click.echo(f"最新单位净值: {quote.latest_nav:.4f}")
        click.echo(f"净值日期: {quote.latest_nav_date}")
        click.echo(f"估算净值: {estimated_nav}")
        click.echo(f"估算涨跌幅: {click.style(estimated_change, fg=color)}")
        click.echo(f"估算时间: {quote.estimate_time or 'N/A'}")
        click.echo("说明: 估算净值不是最终成交净值，最终净值通常在交易日晚上更新。")


@cli.command()
def list():
    """Show your ETF watchlist"""
    if not CONFIG_FILE.exists():
        click.echo("Watchlist is empty. Use 'etf add <symbol>' to add ETFs.")
        return

    watchlist = json.loads(CONFIG_FILE.read_text())
    if not watchlist:
        click.echo("Watchlist is empty.")
        return

    symbols = [item["symbol"] for item in watchlist]
    quotes = fetch_batch_quotes(symbols)

    if not quotes:
        click.echo("Failed to fetch quotes", err=True)
        return

    click.echo(f"\n{'ETF':<12} {'名称':<12} {'最新价':>8} {'涨跌%':>8} {'振幅%':>8}")
    click.echo("-" * 55)

    for quote in quotes:
        color = "green" if quote.is_up else "red"
        sign = "+" if quote.is_up else ""
        line = f"{quote.symbol:<12} {quote.name:<12} {quote.latest:>8.3f} {sign}{quote.change_pct:>7.2f} {quote.intraday_range:>8.2f}"
        click.echo(click.style(line, fg=color))


@cli.command()
@click.argument("symbol")
@click.option("--name", help="Custom name for this ETF (optional)")
def add(symbol: str, name: Optional[str]):
    """Add an ETF to your watchlist"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    watchlist = []
    if CONFIG_FILE.exists():
        watchlist = json.loads(CONFIG_FILE.read_text())

    if any(item["symbol"] == symbol.upper() for item in watchlist):
        click.echo(f"{symbol} is already in watchlist")
        return

    quote = fetch_quote(symbol)
    if not quote:
        click.echo(f"Cannot verify {symbol}, but adding anyway", err=True)
        display_name = name or symbol.upper()
    else:
        display_name = name or quote.name
        click.echo(f"Added: {display_name} ({symbol.upper()})")

    watchlist.append({"symbol": symbol.upper(), "name": display_name})
    CONFIG_FILE.write_text(json.dumps(watchlist, indent=2))


@cli.command()
@click.argument("symbol")
def remove(symbol: str):
    """Remove an ETF from your watchlist"""
    if not CONFIG_FILE.exists():
        click.echo("Watchlist is empty")
        return

    watchlist = json.loads(CONFIG_FILE.read_text())
    original_len = len(watchlist)
    watchlist = [item for item in watchlist if item["symbol"] != symbol.upper()]

    if len(watchlist) == original_len:
        click.echo(f"{symbol} not found in watchlist")
        return

    CONFIG_FILE.write_text(json.dumps(watchlist, indent=2))
    click.echo(f"Removed {symbol.upper()}")


def build_pair_context(name: str, output_json: bool = False) -> Optional[str]:
    """Build combined ETF/fund pair context string."""
    pairs = load_pairs()
    if name not in pairs:
        click.echo(f"Pair {name} not found", err=True)
        return None

    item = pairs[name]
    etf_quote = fetch_quote(item["etf"])
    fund_quote = fetch_fund_quote(item["fund"])

    if not etf_quote or not fund_quote:
        click.echo(f"Failed to fetch pair {name}", err=True)
        return None

    notes = [
        "exchange_traded_etf is real-time market price",
        "otc_fund estimated_nav is not final transaction NAV",
        "OTC fund orders before 15:00 usually settle at current trading day's final NAV",
    ]

    if output_json:
        data = {
            "type": "etf_otc_fund_pair",
            "name": name,
            "exchange_traded_etf": etf_quote.to_dict(),
            "otc_fund": fund_quote.to_dict(),
            "notes": notes,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    return "\n".join([
        f"# ETF / 场外基金配对行情上下文: {name}",
        "",
        "## 场内 ETF 参考",
        "",
        etf_quote.to_ai_context(),
        "",
        "## 场外基金实际交易对象",
        "",
        fund_quote.to_ai_context(),
        "",
        "## 重要说明",
        "- 场内 ETF 是交易所实时价格。",
        "- 场外基金以最终净值成交，估算净值仅供参考。",
        "- 如果是 15:00 前申购/赎回，通常按当日最终净值结算。",
    ])


@cli.command()
@click.argument("key")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
@click.option("--copy", "copy_output", is_flag=True, help="Copy output to clipboard")
def smart(key: str, output_json: bool, copy_output: bool):
    """Smart lookup: pair name, ETF code, or OTC fund code"""
    pairs = load_pairs()
    if key in pairs:
        text = build_pair_context(key, output_json=output_json)
        if text is None:
            sys.exit(1)
        if copy_output and not copy_to_clipboard(text):
            click.echo("No clipboard command available", err=True)
            sys.exit(1)
        click.echo(text)
        return

    if is_exchange_traded_etf_code(key):
        quote = fetch_quote(key)
        if not quote:
            click.echo(f"Failed to fetch ETF quote for {key}", err=True)
            sys.exit(1)
        text = json.dumps(quote.to_dict(), indent=2, ensure_ascii=False) if output_json else quote.to_ai_context()
        if copy_output and not copy_to_clipboard(text):
            click.echo("No clipboard command available", err=True)
            sys.exit(1)
        click.echo(text)
        return

    quote = fetch_fund_quote(key)
    if not quote:
        click.echo(f"Cannot smart-resolve {key}. Try 'etf get {key}', 'etf fund {key}', or 'etf pair get {key}'.", err=True)
        sys.exit(1)

    text = json.dumps(quote.to_dict(), indent=2, ensure_ascii=False) if output_json else quote.to_ai_context()
    if copy_output and not copy_to_clipboard(text):
        click.echo("No clipboard command available", err=True)
        sys.exit(1)
    click.echo(text)


@cli.group()
def pair():
    """Manage ETF and OTC fund pairs"""
    pass


@pair.command("add")
@click.argument("name")
@click.argument("etf_symbol")
@click.argument("fund_symbol")
def pair_add(name: str, etf_symbol: str, fund_symbol: str):
    """Add an ETF/OTC fund pair"""
    pairs = load_pairs()
    pairs[name] = {"name": name, "etf": etf_symbol.upper(), "fund": fund_symbol}
    save_pairs(pairs)
    click.echo(f"Added pair {name}: ETF {etf_symbol.upper()} + fund {fund_symbol}")


@pair.command("remove")
@click.argument("name")
def pair_remove(name: str):
    """Remove an ETF/OTC fund pair"""
    pairs = load_pairs()
    if name not in pairs:
        click.echo(f"Pair {name} not found", err=True)
        sys.exit(1)
    del pairs[name]
    save_pairs(pairs)
    click.echo(f"Removed pair {name}")


@pair.command("list")
def pair_list():
    """List ETF/OTC fund pairs"""
    pairs = load_pairs()
    if not pairs:
        click.echo("No pairs configured. Use 'etf pair add <name> <etf> <fund>'.")
        return

    click.echo(f"\n{'名称':<12} {'场内ETF':<12} {'场外基金':<12}")
    click.echo("-" * 40)
    for name, item in pairs.items():
        click.echo(f"{name:<12} {item['etf']:<12} {item['fund']:<12}")


@pair.command("get")
@click.argument("name")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
@click.option("--ai", "output_ai", is_flag=True, help="Output AI-friendly markdown context")
def pair_get(name: str, output_json: bool, output_ai: bool):
    """Get combined ETF and OTC fund context"""
    if output_json or output_ai:
        text = build_pair_context(name, output_json=output_json)
        if text is None:
            sys.exit(1)
        click.echo(text)
        return

    pairs = load_pairs()
    if name not in pairs:
        click.echo(f"Pair {name} not found", err=True)
        sys.exit(1)

    item = pairs[name]
    etf_quote = fetch_quote(item["etf"])
    fund_quote = fetch_fund_quote(item["fund"])

    if not etf_quote or not fund_quote:
        click.echo(f"Failed to fetch pair {name}", err=True)
        sys.exit(1)

    click.echo(f"\n{name}")
    click.echo(f"场内ETF: {etf_quote.name} ({etf_quote.symbol}) {etf_quote.latest:.3f} {etf_quote.change_pct:+.2f}%")
    estimated_nav = f"{fund_quote.estimated_nav:.4f}" if fund_quote.estimated_nav is not None else "N/A"
    estimated_change = f"{fund_quote.estimated_change_pct:+.2f}%" if fund_quote.estimated_change_pct is not None else "N/A"
    click.echo(f"场外基金: {fund_quote.name} ({fund_quote.symbol}) 估算净值 {estimated_nav} {estimated_change}")
    click.echo(f"估算时间: {fund_quote.estimate_time or 'N/A'}")


@cli.command()
def watch():
    """Show watchlist with AI-friendly markdown output"""
    if not CONFIG_FILE.exists():
        click.echo("Watchlist is empty")
        return

    watchlist = json.loads(CONFIG_FILE.read_text())
    if not watchlist:
        click.echo("Watchlist is empty")
        return

    symbols = [item["symbol"] for item in watchlist]
    quotes = fetch_batch_quotes(symbols)

    click.echo("\n# ETF 自选列表行情快照\n")
    click.echo(f"更新时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for quote in quotes:
        click.echo(quote.to_ai_context())
        click.echo()


if __name__ == "__main__":
    cli()


# ============ Portfolio PnL Commands ============

@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output JSON")
def pnl(output_json: bool):
    """Estimate today's portfolio PnL from configured holdings."""
    data = build_portfolio_pnl()
    if data is None:
        click.echo("No holdings configured. Use 'etf holding set <code> <amount>'.")
        return

    if output_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    color = "green" if data["total_gain"] >= 0 else "red"
    sign = "+" if data["total_gain"] >= 0 else ""
    pct_sign = "+" if data["total_pct"] >= 0 else ""
    risk_pct_sign = "+" if data["risk_pct"] >= 0 else ""
    click.echo("\n组合实时估算\n")
    click.echo(f"总资产: {data['total_amount']:,.2f}")
    click.echo(f"风险资产: {data['risk_amount']:,.2f}")
    click.echo(f"现金/逆回购: {data['cash_amount']:,.2f}")
    click.echo(f"今日估算盈亏: {click.style(f'{sign}{data['total_gain']:,.2f}', fg=color)}")
    click.echo(f"总资产涨跌幅: {click.style(f'{pct_sign}{data['total_pct']:.2f}%', fg=color)}")
    click.echo(f"风险资产涨跌幅: {click.style(f'{risk_pct_sign}{data['risk_pct']:.2f}%', fg=color)}")
    header = " ".join([
        pad_display("代码", 8),
        pad_display("名称", 36),
        pad_display("金额", 12, align="right"),
        pad_display("涨跌", 8, align="right"),
        pad_display("盈亏", 10, align="right"),
        pad_display("来源", 12, align="right"),
    ])
    click.echo(f"\n{header}")
    click.echo("-" * display_width(header))
    for item in data["items"]:
        if item["change_pct"] is None:
            pct = "N/A"
            gain = "N/A"
            item_color = None
        else:
            item_color = "green" if item["gain"] >= 0 else "red"
            pct = f"{item['change_pct']:+.2f}%"
            gain = f"{item['gain']:+,.2f}"
        line = " ".join([
            pad_display(item["code"], 8),
            pad_display(item["name"], 36),
            pad_display(f"{item['amount']:,.2f}", 12, align="right"),
            pad_display(pct, 8, align="right"),
            pad_display(gain, 10, align="right"),
            pad_display(item["source"], 12, align="right"),
        ])
        click.echo(click.style(line, fg=item_color) if item_color else line)


# ============ Holdings Commands ============

@cli.group()
def holding():
    """Manage holding amounts."""
    pass


@holding.command("set")
@click.argument("code")
@click.argument("amount", type=float)
def holding_set(code: str, amount: float):
    holdings = load_holdings()
    holdings = [h for h in holdings if h["code"] != code]
    holdings.append({"code": code, "amount": amount})
    save_holdings(holdings)
    click.echo(f"Set holding {code}: {amount:.2f}")


@holding.command("list")
def holding_list():
    holdings = load_holdings()
    if not holdings:
        click.echo("No holdings configured. Use 'etf holding set <code> <amount>'.")
        return
    click.echo(f"\n{'代码':<10} {'金额':>12}")
    click.echo("-" * 25)
    for h in holdings:
        click.echo(f"{h['code']:<10} {h['amount']:>12.2f}")


@holding.command("remove")
@click.argument("code")
def holding_remove(code: str):
    holdings = load_holdings()
    holdings = [h for h in holdings if h["code"] != code]
    save_holdings(holdings)
    click.echo(f"Removed holding {code}")


@holding.command("adjust", context_settings={"ignore_unknown_options": True})
@click.argument("code")
@click.argument("delta", type=click.UNPROCESSED)
def holding_adjust(code: str, delta: str):
    """Adjust holding amount by delta after buy/sell."""
    delta_amount = float(delta)
    holdings = load_holdings()
    found = False
    for h in holdings:
        if h["code"] == code:
            h["amount"] = float(h["amount"]) + delta_amount
            found = True
            new_amount = h["amount"]
            break
    if not found:
        new_amount = delta_amount
        holdings.append({"code": code, "amount": new_amount})
    save_holdings(holdings)
    click.echo(f"Adjusted holding {code}: {delta_amount:+.2f} -> {new_amount:.2f}")


# ============ Fund Watchlist Commands ============

@cli.command()
def snapshot():
    """Save current portfolio PnL snapshot to local history."""
    import datetime
    data = build_portfolio_pnl()
    if data is None:
        click.echo("No holdings configured. Use 'etf holding set <code> <amount>'.")
        return
    record = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_amount": data["total_amount"],
        "risk_amount": data["risk_amount"],
        "cash_amount": data["cash_amount"],
        "total_gain": data["total_gain"],
        "total_pct": data["total_pct"],
        "risk_pct": data["risk_pct"],
    }
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOTS_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    click.echo(f"Snapshot saved: {record['timestamp']} total={data['total_amount']:,.2f} gain={data['total_gain']:+,.2f}")


def _render_bar_chart(values, width=50, height=10):
    """Render a terminal bar/area chart from numeric values using block characters."""
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v if max_v != min_v else 1.0
    rows = []
    for row in range(height - 1, -1, -1):
        threshold = min_v + span * row / (height - 1)
        line_chars = []
        for v in values:
            if v >= threshold:
                line_chars.append("█")
            else:
                line_chars.append(" ")
        rows.append("".join(line_chars))
    return rows


def _render_line_chart(values, width=50, height=10):
    """Render a terminal line chart."""
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v if max_v != min_v else 1.0
    if len(values) == 1:
        columns = [0]
        width = 1
    else:
        width = max(width, len(values))
        columns = [round(i * (width - 1) / (len(values) - 1)) for i in range(len(values))]
    rows = [round((max_v - v) / span * (height - 1)) for v in values]

    grid = [[" " for _ in range(width)] for _ in range(height)]
    for i, (x, y) in enumerate(zip(columns, rows)):
        grid[y][x] = "•"
        if i == 0:
            continue
        prev_x = columns[i - 1]
        prev_y = rows[i - 1]
        dx = x - prev_x
        if dx <= 0:
            continue
        for step in range(1, dx):
            t = step / dx
            yy = round(prev_y + (y - prev_y) * t)
            if yy == prev_y == y:
                ch = "─"
            elif y < prev_y:
                ch = "╱"
            else:
                ch = "╲"
            grid[yy][prev_x + step] = ch
    return ["".join(row) for row in grid]


def _last_snapshot_per_day(snapshots):
    daily = {}
    for snapshot in snapshots:
        daily[snapshot["timestamp"][:10]] = snapshot
    return [*daily.values()]


def _load_snapshots():
    if not SNAPSHOTS_FILE.exists():
        return []
    lines = SNAPSHOTS_FILE.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@cli.command()
def brief():
    """Print portfolio context for continuing in a new Claude window."""
    data = build_portfolio_pnl()
    if data is None:
        click.echo("No holdings configured. Use 'etf holding set <code> <amount>'.")
        return

    exchange_gain = sum(item["gain"] or 0 for item in data["items"] if item["source"] == "etf")
    otc_gain = sum(item["gain"] or 0 for item in data["items"] if item["source"] != "etf" and not item["is_cash"])
    snapshots = _last_snapshot_per_day(_load_snapshots())[-5:]

    click.echo("ETF 投资上下文简报")
    click.echo("")
    click.echo(f"总资产: {data['total_amount']:,.2f}")
    click.echo(f"风险资产: {data['risk_amount']:,.2f}")
    click.echo(f"现金/低风险: {data['cash_amount']:,.2f}")
    click.echo(f"今日估算盈亏: {data['total_gain']:+,.2f}")
    click.echo(f"场内估算盈亏: {exchange_gain:+,.2f}")
    click.echo(f"场外估算盈亏: {otc_gain:+,.2f}")

    if snapshots:
        click.echo("")
        click.echo("最近每日快照:")
        for snapshot in snapshots:
            click.echo(f"{snapshot['timestamp'][:10]}  {snapshot['total_amount']:,.2f}")

    click.echo("")
    click.echo("关键口径:")
    click.echo("- 场外 = 支付宝。")
    click.echo("- 晚上支付宝实际收益比盘中估算更准。")
    click.echo("- etf curve 只看每日最后一条 snapshot，不看盘中。")
    click.echo("- 新窗口先跑 etf brief、etf pnl、etf curve 恢复状态。")

    click.echo("")
    click.echo("新窗口接续提示:")
    click.echo("请读取 ~/.etf/context.md，然后运行 etf brief、etf pnl、etf curve，继续帮我整理 ETF/支付宝投资账本。")


@cli.command()
@click.option("--last", "last_n", default=30, help="Number of recent days to show")
@click.option("--bar", "bar_chart", is_flag=True, help="Show bar/area chart instead of line chart")
def curve(last_n: int, bar_chart: bool):
    """Draw terminal portfolio equity curve from saved snapshots."""
    if not SNAPSHOTS_FILE.exists():
        click.echo("No snapshots yet. Use 'etf snapshot' first.")
        return
    snapshots = _load_snapshots()
    if not snapshots:
        click.echo("No snapshots found.")
        return
    snapshots = _last_snapshot_per_day(snapshots)[-last_n:]
    values = [s["total_amount"] for s in snapshots]
    start = snapshots[0]
    end = snapshots[-1]
    total_return = (end["total_amount"] - start["total_amount"]) / start["total_amount"] * 100

    # Build x labels: short dates
    x_labels = [s["timestamp"][5:10] for s in snapshots]
    x_vals = builtins.list(range(len(values)))

    # Determine line color based on total return
    line_color = "green" if total_return >= 0 else "red"

    plt.clear_figure()
    plt.title("资产曲线")
    plt.xlabel("日期")
    plt.ylabel("总资产")
    plt.plot(x_vals, values, color=line_color)
    if bar_chart:
        plt.bar(x_vals, values, color=line_color)
    # Show date labels on x axis: first, middle, last
    n = len(x_labels)
    if n <= 10:
        plt.xticks(x_vals, x_labels)
    else:
        step = max(n // 5, 1)
        tick_positions = builtins.list(range(0, n, step))
        if n - 1 not in tick_positions:
            tick_positions.append(n - 1)
        tick_labels = [x_labels[i] for i in tick_positions]
        plt.xticks(tick_positions, tick_labels)
    plt.yticks([min(values), (min(values) + max(values)) / 2, max(values)])
    plt.show()

    click.echo(f"\n起始: {start['total_amount']:,.0f} ({start['timestamp'][:10]})")
    click.echo(f"当前: {end['total_amount']:,.0f} ({end['timestamp'][:10]})")
    gain = end["total_amount"] - start["total_amount"]
    sign = "+" if gain >= 0 else ""
    color = "green" if gain >= 0 else "red"
    click.echo(f"收益: {click.style(f'{sign}{gain:,.0f} / {sign}{total_return:.2f}%', fg=color)}")

    # Max drawdown
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
    click.echo(f"最大回撤: {max_dd:.2f}%")


@cli.group()
def fundw():
    """Manage OTC fund watchlist and estimates."""
    pass


@fundw.command("add")
@click.argument("code")
@click.option("--ref", "ref_etf", help="Reference exchange-traded ETF code")
def fundw_add(code: str, ref_etf: Optional[str]):
    """Add an OTC fund to watchlist, optionally bind to a reference ETF."""
    watchlist = load_fund_watchlist()
    if any(item["code"] == code for item in watchlist):
        click.echo(f"{code} already in fund watchlist")
        return
    fund_q = fetch_fund_quote(code)
    name = fund_q.name if fund_q else code
    entry = {"code": code, "name": name}
    if ref_etf:
        entry["ref_etf"] = ref_etf.upper()
    watchlist.append(entry)
    save_fund_watchlist(watchlist)
    ref_msg = f" -> ref ETF {ref_etf.upper()}" if ref_etf else ""
    click.echo(f"Added fund {name} ({code}){ref_msg}")


@fundw.command("remove")
@click.argument("code")
def fundw_remove(code: str):
    """Remove an OTC fund from watchlist."""
    watchlist = load_fund_watchlist()
    original = len(watchlist)
    watchlist = [item for item in watchlist if item["code"] != code]
    if len(watchlist) == original:
        click.echo(f"{code} not found in fund watchlist")
        return
    save_fund_watchlist(watchlist)
    click.echo(f"Removed fund {code}")


@fundw.command("list")
def fundw_list():
    """List OTC fund watchlist."""
    watchlist = load_fund_watchlist()
    if not watchlist:
        click.echo("Fund watchlist is empty. Use 'etf fundw add <code> [--ref <etf>]'")
        return
    click.echo(f"\n{'代码':<10} {'名称':<30} {'参考ETF':<10}")
    click.echo("-" * 55)
    for item in watchlist:
        ref = item.get("ref_etf", "")
        click.echo(f"{item['code']:<10} {item['name']:<30} {ref:<10}")


@fundw.command("watch")
@click.option("--json", "output_json", is_flag=True)
def fundw_watch(output_json: bool):
    """Show all OTC funds with intraday estimate and reference ETF."""
    watchlist = load_fund_watchlist()
    if not watchlist:
        click.echo("Fund watchlist is empty. Use 'etf fundw add <code>'")
        return

    results = []
    for item in watchlist:
        code = item["code"]
        fund_q = fetch_fund_quote(code)
        ref_etf = item.get("ref_etf")
        ref_q = fetch_quote(ref_etf) if ref_etf else None
        proxy = None
        if fund_q is None or fund_q.estimated_change_pct is None:
            proxy = estimate_fund_by_holdings(code)
        results.append({
            "code": code,
            "name": fund_q.name if fund_q else (proxy["fund_name"] if proxy else item.get("name", code)),
            "estimate_pct": fund_q.estimated_change_pct if fund_q and fund_q.estimated_change_pct else None,
            "estimate_time": fund_q.estimate_time if fund_q else None,
            "latest_nav": fund_q.latest_nav if fund_q else None,
            "ref_etf": ref_etf,
            "ref_etf_pct": ref_q.change_pct if ref_q else None,
            "proxy_pct": proxy["estimated_change_pct"] if proxy else None,
            "proxy_coverage": proxy["holdings_coverage"] if proxy else None,
            "proxy_stock_ratio": proxy.get("stock_ratio") if proxy else None,
        })

    if output_json:
        click.echo(json.dumps(results, indent=2, ensure_ascii=False))
        return

    click.echo("\n场外基金盘中估算\n")
    click.echo(f"{'代码':<8} {'名称':<24} {'官方估算':>10} {'代理估算':>10} {'参考ETF':>10}")
    click.echo("-" * 70)
    for r in results:
        est = f"{r['estimate_pct']:+.2f}%" if r["estimate_pct"] is not None else "N/A"
        proxy = f"{r['proxy_pct']:+.2f}%" if r["proxy_pct"] is not None else ""
        if r["ref_etf"] and r["ref_etf_pct"] is not None:
            ref = f"{r['ref_etf']} {r['ref_etf_pct']:+.2f}%"
        else:
            ref = ""
        click.echo(f"{r['code']:<8} {r['name']:<24} {est:>10} {proxy:>10} {ref:>10}")


@cli.command()
def est():
    """One-click estimate: all fund watchlist + all pairs."""
    import datetime
    lines = []
    lines.append("=" * 60)
    lines.append("一键持仓估算")
    lines.append(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    watchlist = load_fund_watchlist()
    if watchlist:
        lines.append("\n## 场外基金")
        for item in watchlist:
            code = item["code"]
            fund_q = fetch_fund_quote(code)
            ref_etf = item.get("ref_etf")
            ref_q = fetch_quote(ref_etf) if ref_etf else None
            proxy = None
            if fund_q is None or fund_q.estimated_change_pct is None:
                proxy = estimate_fund_by_holdings(code)
            name = fund_q.name if fund_q else (proxy["fund_name"] if proxy else item.get("name", code))

            est_str = f"官方估算 {fund_q.estimated_change_pct:+.2f}%" if fund_q and fund_q.estimated_change_pct is not None else ""
            proxy_str = f"重仓估算 {proxy['estimated_change_pct']:+.2f}% (覆盖{proxy['holdings_coverage']:.0f}%)" if proxy else ""
            ref_str = f"参考ETF {ref_q.name} {ref_q.change_pct:+.2f}%" if ref_q else ""
            parts = [p for p in [est_str, proxy_str, ref_str] if p]
            line = f"{name} ({code}): {' | '.join(parts) if parts else '暂无数据'}"
            lines.append(f"  {line}")

    pairs = load_pairs()
    if pairs:
        lines.append("\n## 场内+场外配对")
        for name, item in pairs.items():
            etf_q = fetch_quote(item["etf"])
            fund_q = fetch_fund_quote(item["fund"])
            etf_str = f"{etf_q.change_pct:+.2f}%" if etf_q else "N/A"
            fund_str = f"{fund_q.estimated_change_pct:+.2f}%" if fund_q and fund_q.estimated_change_pct else "N/A"
            lines.append(f"  {name}: 场内 {item['etf']} {etf_str} | 场外 {item['fund']} {fund_str}")

    click.echo("\n".join(lines))
