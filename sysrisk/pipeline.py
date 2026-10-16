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
    bbg_dir: str | None = None       # folder of Bloomberg extracts -> private build
    sectors: list = field(default_factory=lambda: list(FIN_UNIVERSE))


def _weekly(s: pd.Series | pd.DataFrame, lag_days: int = 0, limit: int | None = 26):
    """Shift by publication lag, sample to Friday weeks, forward fill (bounded) - no look-ahead."""
    x = s.copy()
    if len(x) == 0:                         # a failed optional source: return an empty weekly series, never crash
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], freq="W-FRI"))
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
    eq_tickers = sorted(set(fin_tickers) | set(DY_PANEL.values()) | {MARKET_PROXY, SYSTEM_PROXY, "^VIX", "RSP"})
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
    BBG = {}
    if p.bbg_dir:
        from .data import load_bbg
        BBG = load_bbg(p.bbg_dir)
        R["meta"]["bloomberg"] = True
        R["meta"]["source"] = provider.name + " + Bloomberg (private build)"
        if "srisk_fund" in BBG:   # Bloomberg balance sheets back to 2002 replace Yahoo's ~6 quarters
            bl = BBG["srisk_fund"].xs("BS_TOT_LIAB2", axis=1, level=1) * 1e6
            bl.columns = [c.replace(" US Equity", "") for c in bl.columns]
            bl.index = bl.index + pd.Timedelta(days=45)                        # filing lag
            bl = bl.groupby(level=0).last()
            liab = bl.combine_first(liab).sort_index()
            log(f"[bbg] liabilities from Bloomberg for {bl.notna().any().sum()} firms, from {bl.index[0].date()}")

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
    # v4 (colleague's charts): FINRA net margin debt, OFR hedge fund data, NY Fed tri-party rate, H.8 / H.4.1 series
    from . import data as _d
    def _try(f, *a):
        try:
            return f(*a)
        except Exception as e:
            log(f"   optional source failed: {e}")
            return None
    finra = _try(_d.fetch_finra_margin)
    eqv_m = eqv.resample("ME").last().ffill()
    margin = (finra["net"] / eqv_m.reindex(finra.index, method="ffill") * 100).dropna() if finra is not None else \
        pd.Series(dtype=float)
    ofr = _try(_d.fetch_ofr, ["FPF-BORROW_REPO_SUM", "FPF-STRATEGY_RV_LEVERAGERATIO_NAVWMEAN", "TFF-LF_TREAS_NET_POSITION"])
    ofr = ofr if ofr is not None else pd.DataFrame(columns=["FPF-BORROW_REPO_SUM", "FPF-STRATEGY_RV_LEVERAGERATIO_NAVWMEAN",
                                                            "TFF-LF_TREAS_NET_POSITION"])
    hf_repo = ofr["FPF-BORROW_REPO_SUM"].dropna() / 1e12                       # $tn
    hf_rv_lev = ofr["FPF-STRATEGY_RV_LEVERAGERATIO_NAVWMEAN"].dropna()
    lf_short = -ofr["TFF-LF_TREAS_NET_POSITION"].dropna() / 1e12                # net short, $tn notional
    tgcr = _try(_d.fetch_nyfed_rate, "tgcr")
    tgcr_iorb = ((tgcr - ior.reindex(tgcr.index, method="ffill")) * 100).rolling(5).mean() if tgcr is not None else \
        pd.Series(dtype=float)
    res_assets = (fred["WRESBAL"].dropna() / 1e3 / fred["TLAACBW027SBOG"].dropna().reindex(
        fred["WRESBAL"].dropna().index, method="ffill") * 100).dropna()          # $mn -> $bn over $bn
    bank_nbfi = fred["LNFACBW027SBOG"].dropna().pct_change(52) * 100
    ci_draw = ((fred["TOTCI"].dropna() / fred["TOTCI"].dropna().shift(4)) ** 13 - 1) * 100
    a2p2 = ((fred["RIFSPPNA2P2D30NB"] - fred["RIFSPPNAAD30NB"]).dropna() * 100).rolling(5).mean()
    fin_cp = fred["FINCP"].dropna().pct_change(13) * 100
    swap_lines = (fred["SWPT"].fillna(0) + fred["H41RESPPALGTRFNWW"].fillna(0)).dropna() / 1e3   # $mn -> $bn
    swap_lines = swap_lines[fred["SWPT"].notna()]
    rel = (close["SPY"] / close["RSP"]).dropna() if "RSP" in close else pd.Series(dtype=float)
    # ---- Bloomberg-only series (empty in the public build)
    E = pd.Series(dtype=float)
    bb_hy = bb_ig = bb_cet1 = bb_hkm = bb_bdc = bb_ust = bb_intl = bb_jpy = bb_eur = E
    bbg_extra = {}
    if BBG:
        def col(name, t, f="PX_LAST"):
            try:
                return BBG[name][(t, f)].dropna()
            except KeyError:
                return E
        bb_hy, bb_ig = col("spreads", "LF98OAS Index"), col("spreads", "LUACOAS Index")
        c1 = BBG["cet1"].xs("BS_TIER1_COM_EQUITY_RATIO", axis=1, level=1) if "cet1" in BBG else pd.DataFrame()
        bb_cet1 = c1.resample("QE").last().median(axis=1).dropna() if len(c1) else E
        if "dealers" in BBG:
            us = ["JPM US Equity", "BAC US Equity", "C US Equity", "GS US Equity", "MS US Equity", "WFC US Equity",
                  "JEF US Equity"]
            dl = BBG["dealers"].resample("QE").last()
            mc = dl.xs("CUR_MKT_CAP", axis=1, level=1).reindex(columns=us)
            db = dl.xs("BS_TOT_LIAB2", axis=1, level=1).reindex(columns=us)
            ok = mc.notna() & db.notna()
            bb_hkm = (mc.where(ok).sum(axis=1) / (mc.where(ok).sum(axis=1) + db.where(ok).sum(axis=1)) * 100)
            bb_hkm = bb_hkm[ok.sum(axis=1) >= 4]
        if "bdc_nav" in BBG:
            pb = BBG["bdc_nav"].xs("PX_TO_BOOK_RATIO", axis=1, level=1)
            bb_bdc = ((1 - pb.where(pb.notna().sum(axis=1) >= 4).median(axis=1)) * 100).dropna()   # discount, %
        bb_ust = col("xccy_liq", "GVLQUSD Index")
        bb_intl = pd.concat([col("xccy_liq", "GVLQJPY Index"), col("xccy_liq", "GVLQGBP Index")], axis=1).mean(axis=1).dropna()
        bb_jpy = col("xccy_liq", ".JYCCBS3M G Index").rolling(5).mean().dropna()
        eur_new, eur_old = col("xccy_liq", "EUXOQQ1 Curncy"), col("xccy", "EUBS1 Curncy")
        bb_eur = pd.concat([eur_old[eur_old.index < (eur_new.index[0] if len(eur_new) else eur_old.index[-1])], eur_new]).sort_index()
        bbg_extra = {"xccy": pd.concat({"USD/JPY 3m OIS basis": bb_jpy, "EUR/USD 1y basis": bb_eur}, axis=1),
                             "liq": pd.concat({"Treasuries": bb_ust, "JGBs": col("xccy_liq", "GVLQJPY Index"),
                                               "Gilts": col("xccy_liq", "GVLQGBP Index"),
                                               "Bunds": col("xccy_liq", "GVLQDE Index")}, axis=1)}
    concentration = (rel / rel.shift(756) - 1) * 100
    r_sb = close[["SPY", "IEF"]].pct_change(fill_method=None)
    sb_corr = r_sb["SPY"].rolling(63).corr(r_sb["IEF"])
    credit_widen = fred["BAA10Y"].dropna().resample("W-FRI").last().diff(13)
    fx_vol = xt["DX-Y.NYB"].dropna().pct_change().rolling(21).std() * np.sqrt(252) * 100
    emrel = (xt["EMB"] / close["IEF"]).dropna()
    em_stress = -(emrel / emrel.rolling(252, min_periods=60).max() - 1) * 100
    t10y3m_m = fred["T10Y3M"].dropna().resample("ME").mean()
    rec_prob = pd.Series(norm.cdf(-0.5333 - 0.6330 * t10y3m_m) * 100, index=t10y3m_m.index)
    R["extra"] = {"hf": pd.concat({"repo": hf_repo, "short": lf_short}, axis=1), "res_assets": res_assets,
                  "rv": rv, "low_vol": low_vol, "dealer_lev": dealer_lev, "usd6m": usd6m, "pc_mark": pc_mark,
                  "house_gap": hp, "eq_val": eq_val, "move": xt["^MOVE"].dropna(), "rec_prob": rec_prob}

    R["extra"]["bbg"] = bbg_extra
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
        "reserves_gdp": _weekly(res_assets.loc["2009":]),                    # ample-reserves regime only
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
        "margin": _weekly(margin, 30, None),
        "hf_repo": _weekly(hf_repo, 200, None),
        "hf_rv_lev": _weekly(hf_rv_lev, 200, None),
        "lf_ust_short": _weekly(lf_short, 4, 4),
        "bank_nbfi": _weekly(bank_nbfi.dropna()),
        "concentration": _weekly(concentration.dropna()),
        "tgcr_iorb": _weekly(tgcr_iorb.dropna()),
        "a2p2": _weekly(a2p2.dropna()),
        "fin_cp": _weekly(fin_cp.dropna()),
        "swap_lines": _weekly(swap_lines),
        "ci_draw": _weekly(ci_draw.dropna()),
        "hy_oas": _weekly(bb_hy),
        "bank_capital": _weekly(bb_cet1, 45, None),
        "hkm": _weekly(bb_hkm, 45, None),
        "bdc_pb": _weekly(bb_bdc, 0, 6),
        "ust_liq": _weekly(bb_ust),
        "intl_liq": _weekly(bb_intl),
        "xccy_basis": _weekly(bb_jpy.loc["2010":]),          # post-2010 regime only (structural break)
        "eur_basis": _weekly(bb_eur),
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
    slow = {"credit_gap", "rzone", "hh_debt", "corp_debt", "gar_5", "gov_debt", "granger_dgc", "margin",
            "hf_repo", "hf_rv_lev", "bank_capital", "hkm",
            "hh_dsr", "dealer_lev", "sloos_ci", "cre_delinq", "house_gap", "eq_val", "margin", "fiscal"}
    for c in panel:
        panel[c] = panel[c].ffill(limit=45 if c in slow else 4)   # BIS credit data lands ~2 quarters late
    R["panel"] = panel
    R.update(score(panel, p))

    # ---------------------------------------------------------------- evidence screen + out-of-sample validation
    log("[model] evidence screen (real-time, monthly)")
    xlf_long = _try(lambda: provider.ohlc([SYSTEM_PROXY], "1998-12-01")["close"][SYSTEM_PROXY].dropna())
    xlf_long = xlf_long if xlf_long is not None and len(xlf_long) else close[SYSTEM_PROXY].dropna()
    xlf_long = xlf_long.loc[:close.index[-1]]
    dd = drawdown_target(xlf_long)
    R["equal_weight_index"] = R["index"].copy()
    sel = screen(R["scores"], dd)
    R.update(apply_screen(R["scores"], sel))
    R["screen"] = {"history": sel, "latest": sel[max(sel)] if sel else {},
                   "eligible": [c for c in R["scores"] if REG_BY_ID[c].scored and REG_BY_ID[c].pillar in PILLARS],
                   "n_train": {c: int(pd.concat({"x": R["scores"][c].resample("ME").mean(), "y": dd}, axis=1)
                                       .loc[:dd.index[-1] - pd.offsets.MonthEnd(SCREEN_H)].dropna().shape[0])
                               for c in R["scores"]}, "min_train": SCREEN_MIN, "thr": SCREEN_THR}
    log("   selected now: " + ", ".join(R["screen"]["latest"]))
    log("[model] out-of-sample validation")
    try:
        m = lambda x: x.resample("ME").mean()
        ip = np.log(fred["INDPRO"].dropna()); ip.index = ip.index.to_period("M").to_timestamp("M")
        yip = (ip.shift(-12) - ip) * 100
        I = m(R["index"])
        preds = {"Systemic Risk Index": I, "Old version (equal weights, no screen)": m(R["equal_weight_index"]),
                 "Chicago Fed NFCI alone": m(panel["nfci"]), "St. Louis Fed stress index alone": m(panel["stlfsi"])}
        idx_m = I.index.union(dd.index)
        R["validation"] = {
            "drawdown": M.oos_quantile_test(dd.reindex(idx_m), preds, 0.10, "2010-01-01"),
            "drawdown_2003": M.oos_quantile_test(dd.loc["2003":].reindex(idx_m), preds, 0.10, "2010-01-01"),
            "ip": M.oos_quantile_test(yip.reindex(idx_m), preds, 0.10, "2010-01-01")}
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
        x = panel[c]
        if c in ZERO_FLOOR:                      # mostly-zero facility usage: treat noise below the floor as zero
            x = x.where(x.isna() | (x >= ZERO_FLOOR[c]), 0.0)
        x = x * ind.direction
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
ZERO_FLOOR = {"srf_usage": 1.0, "swap_lines": 1.0}   # $bn

