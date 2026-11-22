"""Cross-asset shock decomposition + liquidity monitor: daily public build.

    python -m xasset.pipeline --out site/xasset            # public data (GitHub Actions)
    python -m xasset.pipeline --panel panel.pkl --out out  # any prepared panel (tests, Bloomberg calibration)

Writes one JSON per dataset ({rows, meta}) plus index.html. The same JSON files feed the private Claude dashboard.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
import numpy as np
import pandas as pd
from xasset.model import build, changes, identify, narrative, NARR

HERE = Path(__file__).parent
V = ['EQ', 'TECH', 'Y2', 'SLOPE', 'RY', 'BE', 'USD', 'JPY', 'CNH', 'AU', 'OIL', 'CU', 'HY']
WIN, STEP, MAXD = 504, 21, 300
OUT = ['ALU', 'VIX', 'BKX', 'MOVE', 'ENERGY_EQ']
UNIT = {'EQ': '%', 'TECH': '%', 'Y2': 'bp', 'SLOPE': 'bp', 'RY': 'bp', 'BE': 'bp', 'USD': '%', 'JPY': '%', 'CNH': '%',
        'AU': '%', 'OIL': '%', 'CU': '%', 'HY': 'bp'}


# ------------------------------------------------------------------ 1. rolling estimation
def estimate(panel: pd.DataFrame, ndraw: int = 100000, log=print, spec=None, use_narr=True, min_acc=300, max_mult=15) -> dict:
    """504-day windows re-estimated every 21 days. Contributions averaged over accepted rotations (max 300 per window)."""
    shocks, SGN, NAMES, LAB = build(V, spec)
    d = changes(panel, V); idx = d.index; T = len(d)
    ends = list(range(T - 1, WIN - 1, -STEP))[::-1]
    if not ends:
        raise RuntimeError(f'only {T} complete daily rows; need more than {WIN}')
    nv, ns = len(V), len(NAMES)
    contrib = np.full((T, nv, ns), np.nan); shock = np.full((T, ns), np.nan); meta = []
    ox = pd.DataFrame(index=panel.index)
    for v in ['ALU', 'BKX', 'ENERGY_EQ']:
        if v in panel: ox[v] = np.log(panel[v]).diff() * 100
    for v in ['VIX', 'MOVE']:
        if v in panel: ox[v] = panel[v].diff()
    ox = ox.reindex(idx, columns=OUT); oc = np.full((T, len(OUT), ns + 1), np.nan)
    t0 = time.time(); prev = None
    for k, e in enumerate(ends):
        s = e - WIN + 1; X = d.iloc[s:e + 1].values; sd = X.std(axis=0)
        nr = narrative(NAMES, V, None, idx[s:e + 1]) if use_narr else []
        acc, _ = identify(X / sd, SGN, ndraw=ndraw, seed=k, narr=nr)
        m_ = 1
        while nr and len(acc) < min_acc and m_ < max_mult:     # narrative windows accept fewer rotations: draw more
            more, _ = identify(X / sd, SGN, ndraw=ndraw, seed=1000 * m_ + k, narr=nr); m_ += 1
            acc = more if len(acc) == 0 else (np.concatenate([acc, more]) if len(more) else acc)
        a = (prev + 1) if prev is not None else s; prev = e
        meta.append(dict(end=idx[e], n_acc=len(acc), n_narr=len(nr)))
        if len(acc) == 0:
            continue
        if len(acc) > MAXD:
            acc = acc[np.random.default_rng(k).choice(len(acc), MAXD, replace=False)]
        seg = slice(a, e + 1); U = d.iloc[seg].values / sd
        E = np.linalg.solve(acc, np.broadcast_to(U.T, (len(acc),) + U.T.shape))
        C = np.einsum('dvs,dst->dtvs', acc, E) * sd[None, None, :, None]
        contrib[seg] = C.mean(0); shock[seg] = E.mean(0).T
        med = np.median(acc, 0); Bm = acc[np.argmin(((acc - med) ** 2).sum((1, 2)))]
        Ew = np.linalg.solve(Bm, (X / sd).T).T; Es = np.linalg.solve(Bm, U.T).T
        for i, v in enumerate(OUT):
            y = ox[v].values[s:e + 1]; m = ~np.isnan(y)
            if m.sum() < 250:
                continue
            beta, *_ = np.linalg.lstsq(np.c_[Ew[m], np.ones(m.sum())], y[m], rcond=None)
            c = Es * beta[None, :ns]; oc[seg, i, :ns] = c; oc[seg, i, ns] = ox[v].values[seg] - c.sum(1)
    meta = pd.DataFrame(meta)
    log(f'{len(ends)} windows in {time.time() - t0:.0f}s; accepted per window min {meta.n_acc.min()} median {int(meta.n_acc.median())}')
    return dict(idx=idx, vars=V, names=NAMES, lab=LAB, shocks=shocks, contrib=contrib, shock=shock, data=d, meta=meta,
                out_contrib=oc, outx=ox)


# ------------------------------------------------------------------ 2. liquidity monitor
IND = {  # name: (label, unit, rule, stress_is_low)
    'liq10': ('Model: liquidity shock, 10d sum', 'σ', 'top 10% → Level 0', False),
    'fail': ('"Safe-asset fail" days in last 10', 'days', 'SPX < −1% & 10y yield up & gold down; ≥ 2 days → Level 0', False),
    'banks': ('Banks vs SPX, 60d', '%', 'underperformance = intermediary strain', True),
    'xbd': ('Broker-dealers vs 1y high', '%', '', True),
    'move': ('MOVE (UST vol)', 'index', 'highest 10% → Level 1', False),
    'ofr_safe': ('OFR FSI: safe assets', 'index', 'highest 10% → Level 1', False),
    'sofr': ('SOFR − IORB', 'bp', '≥ 8bp → Level 2', False),
    'sofr99': ('SOFR 99th pct − IORB', 'bp', '≥ 15bp → Level 2', False),
    'ofr_fund': ('OFR FSI: funding', 'index', 'tightest 5% → Level 2', False),
    'ofr_fsi': ('OFR Financial Stress Index', 'index', '> 0 = above-average stress', False),
    'nfci': ('Chicago Fed NFCI', 'index', '> 0 = tighter than average', False),
    'vix': ('VIX', 'index', '', False),
}
LAYER = {'A  Price signature': ['liq10', 'fail'], 'B  Intermediaries': ['banks', 'xbd'],
         'C  Market liquidity': ['move', 'ofr_safe'], 'D  Funding': ['sofr', 'sofr99', 'ofr_fund'],
         'Composite stress indices': ['ofr_fsi', 'nfci', 'vix']}


def monitor(p: pd.DataFrame, r: dict, carried: dict | None = None) -> dict:
    g = lambda c: p[c] if c in p else pd.Series(np.nan, index=p.index)
    liq = pd.Series(r['shock'][:, r['names'].index('Liquidity')], index=r['idx'])
    dd = r['data']
    fail = ((dd['EQ'] < -1) & (p['UST10'].reindex(dd.index).diff() > 0) & (dd['AU'] < 0)).astype(int)
    ind = pd.DataFrame(index=p.index)
    ind['liq10'] = liq.rolling(10).sum().reindex(p.index)
    ind['fail'] = fail.rolling(10).sum().reindex(p.index)
    ind['banks'] = (np.log(g('BKX')).diff(60) - np.log(p['SPX']).diff(60)) * 100
    ind['xbd'] = (g('XBD') / g('XBD').rolling(252, min_periods=60).max() - 1) * 100
    ind['move'] = g('MOVE'); ind['ofr_safe'] = g('OFR_SAFE')
    ind['sofr'] = g('SOFR_IORB').rolling(5, min_periods=1).median()
    ind['sofr99'] = g('SOFR99_IORB').rolling(5, min_periods=1).median()
    ind['ofr_fund'] = g('OFR_FUNDING'); ind['ofr_fsi'] = g('OFR_FSI'); ind['nfci'] = g('NFCI'); ind['vix'] = g('VIX')
    ind = ind[ind.index >= '2008-01-01']
    pct = pd.DataFrame({c: (-ind[c] if IND[c][3] else ind[c]).rank(pct=True) * 100 for c in ind}, index=ind.index)
    L0 = (pct['liq10'] >= 90) | (ind['fail'] >= 2)
    L1 = (pct[['move', 'ofr_safe']] >= 90).any(axis=1)
    L2 = (ind['sofr99'] >= 15) | (ind['sofr'] >= 8) | (pct['ofr_fund'] >= 95)
    # Bloomberg-only inputs (UST liquidity index, cross-currency basis) are carried from the last calibration run
    # and count only within 7 days of it.
    if carried and carried.get('as_of'):
        a = pd.Timestamp(carried['as_of']); fresh = (ind.index >= a) & (ind.index <= a + pd.Timedelta(days=7))
        if carried.get('L1'): L1 = L1 | fresh
        if carried.get('L2'): L2 = L2 | fresh
    L3 = L1 & L2 & ((ind['fail'] >= 3) | (pct['liq10'] >= 98))
    level = pd.Series(-1.0, index=ind.index)
    level[L0] = 0; level[L1] = np.maximum(level[L1], 1); level[L2] = np.maximum(level[L2], 2); level[L3] = 3
    lad = pd.DataFrame({'L0': L0, 'L1': L1, 'L2': L2, 'L3': L3, 'level': level})
    lad = lad[ind['liq10'].notna()]
    return dict(ind=ind, pct=pct, ladder=lad)


# ------------------------------------------------------------------ 3. export
EP = [('2013 taper tantrum', '2013-05-22', '2013-06-25', 'Monetary / term premium'),
      ('Oct 2023 term-premium selloff', '2023-09-20', '2023-10-19', 'Term premium'),
      ('Mar 2020 dash for cash', '2020-03-09', '2020-03-18', 'Liquidity'),
      ('Feb 2022 Ukraine oil shock', '2022-02-24', '2022-03-08', 'Oil supply / risk-off'),
      ('Jun 2022 75bp hike', '2022-06-10', '2022-06-16', 'Monetary'), ('Mar 2023 SVB', '2023-03-09', '2023-03-17', 'Risk-off'),
      ('Aug 2024 BOJ hike + carry unwind', '2024-07-31', '2024-08-05', 'Risk-off / carry'),
      ('11 Aug 2015 CNY devaluation', '2015-08-11', '2015-08-11', 'Growth (negative)'),
      ('Sep 2024 China stimulus', '2024-09-24', '2024-09-30', 'Growth'),
      ('27 Jan 2025 DeepSeek', '2025-01-27', '2025-01-27', 'AI / tech (negative)'),
      ('Apr 2025 Liberation Day', '2025-04-03', '2025-04-11', 'US risk premium'),
      ('Late Jan 2026 gold crash', '2026-01-29', '2026-02-03', 'Liquidity')]


def export(r: dict, m: dict, out: Path, calib: dict | None, source: str):
    out.mkdir(parents=True, exist_ok=True)
    idx, N, C = r['idx'], r['names'], r['contrib']
    OTH = [i for i, n in enumerate(N) if n.startswith('Other')]; NAM = [n for n in N if not n.startswith('Other')]
    SH = NAM + ['Other / unidentified']
    LAB = dict(r['lab']); LAB['TECH'] = 'Semis, beta-adj. (SOX)'
    col = lambda a: np.concatenate([a[..., [N.index(n) for n in NAM]], np.nansum(a[..., OTH], axis=-1, keepdims=True)], axis=-1)
    code = [{'label': f, 'value': (HERE / f).read_text(), 'type': 'code', 'lang': 'python'} for f in ['model.py', 'data.py', 'pipeline.py']]
    D = lambda t: pd.Timestamp(t).strftime('%Y-%m-%d')
    src = {'label': 'Inputs', 'value': source}
    sizes = {}

    def dump(name, rows, extra=()):
        f = out / f'{name}.json'
        f.write_text(json.dumps({'rows': rows, 'meta': list(extra) + code}, ensure_ascii=False, allow_nan=False))
        sizes[name] = len(rows)

    num = lambda x, k=4: None if x is None or not np.isfinite(x) else round(float(x), k)
    CC = col(C)
    rows = []
    for t in range(len(idx) - 30, len(idx)):
        for i, v in enumerate(V):
            act = float(r['data'].iloc[t][v])
            for j, s in enumerate(SH):
                rows.append({'date': D(idx[t]), 'asset': LAB[v], 'unit': UNIT[v], 'shock': s, 'value': num(CC[t, i, j]), 'actual': num(act)})
    dump('daily_decomp', rows, [src])
    gpk = idx[idx <= '2026-01-28'][-1]
    W = [('Last 20 trading days', idx[-21]), ('Since 1 Nov', idx[idx < '2026-11-01'][-1]), ('Since gold peak (28 Jan)', gpk)]
    rows = []
    for wn, a in W:
        msk = idx > a
        for i, v in enumerate(V):
            act = float(r['data'].loc[msk, v].sum())
            for j, s in enumerate(SH):
                rows.append({'window': wn, 'start': D(a), 'end': D(idx[-1]), 'asset': LAB[v], 'unit': UNIT[v], 'shock': s,
                             'value': num(np.nansum(CC[msk, i, j]), 3), 'actual': num(act, 3)})
    dump('cum_decomp', rows, [src, {'label': 'Note', 'value': 'Sums of daily log % changes (bp for yields, slope and HY); contributions add up exactly to the actual move.'}])
    OUTL = {'ALU': ('Aluminium (COMEX)', '%'), 'BKX': ('US banks (BKX)', '%'), 'ENERGY_EQ': ('Energy equities (XLE)', '%'),
            'VIX': ('VIX (pts)', 'pts'), 'MOVE': ('MOVE (pts)', 'pts')}
    rows = []; msk = idx > idx[-21]; OC = r['out_contrib']; occ = col(OC[..., :len(N)])
    for k, o in enumerate(OUT):
        if np.isnan(OC[msk, k, len(N)]).all():
            continue
        act = float(np.nansum(r['outx'].loc[msk, o]))
        for j, s in enumerate(SH):
            rows.append({'asset': OUTL[o][0], 'unit': OUTL[o][1], 'shock': s, 'value': num(np.nansum(occ[msk, k, j]), 3), 'actual': num(act, 3)})
        rows.append({'asset': OUTL[o][0], 'unit': OUTL[o][1], 'shock': 'Unexplained by model', 'value': num(np.nansum(OC[msk, k, len(N)]), 3), 'actual': num(act, 3)})
    dump('outside_20d', rows, [{'label': 'Method', 'value': 'Each asset regressed on the identified daily shocks over the same 2y window; the rest is unexplained.'}])
    sh = pd.DataFrame(r['shock'], index=idx, columns=N)[NAM]
    s20 = sh.rolling(20).sum()
    rows = [{'date': D(t), 'shock': s, 'value': num(s20.loc[t, s], 3)} for t in idx[-504:] for s in NAM]
    dump('shock_roll20', rows, [{'label': 'Units', 'value': 'Sum of 20 daily structural shocks (each has unit variance), so ±4.5 is roughly a 1-in-100 20-day reading.'}])
    lad, ind, pct = m['ladder'], m['ind'], m['pct']
    rows = [{'date': D(t), 'level': int(lad.loc[t, 'level']), 'liq10': num(ind.loc[t, 'liq10'], 2)} for t in lad.index]
    dump('ladder_history', rows, [{'label': 'Model', 'value': 'Public build from 2012. Bloomberg-only inputs count only within 7 days of a calibration run.'}])
    rows = []
    for ly, cols in LAYER.items():
        for c in cols:
            s_ = ind[c].dropna()
            if s_.empty:
                continue
            rows.append({'layer': ly, 'indicator': IND[c][0], 'value': round(float(s_.iloc[-1]), 2), 'unit': IND[c][1],
                         'pct': int(round(float(pct[c].dropna().iloc[-1]))), 'as_of': D(s_.index[-1]), 'rule': IND[c][2]})
        for x in (calib or {}).get('carried', []):
            if x['layer'] == ly:
                rows.append({'layer': ly, 'indicator': x['indicator'] + ' (Bloomberg, carried)', 'value': x['value'], 'unit': x['unit'],
                             'pct': x['pct'], 'as_of': calib['as_of'], 'rule': x['rule']})
    dump('monitor_latest', rows, [{'label': 'Percentile', 'value': 'Full-history percentile since 2008; 100 = most stressed reading on record (sign flipped where lower = more stress).'}])
    rows = []
    for nm, a, b, ex in EP + [(D(idx[-2]), D(idx[-2]), D(idx[-2]), ''), (D(idx[-1]), D(idx[-1]), D(idx[-1]), '')]:
        msk = (idx >= a) & (idx <= b)
        if not msk.any() or np.isnan(r['shock'][msk]).all():
            continue
        s_ = pd.Series(np.nansum(r['shock'][msk], 0), index=N)[NAM]
        top = s_.abs().sort_values(ascending=False).index
        w = lad.loc[a:b]
        pin = any(a <= n[0] <= b for n in NARR)
        rows.append({'episode': nm, 'start': a, 'end': b, 'expected': ex, 'pinned': 'yes' if pin else 'no', 'top': top[0], 'top_val': round(float(s_[top[0]]), 1),
                     'second': top[1], 'second_val': round(float(s_[top[1]]), 1), 'liq': round(float(s_['Liquidity']), 1),
                     'max_level': int(w.level.max()) if len(w) else -1})
    dump('episodes', rows, [{'label': 'Reading', 'value': 'Two largest shocks by absolute size (sums of daily unit-variance shocks over the window); negative = opposite direction. Pinned = a narrative restriction falls in the window, so the episode is not an independent test.'}])
    rows = [{'shock': s, 'asset': LAB[v], 'sign': {1: '+', -1: '−', 0: '·'}[r['shocks'][s].get(v, 0)]} for s in NAM for v in V]
    dump('restrictions', rows)
    rows = [{'check': k, 'result': v} for k, v in (calib or {}).get('summary', {}).items()]
    dump('calibration', rows, [{'label': 'What this is', 'value': 'Comparison of this public build with the private Bloomberg build on the same dates.'}])
    # full daily shock series, for the next Bloomberg calibration (derived data only)
    (out / 'shocks_daily.json').write_text(json.dumps({'dates': [D(t) for t in idx], 'names': N,
        'values': [[num(x, 3) for x in row] for row in r['shock']]}, allow_nan=False))
    status = {'as_of': D(idx[-1]), 'built_at': pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%M:%SZ'), 'source': source,
              'windows': int(len(r['meta'])), 'min_accepted': int(r['meta'].n_acc.min()), 'level': int(lad['level'].iloc[-1]),
              'datasets': sizes}
    (out / 'status.json').write_text(json.dumps(status, indent=1))
    page = (HERE / 'page.html').read_text()
    (out / 'index.html').write_text((HERE / 'shim.html').read_text().replace('<!--PAGE-->', page))
    return status


SOURCE = ('Public: US Treasury par nominal and real yield curves (2y, 10y, 30y, 10y TIPS); Yahoo Finance closes for S&P 500, SOX, '
          'DXY, USDJPY, USDCNH, gold (GC=F), Brent (BZ=F), copper (HG=F), HYG and IEI (HY spread proxy), VIX, MOVE, BKX, XBD, XLE, '
          'aluminium; NY Fed SOFR; FRED IORB/IOER and NFCI; OFR Financial Stress Index.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='site/xasset')
    ap.add_argument('--panel', help='prepared panel pickle instead of downloading')
    ap.add_argument('--ndraw', type=int, default=int(os.environ.get('XASSET_NDRAW', 100000)))
    a = ap.parse_args()
    if a.panel:
        panel = pd.read_pickle(a.panel)
    else:
        from xasset.data import load
        panel = load()
    print('panel', panel.shape, panel.index.min().date(), '->', panel.index.max().date())
    global INFO
    INFO = {c: [str(panel[c].first_valid_index())[:10], str(panel[c].last_valid_index())[:10], int(panel[c].notna().sum())] for c in panel}
    INFO['_complete_change_rows'] = len(changes(panel, V))
    r = estimate(panel, a.ndraw)
    err = np.nanmax(np.abs(np.nansum(r['contrib'], 2) - r['data'].values)[WIN:])
    assert err < 1e-8, f'contributions do not add up: {err}'
    cf = HERE / 'calibration.json'
    calib = json.loads(cf.read_text()) if cf.exists() else None
    m = monitor(panel, r, calib)
    src = SOURCE
    if not a.panel:
        from xasset.data import USED
        if USED.get('USDCNH', 'CNH=X') != 'CNH=X':
            src += f" USDCNH from Yahoo {USED['USDCNH']}" + (' (onshore yuan; Yahoo has no offshore series)' if USED['USDCNH'] == 'CNY=X' else '') + '.'
    st = export(r, m, Path(a.out), calib, src)
    if not a.panel:
        from xasset.data import LAST, PATCHED, STALE
        st['last_print'] = LAST; st['patched'] = PATCHED; st['carried_last_day'] = STALE
        st['cut_by'] = sorted(k for k, v in LAST.items() if v == min(LAST.values()))
        (Path(a.out) / 'status.json').write_text(json.dumps(st, indent=1))
    print(json.dumps(st, indent=1))


if __name__ == '__main__':
    import sys, traceback
    try:
        main()
    except Exception:
        # leave the reason on the site (no secrets involved) so a failed public build can be diagnosed
        o = Path(sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'site/xasset'); o.mkdir(parents=True, exist_ok=True)
        (o / 'error.txt').write_text(pd.Timestamp.now('UTC').strftime('%Y-%m-%d %H:%M UTC') + '\n' + traceback.format_exc()
                                     + '\npanel columns (first, last, count):\n' + json.dumps(globals().get('INFO', {}), indent=0))
        raise
