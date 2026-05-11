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


def test_smart_uses_pair_ai_context_when_key_matches_pair(monkeypatch, tmp_path):
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

    result = CliRunner().invoke(etf.cli, ["smart", "robot"])

    assert result.exit_code == 0
    assert "ETF / 场外基金配对行情上下文: robot" in result.output
    assert "场内 ETF 参考" in result.output
    assert "场外基金实际交易对象" in result.output


def test_smart_uses_etf_quote_for_exchange_traded_code(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_PAIR_FILE", tmp_path / "pairs.json")
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

    result = CliRunner().invoke(etf.cli, ["smart", "562500"])

    assert result.exit_code == 0
    assert "类型**: 场内 ETF" in result.output
    assert "机器人ETF华夏" in result.output


def test_smart_uses_fund_quote_for_non_etf_six_digit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_PAIR_FILE", tmp_path / "pairs.json")
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda symbol: etf.OTCFundQuote(
        symbol="018344",
        name="华夏中证机器人ETF发起式联接A",
        latest_nav=1.3222,
        latest_nav_date="2026-05-07",
        estimated_nav=1.3542,
        estimated_change_pct=2.42,
        estimate_time="2026-05-08 15:00",
    ))

    result = CliRunner().invoke(etf.cli, ["smart", "018344"])

    assert result.exit_code == 0
    assert "类型**: 场外基金" in result.output
    assert "华夏中证机器人ETF发起式联接A" in result.output


def test_smart_copy_copies_pair_ai_context(monkeypatch, tmp_path):
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

    copied = []
    monkeypatch.setattr(etf, "copy_to_clipboard", lambda text: copied.append(text) or True)

    result = CliRunner().invoke(etf.cli, ["smart", "robot", "--copy"])

    assert result.exit_code == 0
    assert copied
    assert "ETF / 场外基金配对行情上下文: robot" in copied[0]
    assert "ETF / 场外基金配对行情上下文: robot" in result.output


# ============ Fund Watchlist Tests ============

def test_fundw_add_saves_to_watchlist(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda code: etf.OTCFundQuote(
        symbol="020404", name="易方达信创ETF联接C",
        latest_nav=2.0, latest_nav_date="2026-05-08",
        estimated_nav=2.1, estimated_change_pct=5.0,
        estimate_time="2026-05-11 14:00",
    ))
    result = CliRunner().invoke(etf.cli, ["fundw", "add", "020404", "--ref", "159540"])
    assert result.exit_code == 0
    assert "易方达信创ETF联接C" in result.output
    watchlist = json.loads((tmp_path / "fund_watchlist.json").read_text())
    assert len(watchlist) == 1
    assert watchlist[0]["code"] == "020404"
    assert watchlist[0]["ref_etf"] == "159540"


def test_fundw_add_rejects_duplicate(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C"},
    ]))
    result = CliRunner().invoke(etf.cli, ["fundw", "add", "020404"])
    assert result.exit_code == 0
    assert "already" in result.output


def test_fundw_remove_deletes_from_watchlist(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C"},
        {"code": "009447", "name": "财通科技创新"},
    ]))
    result = CliRunner().invoke(etf.cli, ["fundw", "remove", "020404"])
    assert result.exit_code == 0
    watchlist = json.loads((tmp_path / "fund_watchlist.json").read_text())
    assert len(watchlist) == 1
    assert watchlist[0]["code"] == "009447"


def test_fundw_list_shows_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C", "ref_etf": "159540"},
        {"code": "009447", "name": "财通科技创新"},
    ]))
    result = CliRunner().invoke(etf.cli, ["fundw", "list"])
    assert result.exit_code == 0
    assert "020404" in result.output
    assert "009447" in result.output
    assert "159540" in result.output


