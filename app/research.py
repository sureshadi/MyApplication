"""Market research agent for the My Portfolio tab.

For each company it follows the financial-report-analysis method:

1. Identify the latest report on SEC EDGAR (10-K / 10-Q).
2. Extract the key figures for the latest period and the same period a year earlier
   (revenue, margins, net income, EPS, cash flow, cash, debt, buybacks, dividends).
3. Calculate the changes in code: year-over-year growth and margin changes in percentage points.
4. Explain the drivers and guidance. With ANTHROPIC_API_KEY set, Claude writes these from the
   figures and recent headlines; without a key, plain rule-based bullets are used.
5. Check for red flags (receivables or inventory growing faster than revenue, cash flow falling
   while earnings rise, losses, high leverage, ...). Risks are listed first in the result.

Every figure comes from the company's XBRL filings. Missing figures are reported as missing, never
estimated. The output is factual analysis only, not financial advice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date

import httpx

log = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FILING_INDEX_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-&dateb=&owner=include&count=40"
SEC_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"

DISCLAIMER = "Factual analysis of public filings only. Not financial advice."
CLAUDE_MODEL = "claude-opus-5-5"

# XBRL concepts tried in order for each metric (companies use different tags for the same thing).
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "current_debt": ("LongTermDebtCurrent", "DebtCurrent", "CommercialPaper"),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "receivables": ("AccountsReceivableNetCurrent",),
    "inventory": ("InventoryNet",),
}
INSTANT = {"cash", "long_term_debt", "current_debt", "equity", "receivables", "inventory"}


class CompanyNotFound(LookupError):
    """No SEC registrant for this ticker (ETFs, funds and most non-US companies)."""


class ResearchUnavailable(RuntimeError):
    """SEC EDGAR could not be reached."""


# ---------------------------------------------------------------------------
# Figures from XBRL company facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    value: float
    end: date
    start: date | None = None
    form: str = ""
    filed: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days if self.start else 0


@dataclass(frozen=True)
class Figure:
    """One metric for the latest period and the same period a year earlier."""

    key: str
    current: Fact
    prior: Fact | None = None

    @property
    def change_pct(self) -> float | None:
        if self.prior is None or not self.prior.value:
            return None
        if (self.current.value < 0) != (self.prior.value < 0):
            return None  # a swing between profit and loss has no meaningful percentage
        return round((self.current.value - self.prior.value) / abs(self.prior.value) * 100, 1)


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _facts_for(facts: dict, key: str) -> list[Fact]:
    """All facts for the first concept of a metric that has data, de-duplicated by period."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for concept in CONCEPTS[key]:
        units = (gaap.get(concept) or {}).get("units") or {}
        entries = units.get("USD") or units.get("USD/shares") or []
        by_period: dict[tuple, Fact] = {}
        for e in entries:
            end, start = _d(e.get("end")), _d(e.get("start"))
            if end is None or e.get("val") is None:
                continue
            if key not in INSTANT and start is None:
                continue
            fact = Fact(float(e["val"]), end, start, e.get("form", ""), e.get("filed", ""))
            period = (start, end)
            # The latest filing wins, so restated numbers replace the originals.
            if period not in by_period or fact.filed >= by_period[period].filed:
                by_period[period] = fact
        if by_period:
            return list(by_period.values())
    return []


def _year_earlier(candidates: list[Fact], current: Fact) -> Fact | None:
    """The fact covering the same span of time, ending about one year before `current`."""
    best = None
    for f in candidates:
        gap = (current.end - f.end).days
        if not 345 <= gap <= 385:
            continue
        if current.start is not None and abs(f.days - current.days) > 20:
            continue
        if best is None or abs(gap - 365) < abs((current.end - best.end).days - 365):
            best = f
    return best


