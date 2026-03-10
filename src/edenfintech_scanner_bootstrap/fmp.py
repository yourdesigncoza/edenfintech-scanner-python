from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable
from urllib import error, parse, request

from .config import AppConfig, load_config


FmpTransport = Callable[[str, dict[str, str]], list[dict] | dict]


def _round2(value: float) -> float:
    return round(value, 2)


def _round4(value: float) -> float:
    return round(value, 4)


def _statement_sort_key(item: dict) -> tuple[int, str]:
    raw_date = item.get("date")
    if not isinstance(raw_date, str):
        return (0, "")
    return (1, raw_date)


def _sorted_desc(items: list[dict]) -> list[dict]:
    return sorted(items, key=_statement_sort_key, reverse=True)


def _year_from_date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 4:
        return None
    return value[:4]


def _default_transport(endpoint: str, params: dict[str, str]) -> list[dict] | dict:
    query = parse.urlencode(params)
    url = f"https://financialmodelingprep.com/stable/{endpoint}?{query}"
    http_request = request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        body_preview = body.strip().replace("\n", " ")
        if len(body_preview) > 200:
            body_preview = f"{body_preview[:200]}..."
        raise RuntimeError(f"FMP request failed for {endpoint}: HTTP {exc.code}; {body_preview}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"FMP request failed for {endpoint}: {exc}") from exc


class FmpClient:
    def __init__(self, api_key: str, transport: FmpTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport or _default_transport

    def _get(self, endpoint: str, **params: str) -> list[dict] | dict:
        payload = self.transport(endpoint, {"apikey": self.api_key, **params})
        if isinstance(payload, dict) and payload.get("Error Message"):
            raise RuntimeError(f"FMP returned an error for {endpoint}: {payload['Error Message']}")
        return payload

    def quote(self, ticker: str) -> dict:
        payload = self._get("quote", symbol=ticker)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"FMP quote response missing for {ticker}")
        return payload[0]

    def profile(self, ticker: str) -> dict:
        payload = self._get("profile", symbol=ticker)
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"FMP profile response missing for {ticker}")
        return payload[0]

    def historical_prices(self, ticker: str) -> list[dict]:
        payload = self._get("historical-price-eod/full", symbol=ticker)
        if isinstance(payload, list):
            historical = payload
        elif isinstance(payload, dict) and "historical" in payload:
            historical = payload["historical"]
        else:
            raise RuntimeError(f"FMP historical price response missing for {ticker}")
        if not isinstance(historical, list):
            raise RuntimeError(f"FMP historical price response malformed for {ticker}")
        return historical

    def income_statements(self, ticker: str, limit: int = 5) -> list[dict]:
        payload = self._get("income-statement", symbol=ticker, limit=str(limit), period="annual")
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"FMP income statement response missing for {ticker}")
        return _sorted_desc(payload)

    def cash_flow_statements(self, ticker: str, limit: int = 5) -> list[dict]:
        payload = self._get("cash-flow-statement", symbol=ticker, limit=str(limit), period="annual")
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"FMP cash flow response missing for {ticker}")
        return _sorted_desc(payload)

    def stock_screener(self, sector: str, exchange: str = "NYSE", **filters: str) -> list[dict]:
        params = {"sector": sector, "exchange": exchange, **filters}
        payload = self._get("stock-screener", **params)
        if not isinstance(payload, list):
            raise RuntimeError(f"FMP screener response malformed for sector={sector}")
        return payload


def _pct_off_ath(current_price: float, all_time_high: float) -> float:
    if all_time_high <= 0:
        raise ValueError("all_time_high must be positive")
    return _round2(max(0.0, ((all_time_high - current_price) / all_time_high) * 100))


def _shares_millions(income_statements: list[dict]) -> float:
    for statement in _sorted_desc(income_statements):
        shares = statement.get("weightedAverageShsOutDil") or statement.get("weightedAverageShsOut")
        if isinstance(shares, (int, float)) and shares > 0:
            return _round4(float(shares) / 1_000_000)
    raise RuntimeError("FMP income statement did not contain usable share-count data")


def _revenue_history_billions(income_statements: list[dict]) -> list[dict]:
    history: list[dict] = []
    for statement in _sorted_desc(income_statements):
        revenue = statement.get("revenue")
        if isinstance(revenue, (int, float)):
            history.append(
                {
                    "date": statement.get("date"),
                    "revenue_b": _round4(float(revenue) / 1_000_000_000),
                }
            )
    return history


