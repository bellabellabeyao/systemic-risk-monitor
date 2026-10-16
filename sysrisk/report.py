"""
Turn pipeline results into ONE story-led HTML dashboard.

The page answers one question - "How likely is a loss somewhere to become a system-wide problem, and
where would it start?" - through a chain of four links. A systemic event needs all four:

    FUEL           an excess that can unwind         (mispriced credit, leverage, credit booms)
    FAULT LINES    a way for the loss to spread      (thin capital, tail spillovers, crowded trades)
    SHOCK ABSORBERS liquidity to absorb forced sales (reserves, RRP cushion, repo, bank funding)
    IGNITION       a shock actually testing it       (realised stress, bank equity stress)

Every sentence on the page is generated here from the data, so the story updates on each run.

    python -m sysrisk.report --results output/results.pkl --out systemic_risk_monitor.html
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PILLAR_Q, PILLARS, REGISTRY
from .pipeline import LEVELS

# Display units for each indicator's own history chart: (scale, suffix, prefix, axis label)
HIST_UNITS = {
    "ebp_sentiment": (1, "pp", "", "Baa minus 10y Treasury"), "nbfi_leverage": (1, "", "", "Index, 0 = average"),
    "credit_gap": (1, "pp", "", "Gap to trend, pp of GDP"), "rzone": (1, "", "", "0-1, crisis zone above 0.8"),
    "corp_debt": (1, "%", "", "% of GDP"), "low_vol": (1, "%", "", "% below 5-year average vol"),
    "hh_dsr": (1, "%", "", "% of disposable income"), "house_gap": (1, "%", "", "% vs long-run trend"),
    "eq_val": (1, "%", "", "% of GDP"), "margin": (1, "%", "", "% of equity market value"),
    "hh_debt": (1, "%", "", "% of GDP"), "srisk_gdp": (1, "%", "", "% of GDP"),
    "dcovar_max": (1, "%", "", "Extra weekly tail loss, %"), "dcovar_private": (1, "%", "", "Extra weekly tail loss, %"),
    "dealer_lev": (1, "x", "", "Assets / equity"), "stock_bond": (1, "", "", "63-day correlation"),
    "absorption": (100, "%", "", "% of risk from top PCs"), "dy_total": (1, "%", "", "% of variance from spillovers"),
    "granger_dgc": (100, "%", "", "% of sector pairs linked"), "rrp_buffer": (1e-3, "tn", "$", "ON RRP balance"),
    "reserves_gdp": (1, "%", "", "Reserves as % of bank assets"), "sofr_iorb": (1, "bp", "", "SOFR minus IORB, 5-day avg"),
    "srf_usage": (1, "bn", "$", "Daily take-up, 5-day avg"), "cp_spread": (1, "bp", "", "3m financial CP minus T-bill"),
    "usd_6m": (1, "%", "", "6-month change, broad dollar"), "fiscal": (1, "%", "", "% of GDP"),
    "stlfsi": (1, "", "", "Index, 0 = normal"), "nfci": (1, "", "", "Index, 0 = average"),
    "bank_rel_dd": (1, "%", "", "% behind S&P 500 from 1y high"), "sloos_ci": (1, "%", "", "Net % of banks tightening"),
    "cre_delinq": (1, "%", "", "% of loans delinquent"), "pc_mark": (1, "%", "", "% behind HY from 1y high"),
    "credit_widen": (100, "bp", "", "13-week change in Baa-10y"), "vix": (1, "", "", "VIX"), "move": (1, "", "", "MOVE"),
    "fx_vol": (1, "%", "", "1m realised vol, annualised"),
    "margin": (1, "%", "", "Net margin debt, % of equity market value"), "hf_repo": (1, "tn", "$", "Hedge fund repo borrowing"),
    "hf_rv_lev": (1, "x", "", "Gross assets / NAV, relative-value funds"),
    "lf_ust_short": (1, "tn", "$", "Net short, Treasury futures notional"), "bank_nbfi": (1, "%", "", "Year-on-year growth"),
    "concentration": (1, "%", "", "Cap-weighted minus equal-weighted, 3y"), "tgcr_iorb": (1, "bp", "", "TGCR minus IORB, 5-day avg"),
    "a2p2": (1, "bp", "", "A2/P2 minus AA 30-day CP"), "fin_cp": (1, "%", "", "13-week change"),
    "swap_lines": (1, "bn", "$", "Swap lines + FIMA repo"),
    "hy_oas": (100, "bp", "", "HY option-adjusted spread"), "bank_capital": (1, "%", "", "Median CET1 ratio"),
    "hkm": (1, "%", "", "Equity / (equity + debt), US dealers"), "bdc_pb": (1, "%", "", "Discount to NAV (negative = premium)"),
    "ust_liq": (1, "bp", "", "Avg pricing error vs fitted curve"), "intl_liq": (1, "bp", "", "JGB and Gilt average"),
    "xccy_basis": (1, "bp", "", "USD/JPY 3m OIS basis"), "eur_basis": (1, "bp", "", "EUR/USD 1y basis"), "ci_draw": (1, "%", "", "4-week growth, annualised"), "em_stress": (1, "%", "", "% behind Treasuries from 1y high"),
}


def hist_payload(R, asof, ids):
    """Raw history for each indicator in display units, plus the line where a reading turns high-risk:
    the 80th percentile of its own history to date (20th for indicators where low = risky), i.e. the
    same threshold the score uses, so the chart and the score agree. Literature thresholds added where they exist."""
    out = {}
    panel = R["panel"].loc[:asof]
    for i in ids:
        if i not in panel or panel[i].dropna().empty:
            continue
        sc, suf, pre, lab = HIST_UNITS.get(i, (1, "", "", ""))
        x = panel[i].dropna() * sc
        x = x.loc["1995":]
        ind = REG[i]
        q = 0.8 if ind.direction > 0 else 0.2
        thr = (panel[i].dropna() * sc).expanding(156).quantile(q).reindex(x.index)
        step = 2 if len(x) > 1200 else 1                     # fortnightly before thinning long series
        keep = np.zeros(len(x), bool); keep[::step] = True; keep[-1] = True    # always keep the latest week
        xx, tt = x[keep], thr[keep]
        out[i] = {"x": [d.strftime("%Y-%m-%d") for d in xx.index],
                  "y": [round(float(v), 4) for v in xx.values],
                  "thr": [None if pd.isna(v) else round(float(v), 4) for v in tt.values],
                  "dir": ind.direction, "suf": suf, "pre": pre, "lab": lab,
                  "abs": [a * sc for a in ind.abs_thresholds] if ind.abs_thresholds else None}
    return out


# indicators drawn in a chart above each link's table (so the table can mark them)
CHARTED = {"xccy_basis", "eur_basis", "ust_liq", "intl_liq", "hf_repo", "lf_ust_short", "ebp_sentiment", "credit_gap", "eq_val", "house_gap", "srisk_gdp", "dcovar_max", "dcovar_private",
           "dy_total", "stock_bond", "rrp_buffer", "reserves_gdp", "sofr_iorb", "stlfsi", "bank_rel_dd",
           "vix", "move", "credit_widen"}

REG = {i.id: i for i in REGISTRY}
LINK_IDS = {PILLARS[k]: [i.id for i in REGISTRY if i.pillar == k] for k in PILLARS}
CRISES = [("2008-11-07", "GFC"), ("2011-10-14", "Euro crisis"), ("2016-01-22", "2015-16 oil / China"),
          ("2018-12-28", "Dec 2018"), ("2020-03-27", "Covid"), ("2023-04-07", "SVB"), ("2025-04-25", "Apr 2025 tariffs")]


# Literature map: every strand of the systemic-risk literature, where it sits on the dashboard, and what is missing.
# status: "in" scored in the index | "context" shown, not scored | "gap" not covered (reason given)
LITMAP = [
    {"strand": "Credit booms and early warning", "link": "Build-up", "status": "in",
     "papers": "Borio & Drehmann (2009); Schularick & Taylor (2012); Jordà, Schularick & Taylor (2013); Mian, Sufi & Verner (2017); Drehmann & Juselius (2014)",
     "here": "Credit-to-GDP gap, household and corporate debt/GDP, household debt service"},
    {"strand": "Credit and asset-price booms together", "link": "Build-up", "status": "in",
     "papers": "Greenwood, Hanson, Shleifer & Sørensen (2022)", "here": "R-zone"},
    {"strand": "Credit-market sentiment", "link": "Build-up", "status": "in",
     "papers": "Gilchrist & Zakrajšek (2012); López-Salido, Stein & Zakrajšek (2017); Krishnamurthy & Muir (2017)",
     "here": "Baa-10y spread tightness. Gap: the excess bond premium itself (Fed CSV) would be cleaner."},
    {"strand": "Asset-price bubbles and valuations", "link": "Build-up", "status": "in",
     "papers": "Borio & Lowe (2002); Shiller (2000); Jordà, Schularick & Taylor (2015, 'Leveraged bubbles')",
     "here": "House prices vs trend (scored); equity market value/GDP and margin credit (context: non-stationary or no crisis-prediction evidence)"},
    {"strand": "Volatility paradox", "link": "Build-up", "status": "in",
     "papers": "Brunnermeier & Sannikov (2014); Danielsson, Valenzuela & Zer (2018)", "here": "Volatility too low for too long (new)"},
    {"strand": "Market-based tail measures", "link": "Contagion", "status": "in",
     "papers": "Adrian & Brunnermeier (2016); Acharya, Pedersen, Philippon & Richardson (2017); Brownlees & Engle (2017). Critiques: Benoit, Colliard, Hurlin & Pérignon (2017); Löffler & Raupach (2018)",
     "here": "dCoVaR by sector incl. private credit, SRISK"},
    {"strand": "Connectedness and correlation", "link": "Contagion", "status": "in",
     "papers": "Diebold & Yilmaz (2012, 2014); Billio, Getmansky, Lo & Pelizzon (2012); Kritzman, Li, Page & Rigobon (2011)",
     "here": "Spillover index, Granger network, absorption ratio"},
    {"strand": "Intermediary leverage and capital", "link": "Contagion", "status": "context",
     "papers": "Adrian & Shin (2010); Adrian, Etula & Muir (2014); He, Kelly & Manela (2017)",
     "here": "Broker-dealer leverage (Fed Financial Accounts) and He-Kelly-Manela dealer capital ratio (Bloomberg build), both context."},
    {"strand": "Diversification breakdown", "link": "Contagion", "status": "context",
     "papers": "Campbell, Pflueger & Viceira (2020)", "here": "Stock-bond correlation (context)"},
    {"strand": "Crowding and positioning", "link": "Contagion", "status": "context",
     "papers": "Brunnermeier, Nagel & Pedersen (2008); Pedersen (2009, 'When everyone runs for the exit'); Barth & Kahn (2021)",
     "here": "Leveraged funds' Treasury futures short (CFTC via OFR) covers the basis trade. Gap: other CFTC positioning and credit fund flows (EPFR)."},
    {"strand": "Market concentration", "link": "Contagion", "status": "context",
     "papers": "Practitioner measure; Fed Financial Stability Report on equity concentration", "here": "Cap-weighted vs equal-weighted S&P 500 (context)"},
    {"strand": "Fire sales and common holdings", "link": "Contagion", "status": "gap",
     "papers": "Greenwood, Landier & Thesmar (2015); Duarte & Eisenbach (2021); Cont & Schaanning (2017)",
     "here": "Not covered: needs regulatory or 13F holdings data. The largest amplification channel empirically."},
    {"strand": "Interbank exposure networks", "link": "Contagion", "status": "gap",
     "papers": "Eisenberg & Noe (2001); Battiston et al. (2012, DebtRank); Glasserman & Young (2016)",
     "here": "Not covered: bilateral exposures are supervisory data. Glasserman & Young find direct contagion small, so low priority."},
    {"strand": "Funding liquidity, repo and runs", "link": "Shock absorbers", "status": "in",
     "papers": "Brunnermeier & Pedersen (2009); Gorton & Metrick (2012); Copeland, Duffie & Yang (2021); Afonso et al. (2022)",
     "here": "Reserves / bank assets, ON RRP, SOFR-IORB, Standing Repo Facility, CP-bill spread (scored); tri-party repo, A2/P2 CP spread, financial CP outstanding, Fed swap lines (context). Gap: NY Fed repo volumes by segment, prime vs government MMF assets (ICI)."},
    {"strand": "Fiscal space and bank capital", "link": "Shock absorbers", "status": "context",
     "papers": "Romer & Romer (2018); Jordà, Schularick & Taylor (2016); Jordà, Richter, Schularick & Taylor (2021)",
     "here": "Federal debt/GDP (context: non-stationary); bank CET1 ratios (context, Bloomberg build)."},
    {"strand": "Global dollar funding", "link": "Shock absorbers", "status": "context",
     "papers": "Rey (2013); Bruno & Shin (2015); Du, Tepper & Verdelhan (2018); Avdjiev, Du, Koch & Shin (2019)",
     "here": "USD/JPY OIS basis (scored, Bloomberg build); EUR/USD basis, broad dollar, Fed swap lines and FIMA usage (context). Gap: BIS cross-border USD claims, TIC holdings by country."},
    {"strand": "Bank interest-rate risk and deposit runs", "link": "Trigger", "status": "context",
     "papers": "Drechsler, Savov & Schnabl (2021); Jiang, Matvos, Piskorski & Seru (2024)",
     "here": "Regional banks vs market (scored). Gap: unrealised securities losses and uninsured deposits (FDIC Quarterly Banking Profile)."},
    {"strand": "Credit supply and realised losses", "link": "Trigger", "status": "context",
     "papers": "Lown & Morgan (2006); Bassett, Chosak, Driscoll & Zakrajšek (2014); Ivashina & Scharfstein (2010); Acharya & Steffen (2020)",
     "here": "Credit-line draws via C&I loan growth (scored); SLOOS tightening, CRE delinquencies (context: lagging)"},
    {"strand": "Non-bank and private credit, hidden leverage", "link": "Contagion / Trigger", "status": "context",
     "papers": "FSB NBFI monitoring reports; IMF GFSR (Apr 2024, ch. 2) on private credit; Fed Financial Stability Report",
     "here": "Alt-manager and BDC dCoVaR (scored); BDC vs HY mark, hedge fund repo and leverage (OFR Form PF), bank lending to non-banks (H.8), net margin debt (FINRA), all context. Gap: BDC discount to NAV, NAV-loan leverage."},
    {"strand": "Credit-spread shocks", "link": "Trigger", "status": "in",
     "papers": "Gilchrist & Zakrajšek (2012)", "here": "13-week change in the Baa-10y spread (scored)"},
    {"strand": "Market volatility", "link": "Trigger", "status": "context",
     "papers": "Whaley (2000); Bekaert & Hoerova (2014); Menkhoff et al. (2012)",
     "here": "VIX, MOVE, dollar volatility (context: already inside the St. Louis Fed index)"},
    {"strand": "Capital-flow reversals", "link": "Trigger", "status": "context",
     "papers": "Forbes & Warnock (2012); Rey (2013)", "here": "EM dollar bonds vs Treasuries (context)"},
    {"strand": "Market liquidity", "link": "Trigger", "status": "in",
     "papers": "Brunnermeier & Pedersen (2009); Hu, Pan & Wang (2013); Pinter (2023) on the 2022 gilt crisis",
     "here": "Bloomberg Treasury liquidity index (scored, Bloomberg build); JGB and gilt liquidity (context). Gap: IG corporate bond liquidity."},
    {"strand": "Composite stress indices", "link": "Trigger", "status": "in",
     "papers": "Holló, Kremer & Lo Duca (2012, CISS); Kliesen & Smith (2010); Brave & Butters (2011)",
     "here": "St. Louis Fed FSI, Chicago Fed NFCI"},
    {"strand": "Macro tail risk and recession signals", "link": "Consequence", "status": "in",
     "papers": "Adrian, Boyarchenko & Giannone (2019); Estrella & Mishkin (1998); Estrella & Trubin (2006)",
     "here": "Growth-at-Risk; yield-curve recession probability (shown, not in the index)"},
    {"strand": "Evaluating systemic risk measures", "link": "Whole index", "status": "in",
     "papers": "Bisias, Flood, Lo & Valavanis (2012); Giglio, Kelly & Pruitt (2016)",
     "here": "Out-of-sample quantile test of the index (new). Gap: Giglio-Kelly-Pruitt's dimension-reduced quantile regression (PCQR) as an alternative to equal weights."},
]


def ordn(x):
    n = int(round(x))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def level_of(x):
    if x is None or pd.isna(x):
        return "n/a"
    lab = "Low"
    for cut, name in LEVELS:
        if x >= cut:
            lab = name
    return lab


def _s(x: pd.Series, since=None, step=1, scale=1.0):
    x = x.dropna()
    if since is not None:
        x = x.loc[since:]
    if step > 1:
        x = x.iloc[::step]
    return {"x": [d.strftime("%Y-%m-%d") for d in x.index], "y": [round(float(v) * scale, 4) for v in x.values]}


class Story:
    """Builds readings, link verdicts, headline and chart titles from results R."""

    def __init__(self, R):
        self.R = R
        self.asof = R["index"].dropna().index[-1]
        self.panel = R["panel"].loc[:self.asof]
        self.scores = R["scores"].loc[:self.asof]
        self.v = self.panel.iloc[-1]
        self.sc = self.scores.iloc[-1]
        self.sc13 = self.scores.iloc[-1] - self.scores.iloc[-14]
        self.since = {c: self.panel[c].first_valid_index().year for c in self.panel if self.panel[c].notna().any()}
        dco = R["dcovar"].rolling(4, min_periods=2).mean().loc[:self.asof].dropna(how="all").iloc[-1]   # same week as everything else
        self.worst_sector = dco.idxmax() if len(dco) else "n/a"

    # ------------------------------------------------------------- plain-English reading per indicator
    def reading(self, i):
        v = self.v.get(i)
        if v is None or pd.isna(v):
            return "no data"
        R = self.R
        f = {
            "ebp_sentiment": lambda: f"Baa-10y spread {v:.2f}pp, tighter than {self.sc[i]:.0f}% of weeks since {self.since[i]}",
            "nbfi_leverage": lambda: f"index {v:+.2f}, {'above' if v > 0 else 'below'} its long-run average",
            "credit_gap": lambda: f"{v:+.1f}pp vs trend: " + ("credit growing slower than the economy" if v < -2 else
                                                            "near trend" if v < 2 else "inside the Basel buffer zone"),
            "rzone": lambda: f"{v:.2f} on a 0-1 scale (crisis zone above 0.8)",
            "corp_debt": lambda: f"{v:.0f}% of GDP",
            "hh_debt": lambda: f"{v:.0f}% of GDP, down from {self.peak(i)[0]:.0f}% in {self.peak(i)[1]}",
            "srisk_gdp": lambda: f"${R['srisk_total'].loc[:self.asof].dropna().iloc[-1]:.0f}bn shortfall, {v:.1f}% of GDP",
            "dcovar_max": lambda: f"+{v:.1f}% extra weekly loss in the system's worst weeks, from {self.worst_sector}",
            "dcovar_private": lambda: f"+{v:.1f}% extra weekly tail loss",
            "absorption": lambda: f"{v * 100:.0f}% of financials' risk comes from a few common drivers",
            "dy_total": lambda: f"{v:.0f}% of each asset's volatility imported from other assets",
            "granger_dgc": lambda: f"{v * 100:.0f}% of sector pairs show lead-lag links",
            "rrp_buffer": lambda: f"${v:.1f}bn, against a ${self.peak(i)[0] / 1000:.1f}tn peak in {self.peak(i)[1]}",
            "reserves_gdp": lambda: f"{v:.1f}% of bank assets (Sept 2019 low: {self.panel[i].loc['2019'].min():.1f}%)",
            "margin": lambda: f"{v:.2f}% of equity market value" + (" (record high)" if self.sc.get(i, 0) >= 99 else ""),
            "hf_repo": lambda: f"${v:.2f}tn" + (" (record high)" if self.sc.get(i, 0) >= 99 else ""),
            "hf_rv_lev": lambda: f"{v:.1f}x NAV",
            "lf_ust_short": lambda: f"${v:.2f}tn net short",
            "bank_nbfi": lambda: f"{v:+.0f}% over 12 months",
            "concentration": lambda: f"cap-weighted S&P ahead by {v:.0f}% over 3 years",
            "tgcr_iorb": lambda: f"{v:+.1f}bp",
            "a2p2": lambda: f"{v:.0f}bp",
            "fin_cp": lambda: f"{v:+.1f}% over 13 weeks",
            "swap_lines": lambda: f"${v:.1f}bn",
            "ci_draw": lambda: f"{v:+.1f}% annualised over 4 weeks",
            "hy_oas": lambda: f"HY {v * 100:.0f}bp, tighter than {100 - self.sc.get(i, 0):.0f}% of weeks since 2002",
            "bank_capital": lambda: f"{v:.1f}% median CET1",
            "hkm": lambda: f"{v:.1f}% (2008 low: {self.panel[i].loc['2008':'2009'].min():.1f}%)",
            "bdc_pb": lambda: (f"{v:.0f}% below NAV" if v >= 0 else f"{-v:.0f}% above NAV"),
            "ust_liq": lambda: f"{v:.2f}bp off the fitted curve (March 2020: {self.panel[i].loc['2020-03'].max():.1f}bp)",
            "intl_liq": lambda: f"{v:.1f}bp off the fitted curve",
            "xccy_basis": lambda: f"{v:.0f}bp (March 2020: {self.panel[i].loc['2020-03'].min():.0f}bp)",
            "eur_basis": lambda: f"{v:.1f}bp",
            "sofr_iorb": lambda: f"{v:+.1f}bp " + ("(repo still below the Fed floor)" if v < 0 else "(repo trading above the Fed floor)"),
            "srf_usage": lambda: f"${v:.1f}bn a day (5-day average)",
            "cp_spread": lambda: f"{v:.0f}bp",
            "stlfsi": lambda: f"{v:+.2f} (zero = normal stress)",
            "nfci": lambda: f"{v:+.2f} (negative = looser than average)",
            "bank_rel_dd": lambda: f"{v:.0f}% behind the S&P 500 from their 1-year high",
            "gar_5": lambda: f"{v:+.1f}%",
            "low_vol": lambda: f"S&P 500 volatility {abs(v):.0f}% {'below' if v > 0 else 'above'} its 5-year average",
            "hh_dsr": lambda: f"{v:.1f}% of disposable income (peak {self.peak(i)[0]:.1f}% in {self.peak(i)[1]})",
            "dealer_lev": lambda: f"{v:.1f}x assets to equity",
            "usd_6m": lambda: f"broad dollar {v:+.1f}% over 6 months",
            "sloos_ci": lambda: f"net {v:+.0f}% of banks tightening",
            "cre_delinq": lambda: f"{v:.2f}% of CRE loans delinquent",
            "pc_mark": lambda: f"BDCs {v:.0f}% behind HY bonds from their 1-year high",
            "house_gap": lambda: f"real house prices {v:+.1f}% vs long-run trend",
            "eq_val": lambda: f"{v:.0f}% of GDP" + (" (record high)" if self.sc.get(i, 0) >= 99.5 else ""),
            "margin": lambda: f"{v:.1f}% of equity market value",
            "stock_bond": lambda: f"correlation {v:+.2f} over 3 months" + (" (falling together)" if v > 0.2 else ""),
            "fiscal": lambda: f"{v:.0f}% of GDP",
            "credit_widen": lambda: f"Baa-10y {v * 100:+.0f}bp over 13 weeks",
            "vix": lambda: f"{v:.1f}",
            "move": lambda: f"{v:.0f}",
            "fx_vol": lambda: f"{v:.1f}% annualised",
            "em_stress": lambda: f"EM dollar bonds {v:.1f}% behind Treasuries from their 1-year high",
            "rec_prob": lambda: f"{v:.0f}%",
        }.get(i)
        return f() if f else f"{v:.2f}"

    def peak(self, i):
        x = self.panel[i].dropna()
        return float(x.max()), x.idxmax().year

    def short(self, i):
        return REG[i].name.split(" (")[0].lower()

    # ------------------------------------------------------------- per-link verdict
    def link(self, name):
        ids = [i for i in LINK_IDS[name] if i in self.sc.index and pd.notna(self.sc[i]) and REG[i].scored]
        P = self.R["pillars"][name].loc[:self.asof].dropna()
        score, d13 = float(P.iloc[-1]), float(P.iloc[-1] - P.iloc[-14])
        hot = sorted([i for i in ids if self.sc[i] >= 70], key=lambda i: -self.sc[i])
        cool = sorted([i for i in ids if self.sc[i] <= 30], key=lambda i: self.sc[i])
        v, sc = self.v, self.sc
        head, bullets = self.takeaway(name, score, hot, cool)
        drivers = [{"name": REG[i].name, "reading": self.reading(i), "score": float(sc[i])} for i in hot[:2]]
        offsets = [{"name": REG[i].name, "reading": self.reading(i), "score": float(sc[i])} for i in cool[:2]]
        rows = []
        for i in LINK_IDS[name]:
            ind = REG[i]
            if i not in self.panel or self.panel[i].dropna().empty:
                rows.append({"id": i, "name": ind.name, "missing": True, "why": ind.why, "tag": ind.bbg or ind.source,
                             "src": ind.src})
                continue
            s = self.scores[i].dropna() if i in self.scores else pd.Series(dtype=float)
            rows.append({"id": i, "name": ind.name, "reading": self.reading(i),
                         "score": None if s.empty else float(s.iloc[-1]),
                         "d13": None if len(s) < 14 else float(s.iloc[-1] - s.iloc[-14]),
                         "spark": [round(float(z), 1) for z in s.loc[self.asof - pd.DateOffset(years=3):].iloc[::2]],
                         "why": ind.why, "transmits": ind.transmits, "src": ind.src,
                         "scored": ind.scored, "not_scored_why": ind.not_scored_why, "ns_tag": ind.ns_tag,
                         "charted": i in CHARTED})
        return {"name": name, "q": PILLAR_Q[[k for k, n in PILLARS.items() if n == name][0]],
                "score": score, "d13": d13, "level": level_of(score), "head": head, "bullets": bullets,
                "lede": head,
                "drivers": drivers, "offsets": offsets, "rows": rows,
                "spark": [round(float(z), 1) for z in P.loc[self.asof - pd.DateOffset(years=3):].iloc[::2]]}

    # ------------------------------------------------------------- per-link takeaway: one sentence + 2-4 bullets
    def takeaway(self, name, score, hot, cool):
        """Every sentence is conditional on the data, so the takeaway rewrites itself each run.
        Bullets are (label, text, scored?) - context bullets are flagged so the reader knows they do not move the score."""
        v, sc, R = self.v, self.sc, self.R
        g = lambda k, d=0: sc.get(k, d) if pd.notna(sc.get(k, np.nan)) else d
        B = []
        add = lambda lab, txt, i: B.append({"label": lab, "text": txt, "scored": REG[i].scored})
        if name == "Build-up":
            boom = v.get("credit_gap", 0) >= 2 or g("rzone") >= 80
            frothy = g("ebp_sentiment") >= 80
            eq = g("eq_val") >= 95
            head = ("A credit boom is under way" if boom else "No broad credit boom") + \
                   (", but credit is priced for perfection" if frothy else "") + \
                   (" and equity valuations are at a record" if eq else "") + "."
            if frothy:
                add("Credit priced for perfection", f"Baa-10y spread {v['ebp_sentiment']:.2f}pp, tighter than "
                    f"{g('ebp_sentiment'):.0f}% of weeks since {self.since['ebp_sentiment']}. Tight pricing predicts "
                    "wider spreads about two years out.", "ebp_sentiment")
            if eq and g("margin") >= 95:
                add("Record valuation, on borrowed money", f"Equities are worth {v['eq_val']:.0f}% of GDP and net margin "
                    f"debt is {v['margin']:.2f}% of market value, both records. Leverage turns a sell-off into forced "
                    "selling.", "eq_val")
            elif eq:
                add("Record equity valuation", f"Equities are worth {v['eq_val']:.0f}% of GDP. Without leverage behind "
                    "it, this is a growth risk more than a banking risk.", "eq_val")
            if not boom:
                add("Borrowing is not the problem", f"Private credit is {abs(v['credit_gap']):.1f}pp of GDP below trend "
                    f"and household debt is down to {v['hh_debt']:.0f}% of GDP.", "credit_gap")
            if g("corp_debt") >= 70:
                add("Except companies", f"Corporate debt is {v['corp_debt']:.0f}% of GDP ({ordn(g('corp_debt'))} "
                    "percentile), where AI capex and private credit financing sit.", "corp_debt")
            if g("low_vol") >= 65:
                add("Calm breeds leverage", f"{self.reading('low_vol')}; long calm spells precede risk-taking.", "low_vol")
        elif name == "Contagion":
            coupled = g("absorption") >= 70 or g("dcovar_max") >= 70
            thin = g("srisk_gdp") >= 60
            head = ("Losses would spread quickly" if coupled else "Losses would not spread easily") + \
                   (", and capital is thin." if thin else ", but capital buffers are thick enough to absorb them." if coupled
                    else ".")
            if g("absorption") >= 60:
                add("Moving as one trade", f"{self.reading('absorption')} ({ordn(g('absorption'))} percentile).", "absorption")
            add("Where it would start", f"Distress at {self.worst_sector} adds the most to the system's worst weeks "
                f"(+{v['dcovar_max']:.1f}% a week); private credit's listed proxies sit mid-pack "
                f"(+{v['dcovar_private']:.1f}%).", "dcovar_max")
            add("Capital buffer", f"{self.reading('srisk_gdp')} after a 40% crash, "
                f"{'low' if g('srisk_gdp') < 40 else 'high'} by history ({ordn(g('srisk_gdp'))} percentile).", "srisk_gdp")
            if g("hf_repo") >= 90:
                add("Hedge funds levered up", f"Hedge fund repo borrowing is {self.reading('hf_repo')} and leveraged funds "
                    f"are ${v['lf_ust_short']:.2f}tn net short Treasury futures. Repo borrowing is "
                    f"{v['hf_repo'] / R['extra']['hf']['repo'].loc['2019-09':'2020-03'].max():.1f}x its size before the "
                    "March 2020 basis-trade unwind.", "hf_repo")
            if g("stock_bond") >= 85:
                add("Hedge not working", f"Stocks and bonds are moving together ({v['stock_bond']:+.2f} correlation), "
                    "so diversified portfolios would lose on both legs.", "stock_bond")
        elif name == "Shock absorbers":
            no_cushion = g("rrp_buffer") >= 80
            squeeze = v.get("sofr_iorb", -1) > 0
            head = ("The liquidity cushion is gone" if no_cushion else "Liquidity buffers are intact") + \
                   (" and funding is tightening." if squeeze else
                    ", but reserves still hold funding markets steady." if no_cushion else ".")
            if no_cushion:
                add("Cushion drained", f"ON RRP is {self.reading('rrp_buffer')}; the next liquidity drain comes "
                    "straight out of bank reserves.", "rrp_buffer")
            add("Floor still holds", f"Reserves are {self.reading('reserves_gdp')} and repo trades "
                f"{abs(v['sofr_iorb']):.1f}bp {'above' if squeeze else 'below'} the Fed's floor.", "sofr_iorb")
            if g("cp_spread") <= 30:
                add("Bank funding cheap", f"3-month financial CP costs {v['cp_spread']:.0f}bp over bills, "
                    f"lower than {100 - g('cp_spread'):.0f}% of weeks.", "cp_spread")
            if pd.notna(v.get("xccy_basis", np.nan)):
                add("Offshore dollars", f"The USD/JPY basis is {v['xccy_basis']:.0f}bp, "
                    f"{'wider' if g('xccy_basis') >= 70 else 'no wider'} than usual since 2010 "
                    f"({ordn(g('xccy_basis'))} percentile); March 2020 reached "
                    f"{self.panel['xccy_basis'].loc['2020-03'].min():.0f}bp.", "xccy_basis")
            if v.get("srf_usage", 0) >= 1:
                add("Backstop in use", f"Standing Repo Facility take-up is {self.reading('srf_usage')}.", "srf_usage")
        else:  # Trigger
            tested = score >= 65
            cracks = []
            if g("intl_liq") >= 90:
                cracks.append("foreign bond liquidity")
            if g("bdc_pb") >= 80:
                cracks.append("private-credit marks")
            if g("move") >= 65 and g("vix", 100) < 50:
                cracks.append("Treasury volatility")
            if g("pc_mark") >= 75 and "private-credit marks" not in cracks:
                cracks.append("private-credit marks")
            if g("bank_rel_dd") >= 75:
                cracks.append("regional banks")
            head = ("The system is being tested" if tested else "Nothing is testing the system yet") + \
                   (f"; {(', '.join(cracks[:-1]) + ' and ' + cracks[-1]) if len(cracks) > 1 else cracks[0]} {'are' if len(cracks) > 1 else 'is'} the "
                    f"crack{'s' if len(cracks) > 1 else ''} to watch." if cracks else ".")
            add("Stress below normal" if v["stlfsi"] < 0 else "Stress above normal",
                f"St. Louis Fed index {v['stlfsi']:+.2f}, Chicago Fed NFCI {v['nfci']:+.2f}; spreads "
                f"{v['credit_widen'] * 100:+.0f}bp over 13 weeks.", "stlfsi")
            if "Treasury volatility" in cracks:
                add("Treasury volatility", f"MOVE {v['move']:.0f} ({ordn(g('move'))} percentile) while VIX is "
                    f"{v['vix']:.0f}: the collateral market is less calm than equities.", "move")
            if "private-credit marks" in cracks and g("bdc_pb") < 80:
                add("Private credit", f"Listed BDCs are {v['pc_mark']:.0f}% behind HY bonds from their 1-year high; "
                    "the market is marking direct loans down faster than reported NAVs.", "pc_mark")
            if g("intl_liq") >= 90:
                add("Foreign bond markets", f"JGB and gilt markets are less liquid than {g('intl_liq'):.0f}% of weeks since "
                    f"2007, while Treasuries are {'normal' if g('ust_liq', 50) < 70 else 'also strained'}.", "intl_liq")
            if g("bdc_pb") >= 80:
                add("Private credit marks", f"Listed BDCs trade {v['bdc_pb']:.0f}% below reported NAV, wider than "
                    f"{g('bdc_pb'):.0f}% of months since 2008: the market doubts the loan marks.", "bdc_pb")
            if g("bank_rel_dd") >= 60:
                add("Regional banks", f"{self.reading('bank_rel_dd')}.", "bank_rel_dd")
        return head, B[:5 if name in ("Contagion", "Trigger") else 4]

    # ------------------------------------------------------------- headline
    def headline(self, links):
        idx = self.R["index"].loc[:self.asof].dropna()
        x, d13 = float(idx.iloc[-1]), float(idx.iloc[-1] - idx.iloc[-14])
        idx = idx.loc["2005":]                       # all four links observed from here
        pct = float((idx <= x).mean() * 100)
        trend = "rising" if d13 > 3 else "falling" if d13 < -3 else "broadly unchanged"
        peaks = [(n, float(idx.loc[pd.Timestamp(d) - pd.Timedelta(days=21):pd.Timestamp(d) + pd.Timedelta(days=21)].max()))
                 for d, n in CRISES]
        below = [n for n, p in peaks if p > x]
        hi = max(links, key=lambda l: l["score"])
        lo = min(links, key=lambda l: l["score"])
        gar = self.R["gar"].dropna().iloc[-1]
        title = (f"Systemic risk is {level_of(x).lower()}: excesses are building and losses would spread, "
                 f"but nothing is testing the system yet") if links[3]["score"] < 45 and level_of(x) in ("Moderate", "Low") \
            else f"Systemic risk is {level_of(x).lower()}"
        summary = (f"The Systemic Risk Index is {x:.0f} out of 100, {trend} over the past 3 months ({d13:+.0f}), "
                   f"and higher than {pct:.0f}% of weeks since {idx.index[0].year}. "
                   + (f"That is below the peak of every stress episode since 2008. " if not [n for n, p in peaks if p <= x] else
                      f"That is already above the peak reached in {', '.join(n for n, p in peaks if p <= x)}. ") +
                   f"{hi['name']} is the riskiest link ({hi['score']:.0f}); {lo['name'].lower()} is the "
                   f"calmest ({lo['score']:.0f}).")
        # what to watch: biggest 13-week deteriorations among scored indicators
        d = self.sc13.dropna()
        d = d[[c for c in d.index if REG.get(c) and REG[c].pillar in PILLARS]].sort_values(ascending=False)
        watch = [{"name": REG[i].name, "reading": self.reading(i), "d13": float(d[i]), "score": float(self.sc[i])}
                 for i in d.index[:3] if d[i] > 5]
        return {"value": x, "d13": d13, "level": level_of(x), "pct": pct, "title": title, "summary": summary,
                "peaks": [{"name": n, "value": p} for n, p in peaks],
                "gar": {"q05": float(gar["q05"]), "q50": float(gar["q50"]), "date": gar.name.strftime("%b %Y"),
                        "rec": float(self.panel["rec_prob"].dropna().iloc[-1])},
                "watch": watch}

    # ------------------------------------------------------------- chart titles (the takeaway)
    def chart_titles(self):
        R, v, sc = self.R, self.v, self.sc
        net = R["dy"]["latest"]["net"].sort_values()
        dco = R["dcovar"].rolling(4, min_periods=2).mean().loc[:self.asof].dropna(how="all").iloc[-1].sort_values(ascending=False)
        sr_sec = R["srisk_sector"].loc[:self.asof].dropna(how="all").iloc[-1].sort_values(ascending=False)
        res_tn = R["fred"]["WRESBAL"].dropna().iloc[-1] / 1e6
        return {
            "spread": (f"Credit is priced for perfection: the Baa-10y spread is {v['ebp_sentiment']:.2f}pp, tighter than "
                       f"{sc['ebp_sentiment']:.0f}% of weeks since {self.since['ebp_sentiment']}"
                       if sc["ebp_sentiment"] >= 80 else
                       f"Credit pricing is not stretched: Baa-10y spread {v['ebp_sentiment']:.2f}pp"),
            "gap": (f"No credit boom: private credit is {abs(v['credit_gap']):.1f}pp of GDP below its long-run trend"
                    if v["credit_gap"] < 2 else f"Credit boom: private credit is {v['credit_gap']:.1f}pp above trend"),
            "srisk": (f"A 40% equity crash would leave US financials ${R['srisk_total'].loc[:self.asof].dropna().iloc[-1]:.0f}bn short of "
                      f"capital ({v['srisk_gdp']:.1f}% of GDP), {sr_sec.iloc[0] / sr_sec.sum() * 100:.0f}% of it at {sr_sec.index[0]}"),
            "dcovar": (f"Distress at {dco.index[0]} would hurt the system most, adding {dco.iloc[0]:.1f}% to its worst-week "
                       f"loss; private credit ({dco.get('Alt managers', np.nan):.1f}% alts, {dco.get('BDCs', np.nan):.1f}% BDCs) sits mid-pack"),
            "dy": (f"Shocks are flowing out of {net.index[-1]} and {net.index[-2]} and into "
                   f"{net.index[0]} and {net.index[1]}"),
            "plumb": (f"The RRP cushion is gone (${v['rrp_buffer']:.1f}bn), but ${res_tn:.1f}tn of reserves keep repo "
                      f"{abs(v['sofr_iorb']):.1f}bp {'below' if v['sofr_iorb'] < 0 else 'above'} the Fed floor"),
            "stress": (f"Realised stress is below normal: St. Louis Fed index {v['stlfsi']:+.2f}, regional banks "
                       f"{v['bank_rel_dd']:.0f}% behind the market" if v["stlfsi"] < 0 else
                       f"Stress is above normal: St. Louis Fed index {v['stlfsi']:+.2f}"),
            "valuation": (f"Equities are worth {v['eq_val']:.0f}% of GDP"
                          + (", a record" if sc.get("eq_val", 0) >= 99.5 else f", {sc.get('eq_val', 0):.0f}th percentile")
                          + f"; real house prices are {v['house_gap']:+.1f}% vs trend, so the property channel is quiet"
                          if abs(v["house_gap"]) < 5 else
                          f"Equities are worth {v['eq_val']:.0f}% of GDP; real house prices are {v['house_gap']:+.1f}% vs trend"),
            "stockbond": (f"Stocks and bonds are moving together: 3-month correlation {v['stock_bond']:+.2f}, higher than "
                          f"{sc.get('stock_bond', 0):.0f}% of weeks since 2003" if v["stock_bond"] > 0.2 else
                          f"Bonds are still hedging stocks: 3-month correlation {v['stock_bond']:+.2f}"),
            "vol": (f"Equity volatility is calm (VIX {v['vix']:.0f}) but Treasury volatility is not (MOVE {v['move']:.0f}); "
                    f"credit spreads {v['credit_widen'] * 100:+.0f}bp over 13 weeks"
                    if sc.get("move", 0) >= 65 and sc.get("vix", 100) < 50 else
                    f"VIX {v['vix']:.0f}, MOVE {v['move']:.0f}; credit spreads {v['credit_widen'] * 100:+.0f}bp over 13 weeks"),
            "hf": (f"Hedge fund Treasury leverage is at a record: ${v['hf_repo']:.1f}tn of repo borrowing and "
                   f"${v['lf_ust_short']:.2f}tn net short in futures" if sc.get("hf_repo", 0) >= 95 else
                   f"Hedge fund repo borrowing ${v['hf_repo']:.1f}tn; leveraged funds ${v['lf_ust_short']:.2f}tn net short futures"),
            "xccy": (f"Offshore dollar funding is {'tight' if sc.get('xccy_basis', 0) >= 70 else 'calm'}: USD/JPY basis "
                     f"{v.get('xccy_basis', float('nan')):.0f}bp vs {self.panel['xccy_basis'].loc['2020-03'].min():.0f}bp in March 2020"
                     if "xccy_basis" in self.panel and pd.notna(v.get("xccy_basis", np.nan)) else ""),
            "liq": (f"Treasuries trade normally ({v.get('ust_liq', float('nan')):.1f}bp), but JGB and gilt liquidity is "
                    f"near its worst ({v.get('intl_liq', float('nan')):.1f}bp, {sc.get('intl_liq', 0):.0f}th percentile)"
                    if sc.get("intl_liq", 0) >= 85 and sc.get("ust_liq", 100) < 70 else
                    f"Government bond liquidity: Treasuries {v.get('ust_liq', float('nan')):.1f}bp off the fitted curve"),
            "recprob": f"The yield curve puts the chance of a US recession within a year at {v['rec_prob']:.0f}%",
            "gar": (f"Even in a bad case, growth stays positive: 5th-percentile GDP growth over the next year is "
                    f"{R['gar'].dropna().iloc[-1]['q05']:+.1f}%" if R["gar"].dropna().iloc[-1]["q05"] > 0 else
                    f"The bad-case growth path is a recession: 5th percentile {R['gar'].dropna().iloc[-1]['q05']:+.1f}%"),
        }


def payload(R: dict) -> dict:
    st = Story(R)
    links = [st.link(n) for n in PILLARS.values()]
    head = st.headline(links)
    asof = st.asof
    fred = R["fred"]
    idx = R["index"].loc[:asof]
    ctx = [{"name": i.name, "owner": i.owner, "why": i.why} for i in REGISTRY if i.pillar == "context"]
    firm = R["srisk_firm"].head(10).reset_index().rename(columns={"index": "ticker"})
    dco_now = R["dcovar"].rolling(4, min_periods=2).mean().loc[:asof].dropna(how="all").iloc[-1].sort_values()
    return {
        "meta": {"source": R["meta"]["source"],
                 "asof": pd.Timestamp(R["meta"].get("last_data", asof)).strftime("%d %b %Y"),
                 "run": (lambda t: (t.tz_localize("Asia/Singapore") if t.tzinfo is None else t.tz_convert("Asia/Singapore"))
                         .strftime("%d %b %Y %H:%M") + " SGT")(pd.Timestamp(R["meta"]["run_at"])),
                 "demo": "SYNTHETIC" in R["meta"]["source"].upper(),
                 "srisk_start": R["srisk_total"].first_valid_index().strftime("%b %Y"),
                 "levels": LEVELS},
        "head": head, "links": links, "titles": st.chart_titles(), "context": ctx,
        "index": _s(idx, "2005"),
        "crises": [{"x": d, "name": n} for d, n in CRISES],
        "pillars_hist": {c: _s(R["pillars"][c].loc[:asof].ewm(span=4).mean(), "2005", 2) for c in R["pillars"]},
        "spread": _s(fred["BAA10Y"].resample("W-FRI").last(), "1990"),
        "gap": _s(R["credit_gap"]["gap"], "1980"),
        "srisk": {c: _s(R["srisk_sector"][c].loc[:asof].resample("W-FRI").last()) for c in R["srisk_sector"]},
        "firms": json.loads(firm.to_json(orient="records")),
        "dcovar_now": {"y": list(dco_now.index), "x": [round(float(v), 2) for v in dco_now.values]},
        "dy_net": {k: round(float(v), 1) for k, v in R["dy"]["latest"]["net"].sort_values().items()},
        "plumb": {"sofr_iorb": _s(R["panel"]["sofr_iorb"].loc[:asof], "2019"),
                  "rrp": _s(fred["RRPONTSYD"].dropna().resample("W-FRI").last(), "2019", scale=1 / 1000),
                  "res": _s(fred["WRESBAL"].dropna().resample("W-FRI").last(), "2019", scale=1 / 1e6)},
        "stress": {"stlfsi": _s(R["panel"]["stlfsi"].loc[:asof], "2005"),
                   "kre": _s(R["panel"]["bank_rel_dd"].loc[:asof], "2005")},
        "gar": {k: _s(R["gar"][k], "2000") for k in R["gar"].columns},
        "valuation": {"eq": _s(R["extra"]["eq_val"], "1990"), "house": _s(R["extra"]["house_gap"], "1990")},
        "stockbond": _s(R["panel"]["stock_bond"].loc[:asof], "2004"),
        "bbg": None if not R.get("extra", {}).get("bbg") else {
            "xccy": {c: _s(R["extra"]["bbg"]["xccy"][c].loc[:asof], "2005", 2) for c in R["extra"]["bbg"]["xccy"]},
            "liq": {c: _s(R["extra"]["bbg"]["liq"][c].loc[:asof], "2007", 2) for c in R["extra"]["bbg"]["liq"]}},
        "hf": {"repo": _s(R["extra"]["hf"]["repo"].loc[:asof]), "short": _s(R["extra"]["hf"]["short"].loc[:asof])},
        "vol": {"vix": _s(R["panel"]["vix"].loc[:asof], "2005"), "move": _s(R["panel"]["move"].loc[:asof], "2005"),
                "baa": _s(fred["BAA10Y"].resample("W-FRI").last().loc[:asof], "2005")},
        "recprob": _s(R["extra"]["rec_prob"].loc[:asof], "1985"),
        "validation": None if not R.get("validation") else {
            k: [{"name": n, "r2": round(float(r["R2_oos"]), 3), "n": int(r["n"])} for n, r in v.iterrows()]
            for k, v in R["validation"].items()},
        "litmap": LITMAP,
        "hist": hist_payload(R, asof, [r["id"] for l in links for r in l["rows"] if not r.get("missing")]),
    }


def render(R: dict, standalone: bool = False) -> str:
    tpl = (Path(__file__).parent / "dashboard_template.html").read_text()
    data = json.dumps(payload(R), separators=(",", ":"), default=lambda o: None).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", data)
    if standalone:   # a full document for GitHub Pages (Claude artifacts add the doctype themselves)
        html = "<!doctype html>\n<html lang=\"en\">\n" + html + "\n</html>\n"
    return html


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="output/results.pkl")
    ap.add_argument("--out", default="systemic_risk_monitor.html")
    ap.add_argument("--standalone", action="store_true", help="full HTML document, for GitHub Pages")
    a = ap.parse_args()
    with open(a.results, "rb") as f:
        R = pickle.load(f)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(render(R, a.standalone))
    print("wrote", a.out)