def latest_figure(facts: dict, key: str, end: date | None = None) -> Figure | None:
    """Latest value for a metric with its year-earlier comparison.

    Flows (revenue, cash flow) use the shortest period of at least a quarter that ends on the
    latest date: a quarter for income statement lines, year-to-date for cash flow lines that
    10-Qs only report cumulatively. With `end`, use that period end (so metrics line up).
    """
    candidates = _facts_for(facts, key)
    if not candidates:
        return None
    if key not in INSTANT:
        candidates = [f for f in candidates if f.days >= 80]
        if not candidates:
            return None
    target = end or max(f.end for f in candidates)
    at_end = [f for f in candidates if f.end == target]
    if not at_end:
        return None
    current = min(at_end, key=lambda f: f.days)
    return Figure(key, current, _year_earlier(candidates, current))


def period_label(fact: Fact) -> str:
    when = fact.end.strftime("%b %-d, %Y")
    if fact.start is None:
        return f"As of {when}"
    months = round(fact.days / 30.4)
    if months <= 3:
        return f"Quarter ended {when}"
    if months >= 12:
        return f"Year ended {when}"
    return f"{months} months ended {when}"


@dataclass
class Metric:
    """One row of the key metrics table: Metric | This period | Prior year | Change."""

    name: str
    period: str
    current: float | None
    prior: float | None
    change: float | None  # percent, or percentage points for margins
    unit: str  # "usd", "eps", "pct"
    change_unit: str = "%"  # "%" or "pp"
    basis: str = "GAAP"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "period": self.period,
            "current": self.current,
            "prior": self.prior,
            "change": self.change,
            "unit": self.unit,
            "change_unit": self.change_unit,
            "basis": self.basis,
        }


def _metric(name: str, fig: Figure | None, unit: str = "usd") -> Metric | None:
    if fig is None:
        return None
    return Metric(
        name, period_label(fig.current), fig.current.value, fig.prior.value if fig.prior else None, fig.change_pct, unit
    )


def _margin(name: str, part: Figure | None, whole: Figure | None) -> Metric | None:
    if not part or not whole or not whole.current.value or part.current.end != whole.current.end:
        return None
    cur = round(part.current.value / whole.current.value * 100, 1)
    prior = None
    if part.prior and whole.prior and whole.prior.value and part.prior.end == whole.prior.end:
        prior = round(part.prior.value / whole.prior.value * 100, 1)
    change = round(cur - prior, 1) if prior is not None else None
    return Metric(name, period_label(whole.current), cur, prior, change, "pct", "pp")


def _pct_change(cur: float | None, prior: float | None) -> float | None:
    if cur is None or prior is None or not prior or (cur < 0) != (prior < 0):
        return None
    return round((cur - prior) / abs(prior) * 100, 1)


@dataclass
class Fundamentals:
    figures: dict[str, Figure]
    metrics: list[Metric]


def extract_fundamentals(facts: dict) -> Fundamentals:
    """Key figures and the metrics table, all computed from filed values."""
    figs: dict[str, Figure] = {}
    revenue = latest_figure(facts, "revenue")
    if revenue:
        figs["revenue"] = revenue
    # Income statement lines line up with the revenue period when possible.
    for key in ("gross_profit", "operating_income", "net_income", "eps_diluted"):
        fig = (latest_figure(facts, key, revenue.current.end) if revenue else None) or latest_figure(facts, key)
        if fig:
            figs[key] = fig
    ocf = latest_figure(facts, "operating_cash_flow")
    if ocf:
        figs["operating_cash_flow"] = ocf
    for key in ("capex", "buybacks", "dividends"):
        fig = (latest_figure(facts, key, ocf.current.end) if ocf else None) or latest_figure(facts, key)
        if fig:
            figs[key] = fig
    for key in INSTANT:
        fig = latest_figure(facts, key)
        if fig:
            figs[key] = fig

    g = figs.get
    rows: list[Metric | None] = [
        _metric("Revenue", g("revenue")),
        _margin("Gross margin", g("gross_profit"), g("revenue")),
        _metric("Operating income", g("operating_income")),
        _margin("Operating margin", g("operating_income"), g("revenue")),
        _metric("Net income", g("net_income")),
        _metric("Diluted EPS", g("eps_diluted"), "eps"),
        _metric("Operating cash flow", g("operating_cash_flow")),
    ]
    ocf, capex = g("operating_cash_flow"), g("capex")
    if ocf and capex and ocf.current.days == capex.current.days and ocf.current.end == capex.current.end:
        cur = ocf.current.value - capex.current.value
        prior = None
        if ocf.prior and capex.prior and ocf.prior.end == capex.prior.end:
            prior = ocf.prior.value - capex.prior.value
        rows.append(Metric("Free cash flow", period_label(ocf.current), cur, prior, _pct_change(cur, prior), "usd"))
    rows += [
        _metric("Cash and equivalents", g("cash")),
        _total_debt(g("long_term_debt"), g("current_debt")),
        _metric("Share buybacks", g("buybacks")),
        _metric("Dividends paid", g("dividends")),
    ]
    return Fundamentals(figs, [r for r in rows if r is not None])


