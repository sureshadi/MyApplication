"""Market research agent: figures from SEC XBRL facts, changes computed in code, red flags, Claude fallback."""

from types import SimpleNamespace

import httpx
import pytest
import respx

from app import research
from tests import sec_fixtures

UA = "Test agent test@example.com"


def fundamentals(**kw):
    return research.extract_fundamentals(sec_fixtures.company_facts(**kw))


def metric(f, name):
    return next(m for m in f.metrics if m.name == name)


class TestFigures:
    def test_latest_quarter_compared_with_same_quarter_last_year(self):
        f = fundamentals()
        rev = metric(f, "Revenue")
        assert rev.period == "Quarter ended Sep 27, 2026"
        assert (rev.current, rev.prior, rev.change) == (102.0e9, 94.0e9, 8.5)
        assert rev.basis == "GAAP"

    def test_restated_value_from_newer_filing_wins(self):
        facts = sec_fixtures.company_facts()
        entries = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
        entries.append({"start": sec_fixtures.Q_PRI[0], "end": sec_fixtures.Q_PRI[1], "val": 100.0e9,
                        "form": "10-K/A", "filed": "2026-11-15"})
        rev = metric(research.extract_fundamentals(facts), "Revenue")
        assert rev.prior == 100.0e9
        assert rev.change == 2.0

    def test_margins_change_in_percentage_points(self):
        f = fundamentals()
        gm = metric(f, "Gross margin")
        assert (gm.current, gm.prior, gm.change, gm.change_unit) == (47.0, 46.0, 1.0, "pp")
        assert metric(f, "Operating margin").change == 1.0

    def test_cash_flow_uses_its_own_period_and_free_cash_flow_is_derived(self):
        f = fundamentals()
        ocf, fcf = metric(f, "Operating cash flow"), metric(f, "Free cash flow")
        assert ocf.period == "Year ended Sep 27, 2026"
        assert (fcf.current, fcf.prior) == (98.0e9, 108.5e9)
        assert fcf.change == -9.7

    def test_balance_sheet_items_and_total_debt(self):
        f = fundamentals()
        assert metric(f, "Cash and equivalents").period == "As of Sep 27, 2026"
        debt = metric(f, "Total debt")
        assert (debt.current, debt.prior) == (90.0e9, 95.9e9)

    def test_eps_and_shareholder_returns(self):
        f = fundamentals()
        eps = metric(f, "Diluted EPS")
        assert (eps.current, eps.unit) == (1.85, "eps")
        assert metric(f, "Share buybacks").current == 90.0e9
        assert metric(f, "Dividends paid").current == 15.4e9

    def test_missing_figures_are_left_out_not_estimated(self):
        facts = sec_fixtures.company_facts()
        del facts["facts"]["us-gaap"]["GrossProfit"]
        names = [m.name for m in research.extract_fundamentals(facts).metrics]
        assert "Gross margin" not in names and "Revenue" in names

    def test_no_prior_year_means_no_change(self):
        facts = sec_fixtures.company_facts()
        entries = facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]
        facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"] = [e for e in entries if e["end"] != sec_fixtures.Q_PRI[1]]
        ni = metric(research.extract_fundamentals(facts), "Net income")
        assert ni.prior is None and ni.change is None

    def test_swing_to_loss_has_no_percentage(self):
        ni = metric(fundamentals(net_income=(-1.0e9, 2.0e9)), "Net income")
        assert ni.change is None

    def test_company_without_us_gaap_facts(self):
        f = research.extract_fundamentals({"facts": {"ifrs-full": {}}})
        assert f.metrics == []
        assert [r.title for r in research.red_flags(f)] == ["No standard financial data"]


