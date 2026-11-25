"""Synthetic SEC EDGAR responses for tests. The numbers are made up, not real company results."""

from __future__ import annotations

# Ticker list in the shape of https://www.sec.gov/files/company_tickers.json
SEC_TICKERS = {
    str(i): {"cik_str": cik, "ticker": t, "title": title}
    for i, (cik, t, title) in enumerate([
        (320193, "AAPL", "Apple Inc."),
        (1326801, "META", "Meta Platforms, Inc."),
        (1045810, "NVDA", "NVIDIA CORP"),
        (6951, "AMAT", "APPLIED MATERIALS INC /DE"),
        (1730168, "AVGO", "Broadcom Inc."),
        (59478, "LLY", "ELI LILLY & Co"),
        (1652044, "GOOGL", "Alphabet Inc."),
        (789019, "MSFT", "MICROSOFT CORP"),
        (1318605, "TSLA", "Tesla, Inc."),
        (9999901, "LOSS", "Loss Making Corp"),
    ])
}

Q_CUR = ("2026-06-29", "2026-09-27")  # current quarter
Q_PRI = ("2025-06-29", "2025-09-27")  # same quarter a year earlier
Y_CUR = ("2025-09-28", "2026-09-27")  # fiscal year
Y_PRI = ("2024-09-29", "2025-09-27")


# Older periods, so every Portfolio period choice (prior quarter, 2 quarters, 2 and 5 years) has data.
# Each entry: (start, end, share of the current or prior value).
QUARTER_HISTORY = [
    ("2026-03-29", "2026-06-28", "cur", 0.95),  # prior quarter
    ("2025-12-28", "2026-03-28", "cur", 0.92),  # two quarters ago
    ("2024-06-30", "2024-09-28", "pri", 0.90),  # same quarter two years ago
    ("2021-06-27", "2021-09-25", "pri", 0.60),  # same quarter five years ago
]
YEAR_HISTORY = [  # annual lines: year-to-date pieces (for trailing twelve months) and older years
    ("2025-09-28", "2026-06-28", "cur", 0.74), ("2024-09-29", "2025-06-28", "pri", 0.73),
    ("2025-09-28", "2026-03-28", "cur", 0.49), ("2024-09-29", "2025-03-29", "pri", 0.48),
    ("2023-10-01", "2024-09-28", "pri", 0.90), ("2020-09-27", "2021-09-25", "pri", 0.60),
]
INSTANT_HISTORY = [("2026-06-28", "cur", 0.97), ("2026-03-28", "cur", 0.95), ("2024-09-28", "pri", 0.90), ("2021-09-25", "pri", 0.60)]


def _flow(cur, pri, period_cur=Q_CUR, period_pri=Q_PRI, unit="USD", filed="2026-10-30", form="10-K"):
    history = QUARTER_HISTORY if period_cur == Q_CUR else YEAR_HISTORY
    older = [
        {"start": start, "end": end, "val": round((cur if base == "cur" else pri) * share, 4), "form": "10-Q", "filed": "2026-08-01"}
        for start, end, base, share in history
    ]
    return {"units": {unit: older + [
        {"start": period_pri[0], "end": period_pri[1], "val": pri, "form": "10-K", "filed": "2025-10-31"},
        {"start": period_cur[0], "end": period_cur[1], "val": cur, "form": form, "filed": filed},
        # The prior year appears again in the newer filing as a comparative.
        {"start": period_pri[0], "end": period_pri[1], "val": pri, "form": form, "filed": filed},
    ]}}


def _instant(cur, pri):
    older = [{"end": end, "val": (cur if base == "cur" else pri) * share, "form": "10-Q", "filed": "2026-08-01"}
             for end, base, share in INSTANT_HISTORY]
    return {"units": {"USD": older + [
        {"end": Q_PRI[1], "val": pri, "form": "10-K", "filed": "2025-10-31"},
        {"end": Q_CUR[1], "val": cur, "form": "10-K", "filed": "2026-10-30"},
    ]}}


def company_facts(name: str = "Apple Inc.", *, revenue=(102.0e9, 94.0e9), net_income=(27.0e9, 24.0e9),
                  receivables=(39.0e9, 30.0e9), ocf=(110.0e9, 118.0e9), equity=(70.0e9, 65.0e9)) -> dict:
    """Company facts in the shape of data.sec.gov/api/xbrl/companyfacts. Defaults: growing revenue,
    receivables growing faster than revenue and cash flow falling while earnings rise (two red flags)."""
    return {
        "cik": 320193,
        "entityName": name,
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": _flow(*revenue),
            "GrossProfit": _flow(revenue[0] * 0.47, revenue[1] * 0.46),
            "OperatingIncomeLoss": _flow(revenue[0] * 0.31, revenue[1] * 0.30),
            "NetIncomeLoss": _flow(*net_income),
            "EarningsPerShareDiluted": _flow(1.85, 1.62, unit="USD/shares"),
            "NetCashProvidedByUsedInOperatingActivities": _flow(*ocf, period_cur=Y_CUR, period_pri=Y_PRI),
            "PaymentsToAcquirePropertyPlantAndEquipment": _flow(12.0e9, 9.5e9, period_cur=Y_CUR, period_pri=Y_PRI),
            "PaymentsForRepurchaseOfCommonStock": _flow(90.0e9, 95.0e9, period_cur=Y_CUR, period_pri=Y_PRI),
            "PaymentsOfDividends": _flow(15.4e9, 15.2e9, period_cur=Y_CUR, period_pri=Y_PRI),
            "CashAndCashEquivalentsAtCarryingValue": _instant(35.0e9, 29.9e9),
            "LongTermDebtNoncurrent": _instant(78.0e9, 85.0e9),
            "LongTermDebtCurrent": _instant(12.0e9, 10.9e9),
            "StockholdersEquity": _instant(*equity),
            "AccountsReceivableNetCurrent": _instant(*receivables),
        }},
    }


def submissions(name: str = "Apple Inc.") -> dict:
    return {
        "name": name,
        "filings": {"recent": {
            "form": ["8-K", "10-K", "4", "10-Q"],
            "filingDate": ["2026-10-31", "2026-10-30", "2026-10-15", "2026-08-01"],
            "reportDate": ["2026-10-30", "2026-09-27", "", "2026-06-28"],
            "accessionNumber": ["0000320193-26-000100", "0000320193-26-000099", "x", "0000320193-26-000070"],
            "primaryDocument": ["a8k.htm", "aapl-20260927.htm", "x.xml", "aapl-20260628.htm"],
        }},
    }
