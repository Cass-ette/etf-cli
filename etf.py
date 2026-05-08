#!/usr/bin/env python3
"""
etf - A simple CLI for A-share ETF real-time quotes
Primary: Eastmoney API (verified stable)
Fallback: Tencent API
"""

import json
import sys
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, asdict
from functools import wraps
import time

import click
import requests

CONFIG_DIR = Path.home() / ".etf"
CONFIG_FILE = CONFIG_DIR / "watchlist.json"
FUND_PAIR_FILE = CONFIG_DIR / "pairs.json"

# API endpoints
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_BATCH_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TIANTIAN_FUND_URL = "https://fundgz.1234567.com.cn/js"

# Data provider registry
DATA_PROVIDERS = {}


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


def output_pair_context(name: str, output_json: bool = False) -> bool:
    """Output combined ETF/fund pair context. Returns False if pair cannot be fetched."""
    pairs = load_pairs()
    if name not in pairs:
        click.echo(f"Pair {name} not found", err=True)
        return False

    item = pairs[name]
    etf_quote = fetch_quote(item["etf"])
    fund_quote = fetch_fund_quote(item["fund"])

    if not etf_quote or not fund_quote:
        click.echo(f"Failed to fetch pair {name}", err=True)
        return False

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
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        click.echo(f"# ETF / 场外基金配对行情上下文: {name}\n")
        click.echo("## 场内 ETF 参考\n")
        click.echo(etf_quote.to_ai_context())
        click.echo("\n## 场外基金实际交易对象\n")
        click.echo(fund_quote.to_ai_context())
        click.echo("\n## 重要说明")
        click.echo("- 场内 ETF 是交易所实时价格。")
        click.echo("- 场外基金以最终净值成交，估算净值仅供参考。")
        click.echo("- 如果是 15:00 前申购/赎回，通常按当日最终净值结算。")
    return True


@cli.command()
@click.argument("key")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for AI processing")
def smart(key: str, output_json: bool):
    """Smart lookup: pair name, ETF code, or OTC fund code"""
    pairs = load_pairs()
    if key in pairs:
        if not output_pair_context(key, output_json=output_json):
            sys.exit(1)
        return

    if is_exchange_traded_etf_code(key):
        quote = fetch_quote(key)
        if not quote:
            click.echo(f"Failed to fetch ETF quote for {key}", err=True)
            sys.exit(1)
        if output_json:
            click.echo(json.dumps(quote.to_dict(), indent=2, ensure_ascii=False))
        else:
            click.echo(quote.to_ai_context())
        return

    quote = fetch_fund_quote(key)
    if not quote:
        click.echo(f"Cannot smart-resolve {key}. Try 'etf get {key}', 'etf fund {key}', or 'etf pair get {key}'.", err=True)
        sys.exit(1)

    if output_json:
        click.echo(json.dumps(quote.to_dict(), indent=2, ensure_ascii=False))
    else:
        click.echo(quote.to_ai_context())


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
        if not output_pair_context(name, output_json=output_json):
            sys.exit(1)
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
