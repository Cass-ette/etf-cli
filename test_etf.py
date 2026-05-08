import json

import click
from click.testing import CliRunner

import etf


def test_fetch_fund_quote_parses_tiantian_jsonp(monkeypatch):
    class Response:
        text = 'jsonpgz({"fundcode":"018344","name":"华夏中证机器人ETF发起式联接A","jzrq":"2026-05-07","dwjz":"1.0832","gsz":"1.0960","gszzl":"1.18","gztime":"2026-05-08 14:55"});'

        def raise_for_status(self):
            return None

    def fake_get(url, params, timeout):
        assert url == "https://fundgz.1234567.com.cn/js/018344.js"
        assert "rt" in params
        assert timeout == 10
        return Response()

    monkeypatch.setattr(etf.requests, "get", fake_get)

    quote = etf.fetch_fund_quote("018344")

    assert quote.symbol == "018344"
    assert quote.name == "华夏中证机器人ETF发起式联接A"
    assert quote.latest_nav == 1.0832
    assert quote.latest_nav_date == "2026-05-07"
    assert quote.estimated_nav == 1.096
    assert quote.estimated_change_pct == 1.18
    assert quote.estimate_time == "2026-05-08 14:55"


def test_fund_command_outputs_json(monkeypatch):
    quote = etf.OTCFundQuote(
        symbol="018344",
        name="华夏中证机器人ETF发起式联接A",
        latest_nav=1.0832,
        latest_nav_date="2026-05-07",
        estimated_nav=1.096,
        estimated_change_pct=1.18,
        estimate_time="2026-05-08 14:55",
    )
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda symbol: quote)

    result = CliRunner().invoke(etf.cli, ["fund", "018344", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["symbol"] == "018344"
    assert data["name"] == "华夏中证机器人ETF发起式联接A"
    assert data["estimated_change_pct"] == 1.18


def test_fund_command_outputs_human_readable_otc_label(monkeypatch):
    quote = etf.OTCFundQuote(
        symbol="018344",
        name="华夏中证机器人ETF发起式联接A",
        latest_nav=1.0832,
        latest_nav_date="2026-05-07",
        estimated_nav=1.096,
        estimated_change_pct=1.18,
        estimate_time="2026-05-08 14:55",
    )
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda symbol: quote)

    result = CliRunner().invoke(etf.cli, ["fund", "018344"])

    assert result.exit_code == 0
    assert "场外基金" in result.output
    assert "华夏中证机器人ETF发起式联接A" in result.output
    assert "估算涨跌幅: +1.18%" in result.output


def test_pair_add_and_get_json_uses_config_file(monkeypatch, tmp_path):
    pair_file = tmp_path / "pairs.json"
    monkeypatch.setattr(etf, "FUND_PAIR_FILE", pair_file)
    monkeypatch.setattr(etf, "fetch_quote", lambda symbol: etf.ETFQuote(
        symbol="562500",
        name="机器人ETF华夏",
        market="SH",
        latest=1.122,
        open=1.094,
        high=1.126,
        low=1.091,
        prev_close=1.097,
        change_amount=0.025,
        change_pct=2.28,
        volume=14041248,
        amount=1563574566,
    ))
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda symbol: etf.OTCFundQuote(
        symbol="018344",
        name="华夏中证机器人ETF发起式联接A",
        latest_nav=1.3222,
        latest_nav_date="2026-05-07",
        estimated_nav=1.3542,
        estimated_change_pct=2.42,
        estimate_time="2026-05-08 15:00",
    ))

    runner = CliRunner()
    add_result = runner.invoke(etf.cli, ["pair", "add", "robot", "562500", "018344"])
    get_result = runner.invoke(etf.cli, ["pair", "get", "robot", "--json"])

    assert add_result.exit_code == 0
    assert get_result.exit_code == 0
    data = json.loads(get_result.output)
    assert data["type"] == "etf_otc_fund_pair"
    assert data["name"] == "robot"
    assert data["exchange_traded_etf"]["symbol"] == "562500"
    assert data["otc_fund"]["symbol"] == "018344"
    assert "exchange_traded_etf is real-time market price" in data["notes"]


def test_pair_get_ai_labels_etf_and_otc_fund(monkeypatch, tmp_path):
    pair_file = tmp_path / "pairs.json"
    pair_file.write_text(json.dumps({"robot": {"name": "robot", "etf": "562500", "fund": "018344"}}))
    monkeypatch.setattr(etf, "FUND_PAIR_FILE", pair_file)
    monkeypatch.setattr(etf, "fetch_quote", lambda symbol: etf.ETFQuote(
        symbol="562500",
        name="机器人ETF华夏",
        market="SH",
        latest=1.122,
        open=1.094,
        high=1.126,
        low=1.091,
        prev_close=1.097,
        change_amount=0.025,
        change_pct=2.28,
        volume=14041248,
        amount=1563574566,
    ))
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda symbol: etf.OTCFundQuote(
        symbol="018344",
        name="华夏中证机器人ETF发起式联接A",
        latest_nav=1.3222,
        latest_nav_date="2026-05-07",
        estimated_nav=1.3542,
        estimated_change_pct=2.42,
        estimate_time="2026-05-08 15:00",
    ))

    result = CliRunner().invoke(etf.cli, ["pair", "get", "robot", "--ai"])

    assert result.exit_code == 0
    assert "场内 ETF 参考" in result.output
    assert "场外基金实际交易对象" in result.output
    assert "估算净值仅供参考" in result.output
