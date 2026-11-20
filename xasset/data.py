"""Public daily panel for the cross-asset decomposition.

Sources (no keys needed):
  US Treasury   daily par nominal and real (TIPS) yields: FRED H.15 history + Treasury's same-evening files
  Yahoo Finance equities, semis, DXY, FX, gold, Brent, copper, HYG/IEI, VIX, MOVE, banks, broker-dealers, energy, aluminium
  NY Fed        SOFR and its 99th percentile
  FRED          IORB / IOER, Chicago Fed NFCI
  OFR           Financial Stress Index and its sub-indices

The model inputs on the private Bloomberg build were 5pm New York closes. Public closes differ in timing
(futures settle 1:00-2:30pm NY, Yahoo FX bars end late London evening), so single days are noisier; see calibration.json.
"""
from __future__ import annotations
import io, json, urllib.request, warnings
import numpy as np
import pandas as pd

YAHOO = {'SPX': '^GSPC', 'SOX': '^SOX', 'USD': 'DX-Y.NYB', 'USDJPY': 'JPY=X', 'USDCNH': 'CNH=X', 'GOLD': 'GC=F',
         'BRENT': 'BZ=F', 'COPPER': 'HG=F', 'HYG': 'HYG', 'IEI': 'IEI', 'VIX': '^VIX', 'MOVE': '^MOVE',
         'BKX': '^BKX', 'XBD': '^XBD', 'ENERGY_EQ': 'XLE', 'ALU': 'ALI=F'}
FALLBACK = {'USDCNH': ['USDCNH=X', 'CNY=X']}
USED: dict = {}
LAST: dict = {}
PATCHED: list = []   # tickers whose latest bar came from a second, single-ticker request   # last real print of each core series (shown in status.json)   # which Yahoo ticker actually supplied each series
CORE = ['SPX', 'SOX', 'USD', 'USDJPY', 'USDCNH', 'GOLD', 'BRENT', 'COPPER', 'HYG', 'IEI', 'UST2', 'UST30', 'UST10', 'REAL10']
HY_DURATION = 3.5   # approx. spread duration of HYG; turns the HYG-vs-IEI return gap into bp of spread
TSY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
       "?type={t}&field_tdr_date_value={y}&page&_format=csv")


def _get(url, tries=4, timeout=60):
    import time
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def treasury(start_year=2009) -> pd.DataFrame:
    """Daily Treasury par yields: 2y, 10y, 30y nominal and 10y real, percent."""
    out = []
    for y in range(start_year, pd.Timestamp.today().year + 1):
        n = pd.read_csv(io.BytesIO(_get(TSY.format(y=y, t='daily_treasury_yield_curve'))))
        r = pd.read_csv(io.BytesIO(_get(TSY.format(y=y, t='daily_treasury_real_yield_curve'))))
        n['Date'] = pd.to_datetime(n['Date']); r['Date'] = pd.to_datetime(r['Date'])
        d = n.set_index('Date')[['2 Yr', '10 Yr', '30 Yr']].join(r.set_index('Date')[['10 YR']], how='left')
        out.append(d)
    d = pd.concat(out).sort_index()
    d = d[~d.index.duplicated()]
    d.columns = ['UST2', 'UST10', 'UST30', 'REAL10']
    return d.astype(float)


def yields() -> pd.DataFrame:
    """FRED H.15 history (same numbers as Treasury par yields, fast), extended with Treasury's own files for the
    last two years because FRED posts each day only on the next business day."""
    f = fred(['DGS2', 'DGS10', 'DGS30', 'DFII10']).rename(columns={'DGS2': 'UST2', 'DGS10': 'UST10', 'DGS30': 'UST30', 'DFII10': 'REAL10'})
    try:
        t = treasury(pd.Timestamp.today().year - 1)
    except Exception as e:
        warnings.warn(f'Treasury files failed, using FRED only: {e}')
        return f
    return t.combine_first(f)


def fred(series):
    from sysrisk.data import fetch_fred
    return fetch_fred(series, start='2008-01-01')


