"""
End-to-end pipeline:  provider -> models -> weekly indicator panel -> scores -> pillars -> regime.

    python -m sysrisk.pipeline --source free      # Yahoo + FRED
    python -m sysrisk.pipeline --source bbg       # Bloomberg + FRED
    python -m sysrisk.pipeline --source demo      # synthetic, offline

Writes results to ./output/*.csv and a pickle the Streamlit app loads.
"""
from __future__ import annotations

import argparse
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import models as M
from .config import (DY_PANEL, FIN_UNIVERSE, FRED_SERIES, MARKET_PROXY, PILLARS, REGISTRY,
                     SYSTEM_PROXY)


@dataclass
class Params:
    start: str = "2003-01-01"
    covar_q: float = 0.05
    srisk_k: float = 0.08
    srisk_crash: float = 0.40
    dy_window: int = 200
    dy_lags: int = 2
    dy_horizon: int = 10
    ar_window: int = 500
    dgc_window: int = 36
    hp_lambda: float = 400_000
    pct_min_weeks: int = 156        # 3y of history before a percentile score is reported
    regime_cut: float = 60.0
    sectors: list = field(default_factory=lambda: list(FIN_UNIVERSE))


def _weekly(s: pd.Series | pd.DataFrame, lag_days: int = 0, limit: int | None = 26):
    """Shift by publication lag, sample to Friday weeks, forward fill (bounded) - no look-ahead."""
    x = s.copy()
    if lag_days:
        x.index = x.index + pd.Timedelta(days=lag_days)
    return x.resample("W-FRI").last().ffill(limit=limit)


def get_provider(source: str):
    from . import data
    return {"free": data.FreeProvider, "bbg": data.BloombergProvider,
            "demo": data.SyntheticProvider}[source]()