class TestRedFlags:
    def titles(self, risks):
        return [r.title for r in risks]

    def test_default_company_flags_receivables_and_cash_flow(self):
        risks = research.red_flags(fundamentals())
        assert self.titles(risks) == ["Receivables growing faster than revenue", "Cash flow falling while earnings rise"]

    def test_healthy_company_has_no_flags(self):
        risks = research.red_flags(fundamentals(receivables=(31.0e9, 30.0e9), ocf=(120.0e9, 110.0e9)))
        assert risks == []

    def test_shrinking_revenue_and_loss_are_high_severity_and_listed_first(self):
        risks = research.red_flags(fundamentals(revenue=(8.0e9, 10.0e9), net_income=(-1.0e9, 0.5e9)))
        assert risks[0].severity == "high" and risks[1].severity == "high"
        assert {"Revenue is shrinking", "Net loss"} <= set(self.titles(risks))
        assert "fell 20.0%" in risks[0].detail

    def test_risks_are_sorted_by_severity(self):
        risks = research.red_flags(fundamentals(revenue=(9.5e9, 10.0e9)), price_change_pct=-15.0)
        order = [research.SEVERITY_ORDER[r.severity] for r in risks]
        assert order == sorted(order)
        assert "Share price fell sharply" in self.titles(risks)

    def test_inventory_flag_explains_inventory_not_collections(self):
        facts = sec_fixtures.company_facts(receivables=(31.0e9, 30.0e9), ocf=(120.0e9, 110.0e9))
        facts["facts"]["us-gaap"]["InventoryNet"] = sec_fixtures._instant(15.0e9, 6.0e9)
        risks = research.red_flags(research.extract_fundamentals(facts))
        assert self.titles(risks) == ["Inventory growing faster than revenue"]
        assert "unsold stock" in risks[0].detail and "collect" not in risks[0].detail

    def test_receivables_flag_explains_slower_payments(self):
        risk = research.red_flags(fundamentals())[0]
        assert risk.title == "Receivables growing faster than revenue"
        assert "paying more slowly" in risk.detail

    def test_high_leverage(self):
        risks = research.red_flags(fundamentals(equity=(30.0e9, 28.0e9)))
        lev = next(r for r in risks if r.title == "High leverage")
        assert "3.0x" in lev.detail

    def test_negative_equity_with_buybacks_is_low_severity(self):
        risks = research.red_flags(fundamentals(equity=(-5.0e9, 2.0e9)))
        neg = next(r for r in risks if r.title == "Negative shareholders' equity")
        assert neg.severity == "low"

    def test_small_price_drop_is_not_flagged(self):
        assert "Share price fell sharply" not in self.titles(research.red_flags(fundamentals(), price_change_pct=-4.0))


class TestSummary:
    def test_rule_based_headline_and_drivers(self):
        headline, drivers = research.rule_based_summary("Apple Inc.", fundamentals())
        assert headline == ("Apple Inc. revenue grew 8.5% year over year to $102.00B (quarter ended Sep 27, 2026), "
                            "with net income of $27.00B (+12.5%).")
        assert drivers[0] == "Revenue +8.5% year over year to $102.00B (GAAP)."
        assert len(drivers) <= 5

    def test_swing_to_loss_driver(self):
        _, drivers = research.rule_based_summary("X", fundamentals(net_income=(-1.0e9, 2.0e9)))
        assert "Net income swung to a loss of $1.00B, from $2.00B a year earlier (GAAP)." in drivers

    @pytest.mark.parametrize("value,text", [(1.5e12, "$1.50T"), (-2.25e9, "-$2.25B"), (3.4e6, "$3.40M"), (512, "$512"), (None, "n/a")])
    def test_money(self, value, text):
        assert research.money(value) == text


class TestLookup:
    async def test_cik_lookup_pads_to_ten_digits(self):
        async with httpx.AsyncClient() as client:
            assert await research.lookup_cik(client, "aapl", UA, sec_fixtures.SEC_TICKERS) == ("0000320193", "Apple Inc.")

    async def test_unknown_ticker(self):
        async with httpx.AsyncClient() as client:
            with pytest.raises(research.CompanyNotFound):
                await research.lookup_cik(client, "SPY", UA, sec_fixtures.SEC_TICKERS)

    def test_recent_filings_keeps_only_10k_and_10q_with_links(self):
        filings = research.recent_filings(sec_fixtures.submissions(), "0000320193")
        assert [f.form for f in filings] == ["10-K", "10-Q"]
        assert filings[0].url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000099/aapl-20260927.htm"