LEVELS = [(40, "Moderate"), (52, "Elevated"), (65, "High")]



# ==================================================================== evidence screen
SCREEN_H, SCREEN_TAU, SCREEN_MIN, SCREEN_THR = 12, 0.10, 36, 0.02
REG_BY_ID = {i.id: i for i in REGISTRY}


def drawdown_target(px: pd.Series) -> pd.Series:
    """Worst XLF drawdown over the next 12 months (%), monthly. NaN for the last 12 months."""
    x = px.resample("ME").last()
    dd = (pd.concat([x.shift(-k) for k in range(1, SCREEN_H + 1)], axis=1).min(axis=1) / x - 1) * 100
    dd.iloc[-SCREEN_H:] = np.nan
    return dd


def screen(S: pd.DataFrame, dd: pd.Series) -> dict:
    """
    Real-time evidence screen (pre-specified: tau 0.10, 12-month horizon, >= 36 months of training pairs,
    in-sample quantile pseudo-R2 > 0.02 with the right sign). At each month-end t, each eligible indicator is
    fitted only on pairs (x_s, worst drawdown over s+1..s+12) already realised by t. An indicator is kept if
    a higher risk score went with a deeper 10th-percentile drawdown. Returns {month_end: {id: pseudo_R2}}.
    """
    cand = [c for c in S if REG_BY_ID[c].scored and REG_BY_ID[c].pillar in PILLARS]
    Sm = S[cand].resample("ME").mean()
    out = {}
    for t in Sm.index:
        tr_end = t - pd.offsets.MonthEnd(SCREEN_H)
        keep = {}
        for c in cand:
            d = pd.concat({"x": Sm[c], "y": dd}, axis=1).loc[:tr_end].dropna()
            if len(d) < SCREEN_MIN:
                continue
            X = np.column_stack([np.ones(len(d)), d.x.values])
            b = M.quantreg(d.y.values, X, SCREEN_TAU)
            l1 = M.qloss(d.y.values, X @ b, SCREEN_TAU)
            l0 = M.qloss(d.y.values, np.quantile(d.y.values, SCREEN_TAU), SCREEN_TAU)
            r2 = 1 - l1 / l0
            if b[1] < 0 and r2 > SCREEN_THR:
                keep[c] = float(r2)
        if keep or out:
            out[t] = keep
    return out


