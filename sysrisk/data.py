"""
Data providers. All expose the same interface so the pipeline is source-agnostic:

    ohlc(tickers, start)        -> dict(open/high/low/close -> DataFrame[date x ticker])
    fundamentals(tickers, start)-> (mkt_cap DataFrame daily, liabilities DataFrame quarterly), units: USD
    fred(series_ids, start)     -> DataFrame[date x series] (native frequency, NaN elsewhere)

Providers
  FreeProvider       Yahoo Finance (yfinance) + FRED public CSV endpoint (no API key needed)
  BloombergProvider  xbbg / blpapi for equities & fundamentals (long SRISK history), FRED for macro
  SyntheticProvider  fully simulated data with crisis episodes - for testing the pipeline offline.
                     NEVER read its output as a market view.
"""
from __future__ import annotations

import io
import urllib.request
import warnings

import numpy as np
import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


# ------------------------------------------------------------------ FRED (shared)
def fetch_fred(series: list[str], start: str = "1960-01-01") -> pd.DataFrame:
    out = {}
    import time
    for s in series:
        try:
            for k in range(4):
                try:
                    with urllib.request.urlopen(FRED_CSV.format(s), timeout=60) as r:
                        df = pd.read_csv(io.BytesIO(r.read()))
                    break
                except Exception:
                    if k == 3:
                        raise
                    time.sleep(5 * (k + 1))
            dcol = df.columns[0]
            ser = pd.to_numeric(df.iloc[:, 1], errors="coerce")
            ser.index = pd.to_datetime(df[dcol])
            out[s] = ser[ser.index >= start]
        except Exception as e:                                   # keep going; flag missing series
            warnings.warn(f"FRED {s} failed: {e}")
    return pd.DataFrame(out).sort_index()


# ------------------------------------------------------------------ Free: Yahoo + FRED
class FreeProvider:
    name = "Yahoo Finance + FRED"

    def __init__(self):
        import yfinance as yf                                      # noqa: F401  (fail early if missing)
        self.yf = yf

    def ohlc(self, tickers, start, tries: int = 5):
        """Yahoo rate-limits shared IPs (cloud runners). Retry with backoff; then retry any tickers still empty."""
        import time
        d = None
        for k in range(tries):
            try:
                d = self.yf.download(list(tickers), start=start, auto_adjust=True, progress=False,
                                     group_by="column", threads=False)
                if d is not None and not d.empty:
                    break
            except Exception as e:
                warnings.warn(f"Yahoo attempt {k + 1} failed: {e}")
            time.sleep(15 * (k + 1))
        if d is None or d.empty:
            raise RuntimeError("Yahoo Finance returned no data after retries")
        out = {k.lower(): d[k] for k in ["Open", "High", "Low", "Close"]}
        missing = [t for t in tickers if t not in out["close"] or out["close"][t].dropna().empty]
        for t in missing:
            for k in range(3):
                time.sleep(10 * (k + 1))
                try:
                    x = self.yf.download(t, start=start, auto_adjust=True, progress=False)
                    if x is not None and not x.empty:
                        for f in ["Open", "High", "Low", "Close"]:
                            col = x[f]
                            out[f.lower()][t] = col.iloc[:, 0] if hasattr(col, "columns") else col
                        break
                except Exception:
                    pass
        still = [t for t in tickers if t not in out["close"] or out["close"][t].dropna().empty]
        if still:
            warnings.warn(f"Yahoo: no data for {still}")
        return out

    def fundamentals(self, tickers, start):
        """
        Market cap = unadjusted close x shares outstanding (time-varying where Yahoo has it).
        Liabilities = 'Total Liabilities Net Minority Interest' from quarterly balance sheets.
        CAVEAT: Yahoo only returns ~5-8 quarters of balance sheets. Earlier dates are back-filled
        with the earliest available value and flagged; use BloombergProvider for full history.
        """
        px = self.yf.download(list(tickers), start=start, auto_adjust=False, progress=False)["Close"]
        caps, liabs = {}, {}
        for t in tickers:
            tk = self.yf.Ticker(t)
            try:
                sh = tk.get_shares_full(start=start)
                sh = sh[~sh.index.duplicated(keep="last")]
                sh.index = sh.index.tz_localize(None).normalize()
                sh = sh.reindex(px.index, method="ffill").bfill()
            except Exception:
                sh = pd.Series(tk.info.get("sharesOutstanding", np.nan), index=px.index)
            caps[t] = px[t] * sh
            parts = []
            for bs, lag in [(tk.balance_sheet, 75), (tk.quarterly_balance_sheet, 45)]:   # annual + quarterly
                try:
                    row = next(r for r in ["Total Liabilities Net Minority Interest", "Total Liab"] if r in bs.index)
                    l = bs.loc[row].astype(float).dropna()
                    l.index = pd.to_datetime(l.index) + pd.Timedelta(days=lag)          # filing lag
                    parts.append(l)
                except Exception:
                    pass
            if parts:
                l = pd.concat(parts).sort_index()
                liabs[t] = l[~l.index.duplicated(keep="last")]
            else:
                warnings.warn(f"no liabilities for {t}")
        return pd.DataFrame(caps), pd.DataFrame(liabs).sort_index()

    def fred(self, series, start):
        return fetch_fred(series, start)