def test_fundw_watch_shows_estimates(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C", "ref_etf": "159540"},
    ]))
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda code: etf.OTCFundQuote(
        symbol=code, name="易方达信创ETF联接C",
        latest_nav=2.0, latest_nav_date="2026-05-08",
        estimated_nav=2.1, estimated_change_pct=5.01,
        estimate_time="2026-05-11 14:00",
    ))
    monkeypatch.setattr(etf, "fetch_quote", lambda code: etf.ETFQuote(
        symbol="159540", name="信创ETF易方达", market="SZ",
        latest=2.115, open=2.07, high=2.14, low=2.062,
        prev_close=2.014, change_amount=0.101, change_pct=5.01,
        volume=1505, amount=3315000,
    ))

    result = CliRunner().invoke(etf.cli, ["fundw", "watch"])
    assert result.exit_code == 0
    assert "020404" in result.output
    assert "+5.01%" in result.output
    assert "159540" in result.output


def test_fundw_watch_json_output(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C", "ref_etf": "159540"},
    ]))
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda code: etf.OTCFundQuote(
        symbol=code, name="易方达信创ETF联接C",
        latest_nav=2.0, latest_nav_date="2026-05-08",
        estimated_nav=2.1, estimated_change_pct=5.01,
        estimate_time="2026-05-11 14:00",
    ))
    monkeypatch.setattr(etf, "fetch_quote", lambda code: etf.ETFQuote(
        symbol="159540", name="信创ETF易方达", market="SZ",
        latest=2.115, open=2.07, high=2.14, low=2.062,
        prev_close=2.014, change_amount=0.101, change_pct=5.01,
        volume=1505, amount=3315000,
    ))

    result = CliRunner().invoke(etf.cli, ["fundw", "watch", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["estimate_pct"] == 5.01
    assert data[0]["ref_etf_pct"] == 5.01


def test_est_command_shows_funds_and_pairs(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    monkeypatch.setattr(etf, "FUND_PAIR_FILE", tmp_path / "pairs.json")
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C", "ref_etf": "159540"},
    ]))
    (tmp_path / "pairs.json").write_text(json.dumps({
        "robot": {"name": "robot", "etf": "562500", "fund": "018344"},
    }))
    monkeypatch.setattr(etf, "fetch_fund_quote", lambda code: etf.OTCFundQuote(
        symbol=code, name="test fund",
        latest_nav=1.0, latest_nav_date="2026-05-08",
        estimated_nav=1.05, estimated_change_pct=2.42,
        estimate_time="2026-05-11 14:00",
    ))
    monkeypatch.setattr(etf, "fetch_quote", lambda code: etf.ETFQuote(
        symbol=code, name="test ETF", market="SH",
        latest=1.0, open=1.0, high=1.0, low=1.0,
        prev_close=1.0, change_amount=0.01, change_pct=1.5,
        volume=100, amount=10000,
    ))

    result = CliRunner().invoke(etf.cli, ["est"])
    assert result.exit_code == 0
    assert "一键持仓估算" in result.output
    assert "场外基金" in result.output
    assert "场内+场外配对" in result.output
    assert "020404" in result.output
    assert "robot" in result.output


def test_holding_set_list_remove_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "HOLDINGS_FILE", tmp_path / "holdings.json")
    runner = CliRunner()

    set_result = runner.invoke(etf.cli, ["holding", "set", "020404", "561.89"])
    list_result = runner.invoke(etf.cli, ["holding", "list"])
    remove_result = runner.invoke(etf.cli, ["holding", "remove", "020404"])

    assert set_result.exit_code == 0
    assert "020404" in set_result.output
    assert list_result.exit_code == 0
    assert "020404" in list_result.output
    assert "561.89" in list_result.output
    assert remove_result.exit_code == 0
    assert json.loads((tmp_path / "holdings.json").read_text()) == []