def apply_screen(S: pd.DataFrame, sel: dict) -> dict:
    """Each week uses the selection made at the previous month-end. Link = mean of kept indicators;
    index = mean of the links (at least three), 4-week EMA."""
    if not sel:
        return {}
    months = pd.DatetimeIndex(sorted(sel))
    mask = pd.DataFrame(False, index=S.index, columns=S.columns)
    for w in S.index:
        pos = months.searchsorted(w, side="left") - 1          # latest month-end strictly before this week
        if pos >= 0:
            mask.loc[w, list(sel[months[pos]])] = True
    pill = pd.DataFrame({PILLARS[k]: S[[c for c in S if REG_BY_ID[c].pillar == k]].where(
        mask[[c for c in S if REG_BY_ID[c].pillar == k]]).mean(axis=1) for k in PILLARS})
    # at least two links: before 2009 few contagion/liquidity indicators have a track record, and requiring three
    # would cut the history to Aug 2008 and leave the screen nothing pre-crisis to learn from
    idx = pill.mean(axis=1).where(pill.notna().sum(axis=1) >= 2).ewm(span=4).mean()
    r = idx.round()
    level = pd.Series(np.select([r >= LEVELS[2][0], r >= LEVELS[1][0], r >= LEVELS[0][0]],
                                [LEVELS[2][1], LEVELS[1][1], LEVELS[0][1]], "Low"), index=idx.index).where(idx.notna())
    return {"pillars": pill, "index": idx.rename("Systemic Risk Index"), "regime": level, "screen_mask": mask}

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
    ap.add_argument("--bbg", default=None, help="folder of Bloomberg extracts (private build)")
    a = ap.parse_args()
    R = run(get_provider(a.source), Params(bbg_dir=a.bbg))
    save(R, Path(a.out))
    last = R["pillars"].dropna().index[-1]
    print(R["pillars"].loc[last].round(0).to_string())
    print("Index:", round(R["index"].dropna().iloc[-1]), R["regime"].dropna().iloc[-1])