def _total_debt(long_term: Figure | None, current: Figure | None) -> Metric | None:
    if long_term is None:
        return None
    cur = long_term.current.value
    prior = long_term.prior.value if long_term.prior else None
    if current and current.current.end == long_term.current.end:
        cur += current.current.value
        if prior is not None and current.prior and long_term.prior and current.prior.end == long_term.prior.end:
            prior += current.prior.value
    return Metric("Total debt", period_label(long_term.current), cur, prior, _pct_change(cur, prior), "usd")


# ---------------------------------------------------------------------------
# Red flags (step 5 of the method), computed in code
# ---------------------------------------------------------------------------


@dataclass
class Risk:
    title: str
    detail: str
    severity: str  # "high", "medium", "low"
    source: str = "filings"  # "filings", "market", "news", "analysis"

    def to_dict(self) -> dict:
        return {"title": self.title, "detail": self.detail, "severity": self.severity, "source": self.source}


def _lc(text: str) -> str:
    """'Quarter ended Sep 27' -> 'quarter ended Sep 27' (keeps month names capitalized)."""
    return text[:1].lower() + text[1:]


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= size:
            return f"{sign}${v / size:.2f}{suffix}"
    return f"{sign}${v:,.0f}"


def red_flags(f: Fundamentals, price_change_pct: float | None = None) -> list[Risk]:
    figs, risks = f.figures, []
    rev, ni = figs.get("revenue"), figs.get("net_income")
    rev_g = rev.change_pct if rev else None

    if rev_g is not None and rev_g < 0:
        risks.append(Risk(
            "Revenue is shrinking",
            f"Revenue fell {abs(rev_g):.1f}% year over year to {money(rev.current.value)} ({_lc(period_label(rev.current))}).",
            "high" if rev_g <= -10 else "medium",
        ))
    if ni and ni.current.value < 0:
        risks.append(Risk(
            "Net loss",
            f"The company lost {money(abs(ni.current.value))} ({_lc(period_label(ni.current))}).",
            "high",
        ))
    elif ni and ni.change_pct is not None and ni.change_pct <= -20:
        risks.append(Risk(
            "Earnings dropped sharply",
            f"Net income fell {abs(ni.change_pct):.1f}% year over year to {money(ni.current.value)}.",
            "medium",
        ))
    for key, label, meaning in (
        ("receivables", "Receivables", "This can mean customers are paying more slowly."),
        ("inventory", "Inventory", "This can mean unsold stock is building up or demand is weakening."),
    ):
        fig = figs.get(key)
        if fig and fig.change_pct is not None and rev_g is not None and fig.change_pct - rev_g > 10:
            risks.append(Risk(
                f"{label} growing faster than revenue",
                f"{label} rose {fig.change_pct:.1f}% year over year while revenue changed {rev_g:+.1f}%. {meaning}",
                "medium",
            ))
    ocf = figs.get("operating_cash_flow")
    if ocf and ni and ocf.change_pct is not None and ni.change_pct is not None and ocf.change_pct < 0 < ni.change_pct:
        risks.append(Risk(
            "Cash flow falling while earnings rise",
            f"Operating cash flow fell {abs(ocf.change_pct):.1f}% while net income rose {ni.change_pct:.1f}%. "
            "Earnings may be less backed by cash than they look.",
            "medium",
        ))
    fcf = next((m for m in f.metrics if m.name == "Free cash flow"), None)
    if fcf and fcf.current is not None and fcf.current < 0:
        risks.append(Risk(
            "Negative free cash flow",
            f"Free cash flow was {money(fcf.current)} ({_lc(fcf.period)}): the business spent more than it generated.",
            "medium",
        ))
    op_margin = next((m for m in f.metrics if m.name == "Operating margin"), None)
    if op_margin and op_margin.change is not None and op_margin.change <= -2:
        risks.append(Risk(
            "Operating margin is shrinking",
            f"Operating margin fell {abs(op_margin.change):.1f} percentage points to {op_margin.current:.1f}%.",
            "medium",
        ))
    equity = figs.get("equity")
    debt = next((m for m in f.metrics if m.name == "Total debt"), None)
    if equity and equity.current.value <= 0:
        risks.append(Risk(
            "Negative shareholders' equity",
            f"Liabilities exceed assets: equity is {money(equity.current.value)}. "
            "Often due to buybacks, but it leaves less cushion.",
            "low" if figs.get("buybacks") else "high",
        ))
    elif equity and debt and debt.current and debt.current / equity.current.value > 2:
        risks.append(Risk(
            "High leverage",
            f"Total debt of {money(debt.current)} is {debt.current / equity.current.value:.1f}x shareholders' equity.",
            "medium",
        ))
    cash = figs.get("cash")
    if cash and debt and debt.current and cash.current.value < debt.current * 0.1:
        risks.append(Risk(
            "Little cash against debt",
            f"Cash of {money(cash.current.value)} covers under 10% of {money(debt.current)} in debt.",
            "low",
        ))
    if price_change_pct is not None and price_change_pct <= -10:
        risks.append(Risk(
            "Share price fell sharply",
            f"The stock is down {abs(price_change_pct):.1f}% over the last month.",
            "medium",
            "market",
        ))
    if not f.metrics:
        risks.append(Risk(
            "No standard financial data",
            "The filings have no US GAAP figures this tool can read, so fundamentals could not be checked.",
            "low",
        ))
    return sort_risks(risks)