@pytest.fixture
def sec(mock_http):
    return mock_http


class FakeAnalyst:
    def __init__(self, result):
        self.result = result
        self.payloads = []

    async def __call__(self, payload):
        self.payloads.append(payload)
        return self.result


class TestAnalyze:
    async def analyze(self, analyst=None, **kw):
        async with httpx.AsyncClient() as client:
            return await research.analyze(client, "AAPL", user_agent=UA, tickers=sec_fixtures.SEC_TICKERS,
                                          analyst=analyst, **kw)

    async def test_rule_based_analysis_puts_risks_first_and_cites_sources(self, sec):
        a = (await self.analyze()).to_dict()
        assert list(a)[:6] == ["symbol", "name", "cik", "period", "headline", "risks"]
        assert a["analyst"] == "rules"
        assert a["risks"][0]["title"] == "Receivables growing faster than revenue"
        assert a["sources"][0]["label"] == "10-K filed 2026-10-30 (period 2026-09-27)"
        assert a["sources"][-1]["url"].endswith("CIK0000320193.json")
        assert "Not financial advice" in a["disclaimer"]
        assert "earnings release" in a["guidance"]

    async def test_sends_user_agent_to_sec(self, sec):
        await self.analyze()
        sec_calls = [c.request for c in sec.calls if "sec.gov" in c.request.url.host]
        assert sec_calls and all(r.headers["User-Agent"] == UA for r in sec_calls)

    async def test_claude_narrative_and_risks_are_used_and_computed_flags_kept(self, sec):
        analyst = FakeAnalyst({
            "headline": "Strong quarter on services growth.",
            "drivers": ["Services revenue grew, per headlines."],
            "guidance": "Management expects growth to continue (per Nov 18 headline).",
            "risks": [
                {"title": "EU regulatory review", "detail": "A headline reports a formal review.", "severity": "high"},
                {"title": "Cash flow falling while earnings rise", "detail": "Same as computed.", "severity": "medium"},
            ],
        })
        a = await self.analyze(analyst, headlines=[{"title": "Apple faces EU review", "source": "Yahoo Finance"}])
        assert a.analyst == "claude"
        assert a.headline == "Strong quarter on services growth."
        titles = [r.title for r in a.risks]
        assert titles[0] == "EU regulatory review"
        assert "Receivables growing faster than revenue" in titles  # computed flag Claude missed is kept
        assert titles.count("Cash flow falling while earnings rise") == 1
        payload = analyst.payloads[0]
        assert payload["symbol"] == "AAPL" and payload["metrics"][0]["name"] == "Revenue"
        assert payload["recent_headlines"][0]["title"] == "Apple faces EU review"
        assert payload["computed_red_flags"]

    async def test_falls_back_to_rules_when_claude_fails(self, sec):
        a = await self.analyze(FakeAnalyst(None))
        assert a.analyst == "rules"
        assert a.headline.startswith("Apple Inc. revenue grew 8.5%")

    async def test_bad_claude_output_is_ignored(self, sec):
        a = await self.analyze(FakeAnalyst({"risks": [{"oops": 1}]}))
        assert a.analyst == "rules"

    async def test_sec_outage(self):
        with respx.mock() as router:
            router.get(url__regex=r"https://data\.sec\.gov/.*").mock(side_effect=httpx.ConnectError("down"))
            with pytest.raises(research.ResearchUnavailable):
                await self.analyze()