def run(provider, p: Params = Params(), log=print) -> dict:
    t0 = time.time()
    R = {"meta": {"source": provider.name, "run_at": pd.Timestamp.now(tz="Asia/Singapore"), "params": dict(vars(p))}}

    # ---------------------------------------------------------------- data
    fin_tickers = sorted({t for s in p.sectors for t in FIN_UNIVERSE[s]})
    eq_tickers = sorted(set(fin_tickers) | set(DY_PANEL.values()) | {MARKET_PROXY, SYSTEM_PROXY, "^VIX"})
    log(f"[data] {len(eq_tickers)} equities/ETFs from {provider.name}")
    px = provider.ohlc(eq_tickers, p.start)
    last_day = px["close"][MARKET_PROXY].last_valid_index()          # drop today's partial row
    px = {k: v.loc[:last_day] for k, v in px.items()}
    close = px["close"].ffill(limit=3)
    rets = close.pct_change(fill_method=None)
    log(f"[data] {len(FRED_SERIES)} FRED series")
    fred = provider.fred(FRED_SERIES, "1960-01-01")
    R["fred"] = fred
    cap, liab = provider.fundamentals(fin_tickers, p.start)

    # ---------------------------------------------------------------- B. amplifiers
    # sector baskets: equal-weight daily returns
    baskets = pd.DataFrame({s: rets[[t for t in FIN_UNIVERSE[s] if t in rets]].mean(axis=1)
                            for s in p.sectors})

    log("[model] MES / LRMES / SRISK")
    beta = M.ewma_beta(rets[fin_tickers], rets[MARKET_PROXY])
    lrmes = M.lrmes_from_beta(beta, p.srisk_crash)
    sr = M.srisk(cap, liab, lrmes, p.srisk_k)
    first_liab = liab.apply(lambda c: c.first_valid_index())
    backfilled = pd.DataFrame({c: sr.index < first_liab[c] for c in sr.columns}, index=sr.index)
    sr = sr.where(~backfilled)        # only use dates with reported balance sheets; no back-filling
    sr_pos = sr.clip(lower=0)
    sector_of = {t: s for s in p.sectors for t in FIN_UNIVERSE[s]}
    R["srisk_sector"] = sr_pos.T.groupby(sector_of).sum(min_count=1).T / 1e9          # USD bn
    R["srisk_total"] = sr_pos.sum(axis=1, min_count=1) / 1e9
    R["srisk_coverage"] = sr.notna().sum(axis=1)
    R["srisk_backfilled_share"] = backfilled.mean(axis=1)
    last = sr.dropna(how="all").index[-1]
    R["srisk_firm"] = pd.DataFrame({
        "sector": pd.Series(sector_of), "SRISK $bn": sr.loc[last] / 1e9,
        "LRMES %": lrmes.loc[last] * 100, "beta": beta.loc[last],
        "Mkt cap $bn": cap.reindex([last]).iloc[0] / 1e9,
        "Book lev (D+W)/W": (liab.reindex(sr.index).ffill().loc[last] + cap.loc[last]) / cap.loc[last],
        "backfilled liab": backfilled.loc[last]}).sort_values("SRISK $bn", ascending=False)
    R["mes_tail"] = M.tail_mes(baskets, rets[MARKET_PROXY])

    gdp_nom = fred["GDP"].dropna()                                            # USD bn, SAAR
    gdp_d = gdp_nom.reindex(R["srisk_total"].index, method="ffill")
    R["srisk_gdp"] = (R["srisk_total"] / gdp_d * 100).rename("SRISK % GDP")

    log("[model] dCoVaR (expanding quantile regressions)")
    wk_ret = (1 + rets).resample("W-FRI").prod() - 1
    wk_b = (1 + baskets.fillna(0)).resample("W-FRI").prod() - 1
    state = pd.concat({
        "VIX": close["^VIX"].resample("W-FRI").last().diff() if "^VIX" in close else None,
        "Term": fred["T10Y3M"].resample("W-FRI").last().diff(),
        "Credit": fred["BAA10Y"].resample("W-FRI").last().diff(),
        "Mkt": wk_ret[MARKET_PROXY],
    }, axis=1).dropna()
    dco = {}
    for s in p.sectors:
        try:
            dco[s] = M.delta_covar(wk_b[s], wk_ret[SYSTEM_PROXY], state, q=p.covar_q)["dCoVaR"]
        except Exception as e:
            log(f"   dCoVaR {s} failed: {e}")
    R["dcovar"] = pd.DataFrame(dco)
    pc = [s for s in ["Alt managers", "BDCs"] if s in R["dcovar"]]
    R["dcovar_pc"] = R["dcovar"][pc].mean(axis=1) if pc else pd.Series(dtype=float)

    log("[model] Diebold-Yilmaz connectedness")
    inv = {v: k for k, v in DY_PANEL.items()}
    vol = M.parkinson_vol(px["high"][list(DY_PANEL.values())], px["low"][list(DY_PANEL.values())]).rename(columns=inv)
    vol = vol.replace([np.inf, -np.inf], np.nan).dropna()
    R["dy"] = M.diebold_yilmaz(vol, p.dy_window, p.dy_lags, p.dy_horizon)

    log("[model] Absorption ratio")
    R["ar"] = M.absorption_ratio(rets[fin_tickers].dropna(how="all"), p.ar_window)

    log("[model] Granger network")
    mret = (1 + baskets.fillna(0)).resample("ME").prod() - 1
    R["granger"] = M.granger_dgc(mret, p.dgc_window)

    # ---------------------------------------------------------------- A. build-up
    log("[model] credit gap, R-zone, Growth-at-Risk")
    cr = fred["QUSPAM770A"].dropna()
    R["credit_gap"] = M.credit_gap(cr, p.hp_lambda)
    eq_q = close[MARKET_PROXY].resample("QE").last()
    hpi = fred["CSUSHPINSA"].resample("QE").last()
    cr_q = cr.copy(); cr_q.index = cr_q.index.to_period("Q").to_timestamp("Q")
    R["rzone"] = M.rzone(cr_q, pd.concat({"Equity": eq_q, "Housing": hpi}, axis=1).reindex(cr_q.index))
    gdpr = fred["GDPC1"].dropna(); gdpr.index = gdpr.index.to_period("Q").to_timestamp("Q")
    nfci_q = fred["NFCI"].resample("QE").mean()
    R["gar"] = M.growth_at_risk(gdpr, nfci_q.reindex(gdpr.index))
    # BCNSDODNS is USD mn, GDP is USD bn (SAAR)
    corp = (fred["BCNSDODNS"].dropna() / 1e3 / fred["GDP"].reindex(fred["BCNSDODNS"].dropna().index) * 100)

    # ---------------------------------------------------------------- C. plumbing
    ior = pd.concat([fred["IOER"].dropna(), fred["IORB"].dropna()]).sort_index()
    ior = ior[~ior.index.duplicated(keep="last")]
    sofr = fred["SOFR"].dropna()
    sofr_iorb = (sofr - ior.reindex(sofr.index, method="ffill")) * 100
    cp = (fred["DCPF3M"] - fred["DTB3"]).dropna() * 100
    rel = (close["KRE"] / close["SPY"]).dropna()
    kre_dd = -(rel / rel.rolling(252, min_periods=60).max() - 1) * 100

    # ---------------------------------------------------------------- gap-filling indicators (lit review v2)
    gspc = provider.ohlc([MARKET_PROXY], "1990-01-01")["close"][MARKET_PROXY].dropna()
    rv = gspc.pct_change().rolling(252).std() * np.sqrt(252) * 100
    low_vol = (rv.rolling(1260).mean() - rv) / rv.rolling(1260).mean() * 100     # % below 5y average
    dealer_lev = (fred["BOGZ1FL664090005Q"] / fred["BOGZ1FL665080003Q"]).dropna()
    usd6m = fred["DTWEXBGS"].dropna().pct_change(126) * 100
    pcrel = (close["BIZD"] / close["HYG"]).dropna()
    pc_mark = -(pcrel / pcrel.rolling(252, min_periods=60).max() - 1) * 100
    # valuation, volatility, curve (v3: market-top signals folded in)
    from scipy.stats import norm
    xt = provider.ohlc(["^MOVE", "DX-Y.NYB", "EMB"], "2003-01-01")["close"].loc[:last_day]
    hp = M.credit_gap(np.log(fred["QUSR628BIS"].dropna()) * 100, p.hp_lambda)["gap"]          # % above trend
    gdp_q = fred["GDP"].dropna()
    eqv = fred["NCBEILQ027S"].dropna()
    eq_val = (eqv / 1e3 / gdp_q.reindex(eqv.index) * 100).dropna()
    margin = (fred["BOGZ1FL663067003Q"].dropna() / eqv * 100).dropna()
    r_sb = close[["SPY", "IEF"]].pct_change(fill_method=None)
    sb_corr = r_sb["SPY"].rolling(63).corr(r_sb["IEF"])
    credit_widen = fred["BAA10Y"].dropna().resample("W-FRI").last().diff(13)
    fx_vol = xt["DX-Y.NYB"].dropna().pct_change().rolling(21).std() * np.sqrt(252) * 100
    emrel = (xt["EMB"] / close["IEF"]).dropna()
    em_stress = -(emrel / emrel.rolling(252, min_periods=60).max() - 1) * 100
    t10y3m_m = fred["T10Y3M"].dropna().resample("ME").mean()
    rec_prob = pd.Series(norm.cdf(-0.5333 - 0.6330 * t10y3m_m) * 100, index=t10y3m_m.index)
    R["extra"] = {"rv": rv, "low_vol": low_vol, "dealer_lev": dealer_lev, "usd6m": usd6m, "pc_mark": pc_mark,
                  "house_gap": hp, "eq_val": eq_val, "move": xt["^MOVE"].dropna(), "rec_prob": rec_prob}

    # ---------------------------------------------------------------- weekly panel
    raw = {
        "credit_gap": _weekly(R["credit_gap"]["gap"], 120, None),
        "rzone": _weekly(R["rzone"]["rzone"], 120, None),
        "ebp_sentiment": _weekly(fred["BAA10Y"].dropna()),
        "nbfi_leverage": _weekly(fred["NFCILEVERAGE"].dropna()),
        "hh_debt": _weekly(fred["HDTGPDUSQ163N"].dropna(), 120, None),
        "corp_debt": _weekly(corp, 120, None),
        "srisk_gdp": _weekly(R["srisk_gdp"]),
        "dcovar_max": _weekly(R["dcovar"].max(axis=1)).rolling(4, min_periods=2).mean(),   # 4-wk avg: weekly dCoVaR is noisy
        "dcovar_private": _weekly(R["dcovar_pc"]).rolling(4, min_periods=2).mean(),
        "dy_total": _weekly(R["dy"]["total"]),
        "absorption": _weekly(R["ar"]["AR"]),
        "granger_dgc": _weekly(R["granger"]["dgc"], 0, 6),
        "sofr_iorb": _weekly(sofr_iorb.rolling(5).mean()),
        "reserves_gdp": _weekly(fred["WRESBAL"].loc["2009":].dropna()),        # ample-reserves regime only
        "rrp_buffer": _weekly(fred["RRPONTSYD"].loc["2021-03":].dropna()),     # RRP as a buffer: 2021+
        "srf_usage": _weekly(fred["RPONTSYD"].loc["2021-07-29":].dropna().rolling(5).mean()),  # SRF era only
        "cp_spread": _weekly(cp.rolling(5).mean()),
        "bank_rel_dd": _weekly(kre_dd),
        "stlfsi": _weekly(fred["STLFSI4"].dropna()),
        "nfci": _weekly(fred["NFCI"].dropna()),
        "gar_5": _weekly(R["gar"]["q05"], 0, None) if "q05" in R["gar"] else None,
        "low_vol": _weekly(low_vol.dropna()),
        "hh_dsr": _weekly(fred["TDSP"].dropna(), 90, None),
        "dealer_lev": _weekly(dealer_lev, 75, None),
        "usd_6m": _weekly(usd6m.dropna()),
        "sloos_ci": _weekly(fred["DRTSCILM"].dropna(), 30, None),
        "cre_delinq": _weekly(fred["DRCRELEXFACBS"].dropna(), 75, None),
        "pc_mark": _weekly(pc_mark.dropna()),
        "house_gap": _weekly(hp.dropna(), 90, None),
        "eq_val": _weekly(eq_val, 75, None),
        "margin": _weekly(margin, 75, None),
        "stock_bond": _weekly(sb_corr.dropna()),
        "fiscal": _weekly(fred["GFDEGDQ188S"].dropna(), 90, None),
        "credit_widen": credit_widen.ffill(limit=4),
        "move": _weekly(xt["^MOVE"].dropna()),
        "fx_vol": _weekly(fx_vol.dropna()),
        "em_stress": _weekly(em_stress.dropna()),
        "rec_prob": _weekly(rec_prob, 0, 6),
        # context (not scored)
        "vix": _weekly(fred["VIXCLS"].dropna()),
        "curve": _weekly(fred["T10Y3M"].dropna()),
    }
    # keep full history (FRED series go back decades) so percentiles are judged against more than one cycle
    # include the current, partly finished week (labelled by its Friday) so a daily run shows today's data
    panel = pd.DataFrame({k: v for k, v in raw.items() if v is not None}).loc["1975":close.index[-1] + pd.Timedelta(days=6)]
    R["meta"]["last_data"] = close.index[-1]
    # carry each series to the latest week: quarterly ones up to 45 weeks, the rest up to 4
    slow = {"credit_gap", "rzone", "hh_debt", "corp_debt", "gar_5", "gov_debt", "granger_dgc",
            "hh_dsr", "dealer_lev", "sloos_ci", "cre_delinq", "house_gap", "eq_val", "margin", "fiscal"}
    for c in panel:
        panel[c] = panel[c].ffill(limit=45 if c in slow else 4)   # BIS credit data lands ~2 quarters late
    R["panel"] = panel
    R.update(score(panel, p))

    # ---------------------------------------------------------------- out-of-sample validation (Giglio-Kelly-Pruitt)
    log("[model] out-of-sample validation")
    try:
        m = lambda x: x.resample("ME").mean()
        xlf = close[SYSTEM_PROXY].resample("ME").last()
        dd = (pd.concat([xlf.shift(-k) for k in range(1, 13)], axis=1).min(axis=1) / xlf - 1) * 100
        dd.iloc[-12:] = np.nan
        ip = np.log(fred["INDPRO"].dropna()); ip.index = ip.index.to_period("M").to_timestamp("M")
        yip = (ip.shift(-12) - ip) * 100
        I = m(R["index"])
        preds = {"Systemic Risk Index": I, "Chicago Fed NFCI alone": m(panel["nfci"]),
                 "St. Louis Fed stress index alone": m(panel["stlfsi"])}
        R["validation"] = {
            "drawdown": M.oos_quantile_test(dd.reindex(I.index), preds, 0.10, "2010-01-01"),
            "ip": M.oos_quantile_test(yip.reindex(I.index), preds, 0.10, "2010-01-01")}
    except Exception as e:
        log(f"   validation failed: {e}")
        R["validation"] = None
    log(f"[done] {time.time() - t0:.0f}s")
    return R