def sort_risks(risks: list[Risk]) -> list[Risk]:
    return sorted(risks, key=lambda r: SEVERITY_ORDER.get(r.severity, 3))


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------


@dataclass
class Filing:
    form: str
    filed: str
    period: str
    url: str

    def to_dict(self) -> dict:
        return {"form": self.form, "filed": self.filed, "period": self.period, "url": self.url}


@dataclass
class Analysis:
    symbol: str
    name: str
    cik: str
    headline: str
    risks: list[Risk]
    metrics: list[Metric]
    drivers: list[str]
    guidance: str
    sources: list[dict]
    analyst: str  # "claude" or "rules"
    period: str = ""
    filings: list[Filing] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "cik": self.cik,
            "period": self.period,
            "headline": self.headline,
            "risks": [r.to_dict() for r in self.risks],
            "metrics": [m.to_dict() for m in self.metrics],
            "drivers": self.drivers,
            "guidance": self.guidance,
            "sources": self.sources,
            "analyst": self.analyst,
            "disclaimer": DISCLAIMER,
        }


def rule_based_summary(name: str, f: Fundamentals) -> tuple[str, list[str]]:
    """Headline and driver bullets written from the computed changes alone."""
    by_name = {m.name: m for m in f.metrics}
    rev, ni = by_name.get("Revenue"), by_name.get("Net income")
    if rev and rev.change is not None:
        direction = "grew" if rev.change > 0 else "fell" if rev.change < 0 else "was flat"
        amount = f" {abs(rev.change):.1f}%" if rev.change else ""
        headline = f"{name} revenue {direction}{amount} year over year to {money(rev.current)} ({_lc(rev.period)})"
        if ni and ni.current is not None:
            headline += f", with net income of {money(ni.current)}" + (
                f" ({ni.change:+.1f}%)." if ni.change is not None else "."
            )
        else:
            headline += "."
    elif rev:
        headline = f"{name} reported revenue of {money(rev.current)} ({_lc(rev.period)})."
    else:
        headline = f"Standard financial figures for {name} are not available in its SEC filings."

    drivers = []
    for m in f.metrics:
        if m.change is None and m.unit == "usd" and m.current is not None and m.prior is not None and (m.current < 0) != (m.prior < 0):
            swing = "swung to a loss of" if m.current < 0 else "turned positive at"
            drivers.append(f"{m.name} {swing} {money(abs(m.current))}, from {money(m.prior)} a year earlier (GAAP).")
            continue
        if m.change is None:
            continue
        if m.unit == "pct":
            drivers.append(f"{m.name} {'widened' if m.change > 0 else 'narrowed' if m.change < 0 else 'held'} "
                           f"{abs(m.change):.1f} pp to {m.current:.1f}%.")
        elif m.name in ("Revenue", "Operating income", "Net income", "Free cash flow", "Diluted EPS"):
            value = f"${m.current:.2f}" if m.unit == "eps" else money(m.current)
            drivers.append(f"{m.name} {m.change:+.1f}% year over year to {value} (GAAP).")
    return headline, drivers[:5]


