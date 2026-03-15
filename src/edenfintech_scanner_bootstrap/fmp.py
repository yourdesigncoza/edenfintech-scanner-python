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

    def balance_sheet_statements(self, ticker: str, limit: int = 5) -> list[dict]:
        payload = self._get("balance-sheet-statement", symbol=ticker, limit=str(limit), period="annual")
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"FMP balance sheet response missing for {ticker}")
        return _sorted_desc(payload)

    def multi_quote(self, tickers: list[str]) -> dict[str, dict]:
        """Fetch quotes for multiple tickers using per-ticker quote calls.

        Uses the standard-tier quote endpoint (not premium batch-quote).
        Returns dict keyed by ticker symbol. Missing/errored tickers are omitted.
        """
        if not tickers:
            return {}
        result: dict[str, dict] = {}
        for ticker in tickers:
            try:
                result[ticker] = self.quote(ticker)
            except Exception:
                pass
        return result

    def batch_quote(self, tickers: list[str]) -> dict[str, dict]:
        """Deprecated: use multi_quote() instead. batch-quote is a premium endpoint."""
        return self.multi_quote(tickers)

    def stock_screener(self, sector: str, exchange: str = "NYSE", **filters: str) -> list[dict]:
        params = {"sector": sector, "exchange": exchange, "isActivelyTrading": "true", **filters}
        payload = self._get("company-screener", **params)
        if not isinstance(payload, list):
            raise RuntimeError(f"FMP screener response malformed for sector={sector}")
        return payload

    def stock_peers(self, ticker: str) -> list[str]:
        """Return peer ticker symbols from FMP /stock-peers endpoint."""
        payload = self._get("stock-peers", symbol=ticker)
        if not isinstance(payload, list):
            return []
        peers: list[str] = []
        for item in payload:
            if isinstance(item, dict):
                # Format A: [{symbol: "PYPL", peersList: ["V", "MA", ...]}]
                peer_list = item.get("peersList")
                if isinstance(peer_list, list) and peer_list:
                    peers.extend(str(p) for p in peer_list if p and str(p) != ticker)
                else:
                    # Format B (stable): [{symbol: "DB", companyName: ..., ...}, ...]
                    sym = item.get("symbol") or item.get("peerSymbol", "")
                    if sym and sym != ticker:
                        peers.append(str(sym))
            elif isinstance(item, str) and item != ticker:
                peers.append(item)
        return list(dict.fromkeys(peers))[:5]

    def key_metrics_ttm(self, ticker: str) -> dict:
        """Fetch trailing-twelve-month key metrics for a single ticker."""
        payload = self._get("key-metrics-ttm", symbol=ticker)
        if isinstance(payload, list) and payload:
            return payload[0]
        if isinstance(payload, dict):
            return payload
        return {}

    def peer_metrics(self, tickers: list[str], target_mkt_cap: float | None = None) -> list[dict]:
        """Fetch comparison metrics for a list of peer tickers.

        Uses multi_quote (1 call, standard tier) instead of per-peer quote calls.
        Skips historical_prices for peers (pct_off_ath derived from quote data).
        Filters out peers with market cap >10x or <0.1x of target_mkt_cap.
        Returns list[dict] with ticker + metrics. Missing data = None.
        """
        if not tickers:
            return []

        # Single call for all peer quotes (standard-tier comma-separated)
        quotes = self.multi_quote(tickers)

        # Pre-filter by market cap before expensive per-peer calls
        eligible: list[str] = []
        for ticker in tickers:
            quote = quotes.get(ticker)
            if not quote:
                continue
            mkt_cap = float(quote.get("marketCap", 0) or 0)
            if target_mkt_cap and target_mkt_cap > 0:
                if mkt_cap > target_mkt_cap * 10 or mkt_cap < target_mkt_cap * 0.1:
                    continue
            eligible.append(ticker)

        results: list[dict] = []
        for ticker in eligible:
            try:
                quote = quotes[ticker]
                km = self.key_metrics_ttm(ticker)
                income = self.income_statements(ticker, limit=5)
                cashflows = self.cash_flow_statements(ticker, limit=5)

                # Revenue and CAGR
                rev_history = _revenue_history_billions(income)
                latest_rev = rev_history[0]["revenue_b"] if rev_history else None
                rev_cagr_3yr = None
                if len(rev_history) >= 4 and rev_history[-1]["revenue_b"] and rev_history[-1]["revenue_b"] > 0:
                    oldest = rev_history[min(3, len(rev_history) - 1)]["revenue_b"]
                    if oldest > 0 and latest_rev:
                        rev_cagr_3yr = _round2(((latest_rev / oldest) ** (1 / 3) - 1) * 100)

                # FCF margin
                fcf_history = _fcf_margin_history_pct(income, cashflows)
                latest_fcf = fcf_history[0]["fcf_margin_pct"] if fcf_history else None
                margin_trend = None
                if len(fcf_history) >= 3:
                    recent_avg = sum(h["fcf_margin_pct"] for h in fcf_history[:2]) / 2
                    older_avg = sum(h["fcf_margin_pct"] for h in fcf_history[2:4]) / max(len(fcf_history[2:4]), 1)
                    if recent_avg > older_avg + 1:
                        margin_trend = "improving"
                    elif recent_avg < older_avg - 1:
                        margin_trend = "declining"
                    else:
                        margin_trend = "stable"

                # ROIC, D/E from key metrics
                roic = km.get("roicTTM")
                if isinstance(roic, (int, float)):
                    roic = _round2(float(roic) * 100)
                else:
                    roic = None
                debt_to_equity = km.get("debtToEquityTTM")
                if isinstance(debt_to_equity, (int, float)):
                    debt_to_equity = _round2(float(debt_to_equity))
                else:
                    debt_to_equity = None

                # pct_off_ath from quote (avoids historical_prices call)
                price = float(quote.get("price", 0) or 0)
                year_high = float(quote.get("yearHigh", 0) or 0)
                pct_off = _pct_off_ath(price, year_high) if year_high > 0 and price > 0 else None

                # Dilution (shares growth 3yr)
                shares_growth = None
                if len(income) >= 4:
                    latest_shares = income[0].get("weightedAverageShsOutDil")
                    oldest_shares = income[min(3, len(income) - 1)].get("weightedAverageShsOutDil")
                    if isinstance(latest_shares, (int, float)) and isinstance(oldest_shares, (int, float)) and oldest_shares > 0:
                        shares_growth = _round2(((latest_shares / oldest_shares) ** (1 / 3) - 1) * 100)

                results.append({
                    "ticker": ticker,
                    "latest_revenue_b": latest_rev,
                    "revenue_cagr_3yr": rev_cagr_3yr,
                    "latest_fcf_margin_pct": latest_fcf,
                    "margin_trend": margin_trend,
                    "roic_pct": roic,
                    "debt_to_equity": debt_to_equity,
                    "pct_off_ath": pct_off,
                    "shares_growth_3yr_pct": shares_growth,
                })
            except Exception:
                results.append({
                    "ticker": ticker,
                    "latest_revenue_b": None,
                    "revenue_cagr_3yr": None,
                    "latest_fcf_margin_pct": None,
                    "margin_trend": None,
                    "roic_pct": None,
                    "debt_to_equity": None,
                    "pct_off_ath": None,
                    "shares_growth_3yr_pct": None,
                })
        return results