class TestClaudeAnalyst:
    def test_no_key_means_no_analyst(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert research.default_analyst() is None

    def test_key_builds_analyst_with_latest_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("RESEARCH_MODEL", raising=False)
        analyst = research.default_analyst()
        assert isinstance(analyst, research.ClaudeAnalyst)
        assert analyst.model == "claude-opus-5-5"

    @staticmethod
    def analyst_with(create):
        """A ClaudeAnalyst whose API client is replaced, so no request leaves the test."""
        analyst = research.ClaudeAnalyst("sk-test")
        analyst.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        return analyst

    async def test_request_shape_and_json_parsing(self):
        captured = {}

        async def create(**kwargs):
            captured.update(kwargs)
            text = '{"headline":"h","drivers":[],"guidance":"g","risks":[]}'
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])

        result = await self.analyst_with(create)({"symbol": "AAPL"})
        assert result == {"headline": "h", "drivers": [], "guidance": "g", "risks": []}
        assert captured["model"] == "claude-opus-5-5"
        assert captured["output_config"]["format"]["schema"] is research.ANALYSIS_SCHEMA
        assert captured["fallbacks"] == "default"
        assert captured["betas"] == ["server-side-fallback-2026-07-01"]
        assert '"symbol": "AAPL"' in captured["messages"][0]["content"]

    @pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
    async def test_refusal_or_cut_off_returns_none(self, stop_reason):
        async def create(**kwargs):
            return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text="{}")])

        assert await self.analyst_with(create)({"symbol": "AAPL"}) is None

    async def test_api_error_returns_none(self):
        import anthropic

        async def create(**kwargs):
            raise anthropic.APIConnectionError(request=None)

        assert await self.analyst_with(create)({"symbol": "AAPL"}) is None

    async def test_invalid_json_returns_none(self):
        async def create(**kwargs):
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="not json")])

        assert await self.analyst_with(create)({"symbol": "AAPL"}) is None


class TestComparisons:
    """The Portfolio period picker: figures compared with a quarter, two quarters, or 1, 2 or 5 years earlier."""

    @staticmethod
    def revenue_and_cash_flow(months):
        f = research.extract_fundamentals(sec_fixtures.company_facts(), months)
        by_name = {m.name: m for m in f.metrics}
        return by_name["Revenue"], by_name["Operating cash flow"], by_name["Cash and equivalents"]

    @pytest.mark.parametrize("key, prior, change", [
        ("3M", 96.9e9, 5.3), ("6M", 93.84e9, 8.7), ("1Y", 94.0e9, 8.5), ("2Y", 84.6e9, 20.6), ("5Y", 56.4e9, 80.9),
    ])
    def test_quarterly_figures_use_the_matching_earlier_quarter(self, key, prior, change):
        revenue, _, _ = self.revenue_and_cash_flow(research.COMPARISONS[key].months)
        assert revenue.prior == pytest.approx(prior) and revenue.change == change

    def test_annual_figures_use_the_trailing_year_a_quarter_earlier(self):
        # Fiscal 2025 (118B) + nine months of 2026 (0.74 x 110B) - nine months of 2025 (0.73 x 118B).
        _, ocf, _ = self.revenue_and_cash_flow(3)
        assert ocf.prior == pytest.approx(118e9 + 0.74 * 110e9 - 0.73 * 118e9)

    def test_balance_sheet_figures_use_the_earlier_date(self):
        _, _, cash = self.revenue_and_cash_flow(3)
        assert cash.prior == pytest.approx(0.97 * 35e9)

    def test_missing_history_leaves_no_comparison(self):
        facts = sec_fixtures.company_facts()
        rev = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
        rev[:] = [e for e in rev if not e["end"].startswith("2021")]
        f = research.extract_fundamentals(facts, 60)
        assert f.metrics[0].prior is None and f.metrics[0].change is None

    def test_wording_follows_the_comparison(self):
        cmp = research.COMPARISONS["3M"]
        f = research.extract_fundamentals(sec_fixtures.company_facts(), cmp.months)
        risks = research.red_flags(f, price_change_pct=-15.0, comparison=cmp)
        details = " ".join(r.detail for r in risks)
        assert "year over year" not in details and "over the last 3 months" in details
        headline, drivers = research.rule_based_summary("Apple Inc.", f, cmp)
        assert "quarter over quarter" in headline and all("year over year" not in d for d in drivers)

    async def test_analysis_reports_its_comparison(self, sec):
        async with httpx.AsyncClient() as client:
            a = await research.analyze(client, "AAPL", user_agent="test", comparison="2Y")
        d = a.to_dict()
        assert d["comparison"] == {"key": "2Y", "label": "2 years ago", "phrase": "over two years",
                                    "earlier": "two years earlier", "price_window": "2 years"}
        assert d["metrics"][0]["prior"] == pytest.approx(84.6e9)