def _fcf_margin_history_pct(income_statements: list[dict], cash_flow_statements: list[dict]) -> list[dict]:
    sorted_income = _sorted_desc(income_statements)
    sorted_cashflows = _sorted_desc(cash_flow_statements)
    income_by_date = {statement.get("date"): statement for statement in sorted_income if isinstance(statement.get("date"), str)}
    income_by_year = {
        _year_from_date(statement.get("date")): statement
        for statement in sorted_income
        if _year_from_date(statement.get("date")) is not None
    }
    history: list[dict] = []
    for cashflow in sorted_cashflows:
        cashflow_date = cashflow.get("date")
        statement = income_by_date.get(cashflow_date)
        if statement is None:
            statement = income_by_year.get(_year_from_date(cashflow_date))
        if statement is None:
            continue
        revenue = statement.get("revenue")
        free_cash_flow = cashflow.get("freeCashFlow")
        if not isinstance(revenue, (int, float)) or not isinstance(free_cash_flow, (int, float)) or revenue == 0:
            continue
        history.append(
            {
                "date": cashflow.get("date"),
                "fcf_margin_pct": _round2((float(free_cash_flow) / float(revenue)) * 100),
            }
        )
    return history


def build_raw_candidate_from_fmp(ticker: str, client: FmpClient) -> dict:
    profile = client.profile(ticker)
    quote = client.quote(ticker)
    historical_prices = client.historical_prices(ticker)
    income_statements = client.income_statements(ticker)
    cash_flows = client.cash_flow_statements(ticker)

    current_price = float(quote["price"])
    numeric_closes = [float(item["close"]) for item in historical_prices if isinstance(item.get("close"), (int, float))]
    if not numeric_closes:
        raise RuntimeError(f"FMP historical prices did not contain usable close data for {ticker}")
    all_time_high = max(numeric_closes)
    revenue_history = _revenue_history_billions(income_statements)
    fcf_history = _fcf_margin_history_pct(income_statements, cash_flows)
    shares_m = _shares_millions(income_statements)

    latest_revenue_b = revenue_history[0]["revenue_b"] if revenue_history else None
    trough_revenue_b = min(item["revenue_b"] for item in revenue_history) if revenue_history else None
    latest_fcf_margin_pct = fcf_history[0]["fcf_margin_pct"] if fcf_history else None
    trough_fcf_margin_pct = min(item["fcf_margin_pct"] for item in fcf_history) if fcf_history else None

    return {
        "ticker": ticker,
        "cluster_name": f"{ticker.lower()}-cluster",
        "industry": profile.get("industry", "Unknown Industry"),
        "current_price": _round2(current_price),
        "market_snapshot": {
            "current_price": _round2(current_price),
            "all_time_high": _round2(all_time_high),
            "pct_off_ath": _pct_off_ath(current_price, all_time_high),
        },
        "fmp_context": {
            "profile": profile,
            "quote": quote,
            "annual_income_statements": income_statements,
            "annual_cash_flows": cash_flows,
            "derived": {
                "revenue_history_b": revenue_history,
                "fcf_margin_history_pct": fcf_history,
                "shares_m_latest": shares_m,
                "latest_revenue_b": latest_revenue_b,
                "trough_revenue_b": trough_revenue_b,
                "latest_fcf_margin_pct": latest_fcf_margin_pct,
                "trough_fcf_margin_pct": trough_fcf_margin_pct,
            },
        },
    }


def build_fmp_bundle(
    tickers: list[str],
    *,
    client: FmpClient,
    scan_mode: str = "specific_tickers",
    focus: str | None = None,
) -> dict:
    if not tickers:
        raise ValueError("tickers must not be empty")

    raw_candidates = [build_raw_candidate_from_fmp(ticker, client) for ticker in tickers]
    return {
        "title": f"EdenFinTech FMP Raw Bundle - {', '.join(tickers)}",
        "scan_date": str(date.today()),
        "version": "v1",
        "scan_parameters": {
            "scan_mode": scan_mode,
            "focus": focus or ", ".join(tickers),
            "api": "Financial Modeling Prep",
        },
        "portfolio_context": {
            "current_positions": 0,
            "max_positions": 12,
        },
        "methodology_notes": [
            "This bundle was fetched from FMP and contains deterministic market and financial inputs only.",
            "Add screening_inputs, analysis_inputs, and epistemic_inputs before running build-scan-input.",
        ],
        "raw_candidates": raw_candidates,
    }


def build_fmp_bundle_with_config(
    tickers: list[str],
    *,
    config: AppConfig | None = None,
    transport: FmpTransport | None = None,
) -> dict:
    app_config = config or load_config()
    app_config.require("fmp_api_key")
    client = FmpClient(app_config.fmp_api_key, transport=transport)
    return build_fmp_bundle(tickers, client=client)


def write_fmp_bundle(path: Path, bundle: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2))