def _compute_trailing_ratios(
    income_statements: list[dict],
    cash_flows: list[dict],
    balance_sheets: list[dict],
) -> dict:
    """Compute anonymous trailing ratios from financial statements.

    Returns only computed float ratios — no raw dollar amounts, no prices.
    Safe to pass through the epistemic information barrier.
    """
    latest_inc = income_statements[0] if income_statements else {}
    latest_cf = cash_flows[0] if cash_flows else {}
    latest_bs = balance_sheets[0] if balance_sheets else {}

    revenue = float(latest_inc.get("revenue", 0) or 0)
    ebit = float(latest_inc.get("operatingIncome", 0) or 0)
    interest = float(latest_inc.get("interestExpense", 0) or 0)
    ebitda = float(latest_inc.get("ebitda", 0) or 0)
    net_income = float(latest_inc.get("netIncome", 0) or 0)
    has_continuing_ops = "netIncomeFromContinuingOperations" in latest_inc
    ocf = float(latest_cf.get("operatingCashFlow", 0) or 0)
    fcf = float(latest_cf.get("freeCashFlow", 0) or 0)
    total_debt = float(latest_bs.get("totalDebt", 0) or 0)
    total_equity = float(latest_bs.get("totalStockholdersEquity", 0) or 0)
    current_assets = float(latest_bs.get("totalCurrentAssets", 0) or 0)
    current_liabilities = float(latest_bs.get("totalCurrentLiabilities", 0) or 0)

    # Discontinued operations gap detection
    discontinued_ops_flag = None
    if has_continuing_ops:
        continuing_ops = float(latest_inc.get("netIncomeFromContinuingOperations", 0) or 0)
        if continuing_ops != 0 or net_income != 0:
            gap = abs(net_income - continuing_ops)
            denominator = max(abs(net_income), 1)
            if gap / denominator > 0.15:
                discontinued_ops_flag = True
            else:
                discontinued_ops_flag = False

    return {
        "interest_coverage": round(ebit / interest, 2) if interest else None,
        "debt_to_equity": round(total_debt / total_equity, 2) if total_equity else None,
        "current_ratio": round(current_assets / current_liabilities, 2) if current_liabilities else None,
        "fcf_margin_pct": round(fcf / revenue * 100, 2) if revenue else None,
        "ocf_margin_pct": round(ocf / revenue * 100, 2) if revenue else None,
        "ebitda_margin_pct": round(ebitda / revenue * 100, 2) if revenue else None,
        "net_margin_pct": round(net_income / revenue * 100, 2) if revenue else None,
        "discontinued_ops_flag": discontinued_ops_flag,
    }


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