def test_pnl_estimates_total_gain_from_holdings(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(etf, "FUND_WATCH_FILE", tmp_path / "fund_watchlist.json")
    (tmp_path / "holdings.json").write_text(json.dumps([
        {"code": "020404", "amount": 561.89},
        {"code": "024620", "amount": 3050.23},
    ]))
    (tmp_path / "fund_watchlist.json").write_text(json.dumps([
        {"code": "020404", "name": "易方达信创ETF联接C", "ref_etf": "159540"},
        {"code": "024620", "name": "嘉实机器人ETF联接C", "ref_etf": "159526"},
    ]))

    def fake_fund_quote(code):
        if code == "020404":
            return None
        return etf.OTCFundQuote(
            symbol=code, name="嘉实机器人ETF联接C",
            latest_nav=1.0, latest_nav_date="2026-05-08",
            estimated_nav=1.02, estimated_change_pct=1.66,
            estimate_time="2026-05-11 14:00",
        )

    def fake_quote(code):
        return etf.ETFQuote(
            symbol=code, name="ref ETF", market="SZ",
            latest=1.0, open=1.0, high=1.0, low=1.0,
            prev_close=1.0, change_amount=0.05, change_pct=5.56,
            volume=100, amount=10000,
        )

    monkeypatch.setattr(etf, "fetch_fund_quote", fake_fund_quote)
    monkeypatch.setattr(etf, "fetch_quote", fake_quote)

    result = CliRunner().invoke(etf.cli, ["pnl"])

    assert result.exit_code == 0
    assert "组合实时估算" in result.output
    assert "总市值: 3,612.12" in result.output
    assert "020404" in result.output
    assert "024620" in result.output
    # 561.89*5.56% + 3050.23*1.66% = 81.874902
    assert "+81.87" in result.output


def test_pnl_treats_cash_as_zero_change(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "HOLDINGS_FILE", tmp_path / "holdings.json")
    (tmp_path / "holdings.json").write_text(json.dumps([
        {"code": "cash", "amount": 1000.0},
    ]))
    result = CliRunner().invoke(etf.cli, ["pnl"])
    assert result.exit_code == 0
    assert "cash" in result.output
    assert "+0.00" in result.output
    assert "现金" in result.output
    assert "cash" in result.output


def test_pnl_includes_exchange_traded_etf_holdings(monkeypatch, tmp_path):
    monkeypatch.setattr(etf, "HOLDINGS_FILE", tmp_path / "holdings.json")
    (tmp_path / "holdings.json").write_text(json.dumps([
        {"code": "512800", "amount": 12141.00},
    ]))
    monkeypatch.setattr(etf, "fetch_quote", lambda code: etf.ETFQuote(
        symbol=code, name="银行ETF华宝", market="SH",
        latest=0.783, open=0.784, high=0.784, low=0.779,
        prev_close=0.785, change_amount=-0.002, change_pct=-0.25,
        volume=100, amount=10000,
    ))

    result = CliRunner().invoke(etf.cli, ["pnl"])

    assert result.exit_code == 0
    assert "512800" in result.output
    assert "银行ETF华宝" in result.output
    assert "-30.35" in result.output
    assert "etf" in result.output


def test_estimate_fund_by_holdings_weighted_average(monkeypatch):
    fake_detail = {
        "name": "财通科技创新",
        "stock_ratio": 88.0,
        "holdings": [
            {"code": "688981", "name": "中芯国际", "weight": 9.5},
            {"code": "002049", "name": "紫光国微", "weight": 8.2},
        ],
    }
    monkeypatch.setattr(etf, "fetch_fund_holdings", lambda code: fake_detail)
    stock_pcts = {"688981": 3.0, "002049": -1.0}
    monkeypatch.setattr(etf, "fetch_stock_quote_pct", lambda code: stock_pcts.get(code))

    result = etf.estimate_fund_by_holdings("009447")
    assert result is not None
    assert result["fund_code"] == "009447"
    # weighted: (9.5*3 + 8.2*(-1)) / (9.5+8.2) = (28.5 - 8.2) / 17.7 = 1.147
    assert abs(result["estimated_change_pct"] - 1.15) < 0.05
    assert result["holdings_coverage"] == 17.7
    assert len(result["holdings"]) == 2