# ------------------------------------------------------------------ Bloomberg
class BloombergProvider(FreeProvider):
    """
    Requires a Bloomberg Terminal session on the same machine + `pip install xbbg blpapi`.
    Equities: '<TICKER> US Equity' (edit `bbg_map` for non-US / ETFs).
    Fields: PX_OPEN/PX_HIGH/PX_LOW/PX_LAST, CUR_MKT_CAP (USD mn), BS_TOT_LIAB2 (USD mn, quarterly).
    Macro still comes from FRED (free, identical series).
    """
    name = "Bloomberg + FRED"

    def __init__(self, bbg_map: dict | None = None):
        from xbbg import blp
        self.blp = blp
        self.bbg_map = bbg_map or {}

    def _t(self, t):
        if t in self.bbg_map:
            return self.bbg_map[t]
        if t.startswith("^"):
            return {"^GSPC": "SPX Index", "^VIX": "VIX Index", "^MOVE": "MOVE Index"}.get(t, t)
        return f"{t} US Equity"

    def ohlc(self, tickers, start):
        bt = {self._t(t): t for t in tickers}
        d = self.blp.bdh(list(bt), ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST"], start)
        out = {}
        for k, f in zip(["open", "high", "low", "close"], ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST"]):
            x = d.xs(f, axis=1, level=1)
            out[k] = x.rename(columns=bt)
        return out

    def fundamentals(self, tickers, start):
        bt = {self._t(t): t for t in tickers}
        cap = self.blp.bdh(list(bt), "CUR_MKT_CAP", start).droplevel(1, axis=1).rename(columns=bt) * 1e6
        liab = self.blp.bdh(list(bt), "BS_TOT_LIAB2", start, Per="Q").droplevel(1, axis=1).rename(columns=bt) * 1e6
        liab.index = pd.to_datetime(liab.index) + pd.Timedelta(days=45)
        return cap, liab


# ------------------------------------------------------------------ Synthetic
class SyntheticProvider:
    """
    Simulated world with crisis episodes (2008, 2011, 2020, 2023 regional-bank, 2025-26 private-credit
    wobble). Factor structure: market + financial + sector + idiosyncratic, with crisis-time vol AND
    correlation spikes so every model has something to detect. Purely for pipeline testing.
    """
    name = "SYNTHETIC DEMO DATA"

    EPISODES = [  # (start, peak, end, intensity, sectors hit hardest)
        ("2007-07-15", "2008-10-15", "2009-06-30", 4.0, ["US G-SIB banks", "Insurers", "Brokers/exch"]),
        ("2011-07-20", "2011-09-20", "2011-12-31", 1.8, ["US G-SIB banks"]),
        ("2020-02-20", "2020-03-20", "2020-06-30", 4.5, ["Insurers", "BDCs"]),
        ("2022-03-01", "2022-10-01", "2022-12-31", 1.5, []),
        ("2023-03-01", "2023-03-20", "2023-06-30", 2.5, ["US regional banks"]),
        ("2025-03-15", "2025-04-10", "2025-06-30", 2.2, ["Alt managers", "BDCs"]),
    ]

    def __init__(self, seed: int = 7):
        from .config import FIN_UNIVERSE
        self.rng = np.random.default_rng(seed)
        self.universe = FIN_UNIVERSE
        self.idx = pd.bdate_range("2003-01-01", "2026-10-14")
        self._build_stress()
        self._sim = {}

    def _build_stress(self):
        s = pd.Series(0.0, index=self.idx)
        self.sector_stress = {}
        for st, pk, en, inten, secs in self.EPISODES:
            st, pk, en = map(pd.Timestamp, (st, pk, en))
            up = (self.idx >= st) & (self.idx <= pk)
            dn = (self.idx > pk) & (self.idx <= en)
            bump = pd.Series(0.0, index=self.idx)
            bump[up] = np.linspace(0, 1, up.sum()) ** 2
            bump[dn] = np.linspace(1, 0, dn.sum()) ** 0.7
            s = np.maximum(s, bump * inten / 4.5)
            for sec in secs:
                self.sector_stress[sec] = np.maximum(self.sector_stress.get(sec, 0 * bump), bump)
        self.stress = s                                   # 0..1 system stress driver

    # ---------- equities
    def _simulate_equities(self, tickers):
        key = tuple(sorted(tickers))
        if key in self._sim:
            return self._sim[key]
        n = len(self.idx)
        rng = self.rng
        s = self.stress.values
        vol_mult = 1 + 3.5 * s
        f_mkt = rng.standard_t(5, n) * 0.0095 * vol_mult / np.sqrt(5 / 3) - 0.004 * s * (s > 0.3)
        f_fin = rng.standard_normal(n) * 0.006 * vol_mult
        sec_of = {t: sec for sec, ts in self.universe.items() for t in ts}
        sec_f = {sec: rng.standard_normal(n) * 0.007 * (1 + 3 * self.sector_stress.get(sec, 0 * self.stress).values)
                 - 0.006 * self.sector_stress.get(sec, 0 * self.stress).values for sec in self.universe}
        beta_fin = {"US G-SIB banks": 1.2, "US regional banks": 1.1, "Insurers": 1.0, "Alt managers": 0.9,
                    "BDCs": 0.7, "Brokers/exch": 0.9}
        rets = {}
        for t in tickers:
            sec = sec_of.get(t)
            eps = rng.standard_normal(n) * 0.011
            if t in ("^GSPC", "SPY"):
                r = f_mkt
            elif t == "^VIX":
                continue
            elif sec is None:                        # ETFs / other assets: market loading + own noise
                b = {"HYG": 0.25, "LQD": 0.08, "IEF": -0.15, "GLD": 0.05, "UUP": -0.1, "USO": 1.0,
                     "EEM": 1.1, "KBE": 1.2, "KRE": 1.25, "XLF": 1.15, "BIZD": 0.8, "PSP": 1.1}.get(t, 1.0)
                extra = f_fin if t in ("KBE", "KRE", "XLF", "BIZD", "PSP") else 0
                rr = sec_f["US regional banks"] if t == "KRE" else (sec_f["BDCs"] if t == "BIZD" else 0)
                r = b * f_mkt + 0.8 * np.asarray(extra) + 0.6 * np.asarray(rr) + eps * 0.5 * vol_mult
            else:
                r = 1.0 * f_mkt + beta_fin[sec] * f_fin + sec_f[sec] + eps * (1 + s)
            rets[t] = r + 0.0003
        R = pd.DataFrame(rets, index=self.idx)
        close = 50 * np.exp(R.cumsum())
        rng_hl = np.abs(rng.standard_normal(R.shape)) * (0.006 * (1 + 3 * s))[:, None] + R.abs().values * 0.6
        high = close * np.exp(rng_hl * 0.6)
        low = close * np.exp(-rng_hl * 0.6)
        vix = pd.Series(13 + 55 * s + 2 * rng.standard_normal(n).cumsum() * 0 + np.abs(rng.normal(0, 1.5, n)),
                        index=self.idx)
        out = {"close": close, "high": high, "low": low, "open": close.shift(1).bfill(), "vix": vix}
        self._sim[key] = out
        return out

    def ohlc(self, tickers, start):
        sim = self._simulate_equities(tickers)
        out = {k: sim[k].loc[start:] for k in ["open", "high", "low", "close"]}
        if "^VIX" in tickers:
            for k in out:
                out[k] = out[k].assign(**{"^VIX": sim["vix"].loc[start:]})
        return out

    def fundamentals(self, tickers, start):
        sim = self._simulate_equities(tickers)
        lev = {"US G-SIB banks": 11, "US regional banks": 10, "Insurers": 13, "Alt managers": 3.5,
               "BDCs": 1.2, "Brokers/exch": 5}
        sec_of = {t: sec for sec, ts in self.universe.items() for t in ts}
        size = {t: self.rng.uniform(20, 300) * 1e9 for t in tickers}
        cap = sim["close"][[t for t in tickers if t in sec_of]].apply(
            lambda c: c / c.iloc[0] * size[c.name])
        q = cap.resample("QE").last()
        liab = q.apply(lambda c: c.iloc[0] * (lev[sec_of[c.name]] - 1) * (1 + 0.02 * np.arange(len(c))) ** 0.5)
        # book leverage creeps up into 2007 and for alt managers into 2025
        boost = pd.Series(1.0, index=q.index)
        boost[(q.index >= "2005") & (q.index < "2008-10")] = np.linspace(1, 1.35, ((q.index >= "2005") & (q.index < "2008-10")).sum())
        liab = liab.mul(boost, axis=0)
        liab.index = liab.index + pd.Timedelta(days=45)
        return cap.loc[start:], liab.loc[start:]

    # ---------- macro
    def fred(self, series, start):
        rng = self.rng
        d = pd.date_range("1960-01-01", "2026-10-14", freq="D")
        st = self.stress.reindex(d).fillna(0)
        st_q = st.resample("QE").mean()
        qi = st_q.index
        t = np.arange(len(qi))
        out = {}
        # credit/GDP: secular rise, boom 2002-08, deleverage, mild re-rise from 2022
        cg = 95 + 0.55 * t + 6 * np.sin(t / 22)
        boom = (qi >= "2002") & (qi <= "2008-12")
        cg[boom] += np.linspace(0, 22, boom.sum())
        post = qi > "2008-12"
        cg[post] += 22 - np.minimum(np.arange(post.sum()) * 1.1, 34)
        late = qi >= "2022"
        cg[late] += np.linspace(0, 9, late.sum())
        out["QUSPAM770A"] = pd.Series(cg + rng.normal(0, 0.6, len(qi)), qi)
        gdp_g = 0.006 - 0.025 * st_q.values + rng.normal(0, 0.005, len(qi))
        gdp_g[(qi >= "1974") & (qi <= "1975-03")] -= 0.01
        gdp_g[(qi >= "1980") & (qi <= "1982-09")] -= 0.008
        out["GDPC1"] = pd.Series(3000 * np.exp(np.cumsum(gdp_g)), qi)
        out["GDP"] = out["GDPC1"] * np.exp(np.cumsum(np.full(len(qi), 0.008)))
        out["HDTGPDUSQ163N"] = pd.Series(np.clip(45 + 0.3 * t - 0.002 * t ** 1.9 + rng.normal(0, .5, len(qi)), 40, 99), qi)
        out["BCNSDODNS"] = out["GDP"] * pd.Series(0.35 + 0.0015 * t + 0.04 * (qi >= "2020"), qi)
        out["GFDEGDQ188S"] = pd.Series(35 + 0.12 * t + 15 * (qi >= "2009") + 15 * (qi >= "2020"), qi)
        out["CSUSHPINSA"] = pd.Series(np.exp(np.cumsum(0.012 - 0.06 * ((qi >= "2007") & (qi <= "2011")) / 4
                                                       + rng.normal(0, .004, len(qi)))) * 20, qi)
        w = pd.date_range("1971-01-08", "2026-10-09", freq="W-FRI")
        sw = st.reindex(w, method="ffill").values
        ar = pd.Series(rng.normal(0, .08, len(w))).ewm(alpha=.05).mean().values
        out["NFCI"] = pd.Series(-0.45 + 2.6 * sw + ar, w)
        out["NFCILEVERAGE"] = pd.Series(-0.3 + 1.0 * sw + 0.4 * np.sin(np.arange(len(w)) / 160) + ar, w)
        out["STLFSI4"] = pd.Series(-0.6 + 6 * sw + 3 * ar, w)[w >= "1994"]
        bd = pd.bdate_range("1997-01-01", "2026-10-14")
        sb = st.reindex(bd).values
        noise = lambda sc: rng.normal(0, sc, len(bd))
        out["BAMLH0A0HYM2"] = pd.Series(3.2 + 15 * sb + pd.Series(noise(.05)).cumsum().clip(-1, 1).values, bd)
        out["BAMLC0A4CBBB"] = pd.Series(1.3 + 5 * sb + noise(0.03), bd)
        out["T10Y3M"] = pd.Series(1.5 + np.sin(np.arange(len(bd)) / 700) * 1.7 + noise(0.05), bd)
        out["DTB3"] = pd.Series(np.clip(2.5 + 2.5 * np.sin(np.arange(len(bd)) / 900), 0.02, None), bd)
        out["DCPF3M"] = out["DTB3"] + 0.15 + 2.5 * sb + np.abs(noise(0.04))
        ioer = out["DTB3"][(bd >= "2008-10-09") & (bd < "2021-07-29")] + 0.08
        out["IOER"] = ioer
        out["IORB"] = out["DTB3"][bd >= "2021-07-29"] + 0.1
        sofr_idx = bd[bd >= "2018-04-03"]
        base = pd.concat([ioer, out["IORB"]]).reindex(sofr_idx).ffill()
        qe = pd.Series(np.isin(sofr_idx.strftime("%m-%d"), ["03-31", "06-30", "09-30", "12-31"]), sofr_idx)
        out["SOFR"] = base - 0.05 + 0.08 * qe + 0.6 * (sofr_idx.strftime("%Y-%m") == "2019-09") + \
            0.05 * (sofr_idx >= "2025-09") + rng.normal(0, .015, len(sofr_idx))
        wk = pd.date_range("2002-12-18", "2026-10-08", freq="W-WED")
        res = np.interp(np.arange(len(wk)), [0, 300, 520, 600, 900, 1000, 1150, len(wk) - 1],
                        [0.02, 0.02, 2.7, 1.6, 3.9, 3.1, 3.3, 2.9]) * 1e6
        out["WRESBAL"] = pd.Series(res + rng.normal(0, 5e4, len(wk)), wk)
        rrp_i = bd[bd >= "2013-09-23"]
        rrp = np.interp(np.arange(len(rrp_i)), [0, 1900, 2200, 2400, 2800, len(rrp_i) - 1],
                        [100, 100, 2400, 2200, 300, 15])
        out["RRPONTSYD"] = pd.Series(np.clip(rrp + rng.normal(0, 20, len(rrp_i)), 0, None), rrp_i)
        srf = pd.Series(0.0, index=bd[bd >= "2021-07-29"])
        srf[srf.index >= "2025-09-01"] = np.abs(rng.normal(3, 6, (srf.index >= "2025-09-01").sum()))
        out["RPONTSYD"] = srf
        df = pd.DataFrame({k: v for k, v in out.items() if k in series})
        return df.loc[start:]


# ------------------------------------------------------------------ extra public sources (v4)
def _get_json(url, timeout=60, tries=3):
    import json, time
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def fetch_ofr(mnemonics: list[str]) -> pd.DataFrame:
    """OFR Hedge Fund Monitor (Form PF, CFTC TFF, SCOOS). https://www.financialresearch.gov/hedge-fund-monitor/"""
    out = {}
    for m in mnemonics:
        try:
            d = _get_json(f"https://data.financialresearch.gov/hf/v1/series/timeseries?mnemonic={m}")
            s = pd.Series({pd.Timestamp(a): b for a, b in d if b is not None}, dtype=float)
            out[m] = s.sort_index()
        except Exception as e:
            warnings.warn(f"OFR {m} failed: {e}")
    return pd.DataFrame(out)


def fetch_finra_margin() -> pd.DataFrame:
    """FINRA customer margin balances (monthly, $mn). Net margin debt = debit balances - free credit balances."""
    url = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
    with urllib.request.urlopen(url, timeout=60) as r:
        x = pd.read_excel(io.BytesIO(r.read()))
    x.columns = ["month", "debit", "free_cash", "free_margin"]
    x["month"] = pd.to_datetime(x["month"]) + pd.offsets.MonthEnd(0)
    x = x.set_index("month").sort_index().astype(float)
    x["net"] = x["debit"] - x["free_cash"] - x["free_margin"].fillna(0)
    return x


def fetch_nyfed_rate(rate: str = "tgcr", start: str = "2018-04-02") -> pd.Series:
    """NY Fed reference rate (sofr, tgcr, bgcr) history, percent."""
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    d = _get_json(f"https://markets.newyorkfed.org/api/rates/secured/{rate}/search.json?startDate={start}&endDate={end}")
    return pd.Series({pd.Timestamp(r["effectiveDate"]): float(r["percentRate"]) for r in d["refRates"]}).sort_index()


# ------------------------------------------------------------------ Bloomberg extracts (private build only)
def load_bbg(folder: str) -> dict:
    """Read the CSVs written by bbg_pull.py / bbg_pull2.py (long format: date, ticker, field, value)."""
    import os
    out = {}
    for name in ["spreads", "xccy", "xccy_liq", "cet1", "bdc_nav", "dealers", "srisk_fund"]:
        f = os.path.join(folder, f"{name}.csv")
        if os.path.exists(f):
            d = pd.read_csv(f, parse_dates=["date"])
            out[name] = d.pivot_table(index="date", columns=["ticker", "field"], values="value").sort_index()
    return out