def yahoo(start='2008-01-01') -> pd.DataFrame:
    from sysrisk.data import FreeProvider
    px = FreeProvider().ohlc(list(YAHOO.values()), start)['close']
    inv = {v: k for k, v in YAHOO.items()}
    px = px.rename(columns=inv)
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    px = px[[c for c in YAHOO if c in px.columns]]
    # Yahoo's offshore-yuan series is patchy: fall back to other spellings, then onshore USDCNY (moves almost one for one)
    USED['USDCNH'] = 'CNH=X'
    if 'USDCNH' not in px or px['USDCNH'].notna().sum() < 1000:
        for t in FALLBACK['USDCNH']:
            try:
                x = FreeProvider().ohlc([t], start)['close']
                if t in x and x[t].notna().sum() >= 1000:
                    x.index = pd.to_datetime(x.index).tz_localize(None).normalize()
                    px['USDCNH'] = x[t].reindex(px.index); USED['USDCNH'] = t
                    break
            except Exception as e:
                warnings.warn(f'Yahoo {t} failed: {e}')
    # Yahoo's bulk download sometimes misses the latest bar of a few tickers (seen for HYG/IEI): re-ask those one by one
    try:
        import yfinance as yf
        ref = px['SPX'].dropna().index.max()
        for c, t in YAHOO.items():
            if c in CORE and c in px and px[c].dropna().index.max() < ref:
                h = yf.Ticker(t).history(period='1mo', auto_adjust=True)['Close']
                h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
                h = h[h.index > px[c].dropna().index.max()]
                if len(h):
                    px = px.reindex(px.index.union(h.index)); px.loc[h.index, c] = h.values
                    PATCHED.append(t)
    except Exception as e:
        warnings.warn(f'Yahoo latest-bar patch failed: {e}')
    print('Yahoo columns', {c: (str(px[c].first_valid_index())[:10], str(px[c].last_valid_index())[:10]) for c in px})
    return px


def nyfed_sofr(start='2018-04-02') -> pd.DataFrame:
    end = pd.Timestamp.today().strftime('%Y-%m-%d')
    d = json.loads(_get(f"https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate={start}&endDate={end}"))
    d = pd.DataFrame(d['refRates']); d['date'] = pd.to_datetime(d['effectiveDate'])
    d = d.set_index('date').sort_index()
    return pd.DataFrame({'SOFR': pd.to_numeric(d['percentRate'], errors='coerce'),
                         'SOFR99': pd.to_numeric(d['percentPercentile99'], errors='coerce')})


def ofr_fsi() -> pd.DataFrame:
    d = pd.read_csv(io.BytesIO(_get("https://www.financialresearch.gov/financial-stress-index/data/fsi.csv")), parse_dates=['Date'])
    d = d.set_index('Date').sort_index()
    m = {'OFR FSI': 'OFR_FSI', 'Funding': 'OFR_FUNDING', 'Safe assets': 'OFR_SAFE'}
    return d[[c for c in m if c in d]].rename(columns=m)


def assemble(px: pd.DataFrame, tsy: pd.DataFrame, sofr: pd.DataFrame | None = None, fr: pd.DataFrame | None = None,
             ofr: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per S&P 500 trading day. Short gaps (exchange holidays in one market) carried for up to 2 days.
    Rows after the last real print of any core series are cut, so a late source never shows as a zero move."""
    idx = px['SPX'].dropna().index
    p = px.reindex(idx).join(tsy.reindex(idx))
    allp = pd.concat([px, tsy], axis=1)
    LAST.clear(); LAST.update({c: str(allp[c].dropna().index.max().date()) for c in CORE if c in allp})
    last = min(allp[c].dropna().index.max() for c in CORE if c in p)
    p = p.ffill(limit=2)
    p = p[p.index <= last]
    p['BE10'] = p['UST10'] - p['REAL10']                       # same definition as FRED T10YIE
    p['HYPROXY'] = -(np.log(p['HYG']) - np.log(p['IEI'])) * 1e4 / HY_DURATION
    if sofr is not None and fr is not None:
        ior = pd.concat([fr['IOER'].dropna()[:'2021-07-28'], fr['IORB'].dropna()]).sort_index()
        ior = ior[~ior.index.duplicated()]
        s = sofr.join(ior.rename('IOR').reindex(sofr.index, method='ffill'))
        p = p.join(((s['SOFR'] - s['IOR']) * 100).rename('SOFR_IORB'))
        p = p.join(((s['SOFR99'] - s['IOR']) * 100).rename('SOFR99_IORB'))
    if fr is not None and 'NFCI' in fr:
        p = p.join(fr['NFCI'].dropna().reindex(p.index, method='ffill', limit=7).rename('NFCI'))
    if ofr is not None:
        p = p.join(ofr.reindex(p.index, method='ffill', limit=5))
    return p


def load(log=print) -> pd.DataFrame:
    log('Treasury yields'); tsy = yields()
    log('Yahoo prices'); px = yahoo()
    miss = [c for c in CORE if c not in px.columns and c not in tsy.columns]
    if miss:
        raise RuntimeError(f'missing core series: {miss}')
    sofr = fr = ofr = None
    try:
        sofr = nyfed_sofr()
    except Exception as e:
        warnings.warn(f'NY Fed SOFR failed: {e}')
    try:
        fr = fred(['IORB', 'IOER', 'NFCI'])
    except Exception as e:
        warnings.warn(f'FRED failed: {e}')
    try:
        ofr = ofr_fsi()
    except Exception as e:
        warnings.warn(f'OFR FSI failed: {e}')
    return assemble(px, tsy, sofr, fr, ofr)