def _revenue_history_billions(income_statements: list[dict], *, exclude_years: set[str] | None = None) -> list[dict]:
    history: list[dict] = []
    for statement in _sorted_desc(income_statements):
        revenue = statement.get("revenue")
        year = _year_from_date(statement.get("date"))
        if exclude_years and year in exclude_years:
            continue
        if isinstance(revenue, (int, float)):
            history.append(
                {
                    "date": statement.get("date"),
                    "revenue_b": _round4(float(revenue) / 1_000_000_000),
                }
            )
    return history


def _fcf_margin_history_pct(income_statements: list[dict], cash_flow_statements: list[dict], *, exclude_years: set[str] | None = None) -> list[dict]:
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
        year = _year_from_date(cashflow_date)
        if exclude_years and year in exclude_years:
            continue
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


def _check_statement_completeness(
    income_statements: list[dict],
    cash_flows: list[dict],
    balance_sheets: list[dict],
    *,
    is_actively_trading: bool = True,
) -> dict:
    """Detect zero-filled/incomplete financial statements.

    Uses structural invariants (not field-count density) to flag
    statements where FMP returned placeholder zeros.
    """
    warnings: list[dict] = []
    incomplete_years: list[str] = []

    for cf in cash_flows:
        year = _year_from_date(cf.get("date"))
        ocf = float(cf.get("operatingCashFlow", 0) or 0)
        capex = float(cf.get("capitalExpenditure", 0) or 0)
        cash_end = float(cf.get("cashAtEndOfPeriod", 0) or 0)
        if ocf == 0 and capex == 0 and cash_end > 0:
            warnings.append({
                "statement": "cash_flow",
                "fiscal_year": year,
                "reason": "operatingCashFlow=0 AND capitalExpenditure=0 but cashAtEndOfPeriod>0",
            })
            if year and year not in incomplete_years:
                incomplete_years.append(year)

    for inc in income_statements:
        year = _year_from_date(inc.get("date"))
        revenue = float(inc.get("revenue", 0) or 0)
        op_expenses = float(inc.get("operatingExpenses", 0) or 0)
        net_income = float(inc.get("netIncome", 0) or 0)
        cogs = float(inc.get("costOfRevenue", 0) or 0)
        gross_profit = float(inc.get("grossProfit", 0) or 0)
        if revenue > 0 and op_expenses == 0 and net_income == 0:
            warnings.append({
                "statement": "income",
                "fiscal_year": year,
                "reason": "revenue>0 AND operatingExpenses=0 AND netIncome=0",
            })
            if year and year not in incomplete_years:
                incomplete_years.append(year)
        if revenue > 0 and cogs == 0 and gross_profit == 0:
            warnings.append({
                "statement": "income",
                "fiscal_year": year,
                "reason": "revenue>0 AND costOfRevenue=0 AND grossProfit=0",
            })
            if year and year not in incomplete_years:
                incomplete_years.append(year)

    for bs in balance_sheets:
        year = _year_from_date(bs.get("date"))
        total_assets = float(bs.get("totalAssets", 0) or 0)
        total_liab_eq = float(bs.get("totalLiabilitiesAndTotalEquity", 0) or 0)
        if total_assets > 0 and total_liab_eq == 0:
            warnings.append({
                "statement": "balance_sheet",
                "fiscal_year": year,
                "reason": "totalAssets>0 but totalLiabilitiesAndTotalEquity=0",
            })
            if year and year not in incomplete_years:
                incomplete_years.append(year)
        if total_assets == 0 and is_actively_trading:
            warnings.append({
                "statement": "balance_sheet",
                "fiscal_year": year,
                "reason": "totalAssets=0 while company is actively trading",
            })
            if year and year not in incomplete_years:
                incomplete_years.append(year)

    return {
        "has_incomplete_statements": len(incomplete_years) > 0,
        "incomplete_years": incomplete_years,
        "warnings": warnings,
    }