async def _get_json(client: httpx.AsyncClient, url: str, user_agent: str) -> dict:
    resp = await client.get(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    if resp.status_code == 404:
        raise CompanyNotFound(url)
    resp.raise_for_status()
    return resp.json()


async def lookup_cik(client: httpx.AsyncClient, symbol: str, user_agent: str, tickers: dict | None = None) -> tuple[str, str]:
    """(10-digit CIK, company name) for a ticker, from SEC's ticker list."""
    data = tickers if tickers is not None else await _get_json(client, SEC_TICKERS_URL, user_agent)
    wanted = {symbol.upper(), symbol.upper().replace(".", "-")}
    for row in data.values():
        if str(row.get("ticker", "")).upper() in wanted:
            return f"{int(row['cik_str']):010d}", row.get("title") or symbol
    raise CompanyNotFound(symbol)


def recent_filings(submissions: dict, cik: str, limit: int = 2) -> list[Filing]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    out: list[Filing] = []
    for i, form in enumerate(forms):
        if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
            continue
        accession = (recent.get("accessionNumber") or [""] * len(forms))[i].replace("-", "")
        document = (recent.get("primaryDocument") or [""] * len(forms))[i]
        url = (
            SEC_DOC_URL.format(cik_int=int(cik), accession=accession, document=document)
            if accession and document
            else SEC_FILING_INDEX_URL.format(cik=cik)
        )
        out.append(Filing(form, (recent.get("filingDate") or [""] * len(forms))[i],
                          (recent.get("reportDate") or [""] * len(forms))[i], url))
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Claude (optional): drivers, guidance and extra risks from figures + headlines
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = """You are an equity research analyst following a strict financial-report-analysis method.
You get a company's key figures (already extracted from its SEC filings, with year-over-year changes \
computed in code), red flags computed in code, its latest filings and recent news headlines.

Write:
- headline: one or two sentences on how the latest period went.
- drivers: 3 to 5 short bullets on what drove the results, using only the figures and headlines given.
- guidance: management guidance or outlook for the next period, only if a headline states it; \
otherwise say that guidance was not found in the data provided.
- risks: the most important risks and red flags, most severe first. Include the computed red flags \
that matter, and add risks the headlines show (lawsuits, regulation, guidance cuts, competition). \
Each risk has a short title, a one-sentence detail and a severity of high, medium or low.

Rules: every number you write must appear in the data given; never estimate. Label GAAP figures as GAAP. \
Give factual analysis only, with no buy, sell or hold recommendation."""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "drivers": {"type": "array", "items": {"type": "string"}},
        "guidance": {"type": "string"},
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title", "detail", "severity"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "drivers", "guidance", "risks"],
    "additionalProperties": False,
}