# ==================================================================== scoring
def score(panel: pd.DataFrame, p: Params) -> dict:
    """
    Score = expanding-window percentile of the indicator vs its OWN history (0-100, 100 = riskiest),
    direction-adjusted. Signal colour uses absolute thresholds where the literature gives them
    (credit gap 2/10pp, R-zone, NFCI > 0 ...), else percentile 60 / 80.

    Link score = mean of its indicator scores. Systemic Risk Index = mean of the four links.
    """
    reg = {i.id: i for i in REGISTRY}
    scores, signals = {}, {}
    for c in panel.columns:
        ind = reg.get(c)
        if ind is None or ind.pillar not in PILLARS:
            continue
        x = panel[c] * ind.direction
        sc = x.expanding(min_periods=p.pct_min_weeks).rank(pct=True) * 100
        scores[c] = sc
        if ind.abs_thresholds:
            a, r = ind.abs_thresholds
            v = panel[c]
            sig = np.where(v * ind.direction >= r * ind.direction, 2,
                           np.where(v * ind.direction >= a * ind.direction, 1, 0))
            signals[c] = pd.Series(np.where(v.isna(), np.nan, sig), index=v.index)
        else:
            signals[c] = pd.Series(np.select([sc >= 80, sc >= 60], [2, 1], 0), index=sc.index).where(sc.notna())
    S = pd.DataFrame(scores)
    pill = pd.DataFrame({k: S[[c for c in S if reg[c].pillar == k and reg[c].scored]].mean(axis=1) for k in PILLARS})
    pill.columns = [PILLARS[k] for k in pill.columns]
    # Systemic Risk Index = equal-weight mean of the four links, 4-week EMA so it does not flip on one print.
    # Only reported once at least three links have data.
    idx = pill.mean(axis=1).where(pill.notna().sum(axis=1) >= 3).ewm(span=4).mean()
    level = pd.Series(np.select([idx >= LEVELS[2][0], idx >= LEVELS[1][0], idx >= LEVELS[0][0]],
                                [LEVELS[2][1], LEVELS[1][1], LEVELS[0][1]], "Low"), index=idx.index).where(idx.notna())
    return {"scores": S, "signals": pd.DataFrame(signals), "pillars": pill,
            "index": idx.rename("Systemic Risk Index"), "regime": level}


# Bands calibrated on the index's own history (weekly peaks, v2 indicator set): GFC 88, Covid 66,
# Euro 2011 / 2015-16 / Dec-2018 56, SVB 53, Apr-2025 51.
LEVELS = [(40, "Moderate"), (52, "Elevated"), (65, "High")]


def save(R: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for k in ["panel", "scores", "signals", "pillars", "dcovar", "srisk_sector", "srisk_firm", "gar",
              "credit_gap", "rzone", "ar"]:
        R[k].to_csv(out / f"{k}.csv")
    pd.concat([R["index"], R["regime"].rename("level")], axis=1).to_csv(out / "systemic_risk_index.csv")
    R["dy"]["total"].to_csv(out / "dy_total.csv")
    R["dy"]["net"].to_csv(out / "dy_net.csv")
    with open(out / "results.pkl", "wb") as f:
        pickle.dump(R, f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["free", "bbg", "demo"], default="free")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    R = run(get_provider(a.source))
    save(R, Path(a.out))
    last = R["pillars"].dropna().index[-1]
    print(R["pillars"].loc[last].round(0).to_string())
    print("Index:", round(R["index"].dropna().iloc[-1]), R["regime"].dropna().iloc[-1])