def build_raw_candidate_from_fmp(ticker: str, client: FmpClient) -> dict:
    profile = client.profile(ticker)
    quote = client.quote(ticker)
    historical_prices = client.historical_prices(ticker)
    income_statements = client.income_statements(ticker)
    cash_flows = client.cash_flow_statements(ticker)
    balance_sheets = client.balance_sheet_statements(ticker)

    current_price = float(quote["price"])
    numeric_closes = [float(item["close"]) for item in historical_prices if isinstance(item.get("close"), (int, float))]
    if not numeric_closes:
        raise RuntimeError(f"FMP historical prices did not contain usable close data for {ticker}")
    all_time_high = max(numeric_closes)
    is_actively_trading = profile.get("isActivelyTrading", True)
    data_quality = _check_statement_completeness(
        income_statements, cash_flows, balance_sheets,
        is_actively_trading=is_actively_trading,
    )
    exclude_years = set(data_quality["incomplete_years"])
    revenue_history = _revenue_history_billions(income_statements, exclude_years=exclude_years)
    fcf_history = _fcf_margin_history_pct(income_statements, cash_flows, exclude_years=exclude_years)
    shares_m = _shares_millions(income_statements)
    trailing_ratios = _compute_trailing_ratios(income_statements, cash_flows, balance_sheets)
    # Merge A2/A3 flags into data_quality
    data_quality["discontinued_ops_flag"] = trailing_ratios.get("discontinued_ops_flag")
    data_quality["is_actively_trading"] = profile.get("isActivelyTrading", True)

    latest_revenue_b = revenue_history[0]["revenue_b"] if revenue_history else None
    trough_revenue_b = min(item["revenue_b"] for item in revenue_history) if revenue_history else None
    latest_fcf_margin_pct = fcf_history[0]["fcf_margin_pct"] if fcf_history else None
    trough_fcf_margin_pct = min(item["fcf_margin_pct"] for item in fcf_history) if fcf_history else None

    return {
        "ticker": ticker,
        "cluster_name": f"{ticker.lower()}-cluster",
        "industry": profile.get("industry", "Unknown Industry"),
        "is_actively_trading": profile.get("isActivelyTrading", True),
        "company_description": profile.get("description", ""),
        "current_price": _round2(current_price),
        "trailing_ratios": trailing_ratios,
        "market_snapshot": {
            "current_price": _round2(current_price),
            "all_time_high": _round2(all_time_high),
            "pct_off_ath": _pct_off_ath(current_price, all_time_high),
        },
        "data_quality": data_quality,
        "fmp_context": {
            "profile": profile,
            "quote": quote,
            "annual_income_statements": income_statements,
            "annual_cash_flows": cash_flows,
            "annual_balance_sheets": balance_sheets,
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