class ClaudeAnalyst:
    """Writes the narrative parts of the analysis with the Claude API."""

    def __init__(self, api_key: str, model: str = CLAUDE_MODEL) -> None:
        import anthropic  # imported lazily so the app runs without the package configured

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=90.0, max_retries=1)
        self.model = model

    async def __call__(self, payload: dict) -> dict | None:
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
                system=ANALYST_SYSTEM,
                messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            )
        except self._anthropic.APIError as exc:
            log.warning("Claude analysis failed for %s: %s", payload.get("symbol"), exc)
            return None
        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("Claude analysis for %s stopped: %s", payload.get("symbol"), response.stop_reason)
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Claude analysis for %s was not valid JSON", payload.get("symbol"))
            return None


def default_analyst() -> ClaudeAnalyst | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        return ClaudeAnalyst(key, os.getenv("RESEARCH_MODEL") or CLAUDE_MODEL)
    except Exception as exc:  # package missing or misconfigured: fall back to rules
        log.warning("Claude analyst unavailable: %s", exc)
        return None


def _clean_ai(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return None
    try:
        risks = [
            Risk(str(r["title"])[:120], str(r["detail"])[:400],
                 r["severity"] if r.get("severity") in SEVERITY_ORDER else "medium", "analysis")
            for r in result.get("risks") or []
        ]
        return {
            "headline": str(result.get("headline") or "")[:600],
            "drivers": [str(d)[:300] for d in (result.get("drivers") or [])][:5],
            "guidance": str(result.get("guidance") or "")[:600],
            "risks": risks,
        }
    except (KeyError, TypeError):
        return None


async def analyze(
    client: httpx.AsyncClient,
    symbol: str,
    *,
    user_agent: str,
    tickers: dict | None = None,
    headlines: list[dict] | None = None,
    price_change_pct: float | None = None,
    analyst=None,
) -> Analysis:
    """Run the full analysis for one company. Raises CompanyNotFound / ResearchUnavailable."""
    try:
        cik, name = await lookup_cik(client, symbol, user_agent, tickers)
        facts, submissions = await asyncio.gather(
            _get_json(client, SEC_FACTS_URL.format(cik=cik), user_agent),
            _get_json(client, SEC_SUBMISSIONS_URL.format(cik=cik), user_agent),
        )
    except CompanyNotFound:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise ResearchUnavailable(str(exc)) from exc

    name = facts.get("entityName") or submissions.get("name") or name
    fundamentals = extract_fundamentals(facts)
    risks = red_flags(fundamentals, price_change_pct)
    headline, drivers = rule_based_summary(name, fundamentals)
    guidance = "Guidance is not part of the structured filing data. Check the company's latest earnings release."
    filings = recent_filings(submissions, cik)
    period = fundamentals.metrics[0].period if fundamentals.metrics else ""

    analyst_kind = "rules"
    if analyst is not None:
        payload = {
            "symbol": symbol,
            "company": name,
            "metrics": [m.to_dict() for m in fundamentals.metrics],
            "computed_red_flags": [r.to_dict() for r in risks],
            "filings": [f.to_dict() for f in filings],
            "recent_headlines": [
                {"title": h.get("title"), "source": h.get("source"), "published": h.get("published")}
                for h in (headlines or [])[:12]
            ],
            "one_month_price_change_pct": price_change_pct,
        }
        ai = _clean_ai(await analyst(payload))
        if ai:
            analyst_kind = "claude"
            headline = ai["headline"] or headline
            drivers = ai["drivers"] or drivers
            guidance = ai["guidance"] or guidance
            # Claude's ranked risks first, then any computed red flag it didn't cover.
            seen = {r.title.lower() for r in ai["risks"]}
            risks = sort_risks(ai["risks"] + [r for r in risks if r.title.lower() not in seen])

    sources = [
        {"label": f"{f.form} filed {f.filed} (period {f.period})", "url": f.url} for f in filings
    ] + [{"label": "SEC XBRL company facts", "url": SEC_FACTS_URL.format(cik=cik)}]
    return Analysis(symbol, name, cik, headline, risks, fundamentals.metrics, drivers, guidance,
                    sources, analyst_kind, period, filings)
