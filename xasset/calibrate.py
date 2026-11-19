"""Bloomberg calibration (run privately, never in CI): compares the public build with the Bloomberg build and carries
the Bloomberg-only liquidity inputs as percentiles. Writes xasset/calibration.json, which holds derived numbers only
(correlations, percentiles, computed cross-currency bases), never raw Bloomberg prices.

    python -m xasset.calibrate --bbg-panel panel.pkl --bbg-model model.pkl --public shocks_daily.json

bbg-panel: daily panel from the Bloomberg pull (columns as in the private build: GVLQUSD, EUR_BASIS_3M, JPY_BASIS_3M,
SWSP10, UST10, ...). bbg-model: output of xasset.pipeline.estimate() on that panel. public: shocks_daily.json from the
public site.
"""
from __future__ import annotations
import argparse, json, pickle
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).parent


def carried(p: pd.DataFrame) -> tuple[list, dict]:
    p = p[p.index >= '2008-01-01']
    pctl = lambda s: s.rank(pct=True) * 100
    out, flags = [], {}
    g = p['GVLQUSD'].ffill(limit=3)
    eur = p['EUR_BASIS_3M'].ffill(limit=3); jpy = p['JPY_BASIS_3M'].ffill(limit=3)
    eurd = eur - eur.rolling(250, min_periods=120).median(); jpyd = jpy - jpy.rolling(250, min_periods=120).median()
    sw = p['SWSP10'].diff(20)
    items = [('C  Market liquidity', 'UST liquidity index GVLQUSD', None, 'pctile', pctl(g), 'worst 10% → Level 1'),
             ('C  Market liquidity', '10y SOFR swap spread, 20d change', sw, 'bp', pctl(-sw), 'falling = balance-sheet strain'),
             ('D  Funding', 'EUR 3M basis vs 1y median', eurd, 'bp', pctl(-eurd), 'tightest 3% → Level 2'),
             ('D  Funding', 'JPY 3M basis vs 1y median', jpyd, 'bp', pctl(-jpyd), 'tightest 3% → Level 2')]
    for ly, name, val, unit, pc, rule in items:
        pc = pc.dropna()
        v = None if val is None else round(float(val.dropna().iloc[-1]), 1)
        out.append({'layer': ly, 'indicator': name, 'value': v if v is not None else int(round(pc.iloc[-1])),
                    'unit': unit, 'pct': int(round(pc.iloc[-1])), 'rule': rule})
    flags['L1'] = bool(pctl(g).dropna().iloc[-1] >= 90)
    flags['L2'] = bool(max(pctl(-eurd).dropna().iloc[-1], pctl(-jpyd).dropna().iloc[-1]) >= 97)
    return out, flags


def compare(bm: dict, pub: dict) -> dict:
    b = pd.DataFrame(bm['shock'], index=bm['idx'], columns=bm['names'])
    q = pd.DataFrame(pub['values'], index=pd.to_datetime(pub['dates']), columns=pub['names'], dtype=float)
    names = [n for n in b.columns if not n.startswith('Other') and n in q.columns]
    j = b[names].join(q[names], lsuffix='_b', rsuffix='_p', how='inner').dropna()
    j = j[j.index >= j.index.max() - pd.Timedelta(days=730)]
    res = {}
    if len(j) < 100:
        return {'Overlap': f'only {len(j)} common days; comparison skipped'}
    d1 = {n: j[n + '_b'].corr(j[n + '_p']) for n in names}
    s20 = j.rolling(20).sum().dropna()
    d20 = {n: s20[n + '_b'].corr(s20[n + '_p']) for n in names}
    res['Period compared'] = f"{j.index.min():%d %b %Y} to {j.index.max():%d %b %Y} ({len(j)} days)"
    res['Daily shocks: median correlation'] = f"{np.median(list(d1.values())):.2f} (range {min(d1.values()):.2f} to {max(d1.values()):.2f})"
    res['20-day sums: median correlation'] = f"{np.median(list(d20.values())):.2f} (range {min(d20.values()):.2f} to {max(d20.values()):.2f})"
    for n in names:
        res[f'{n}: daily / 20-day correlation'] = f'{d1[n]:.2f} / {d20[n]:.2f}'
    top_b = j[[n + '_b' for n in names]].abs().idxmax(axis=1).str[:-2]
    top_p = j[[n + '_p' for n in names]].abs().idxmax(axis=1).str[:-2]
    res['Same largest shock on the day'] = f'{(top_b == top_p).mean():.0%} of days'
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bbg-panel', required=True); ap.add_argument('--bbg-model', required=True); ap.add_argument('--public')
    ap.add_argument('--as-of')
    a = ap.parse_args()
    p = pd.read_pickle(a.bbg_panel); bm = pickle.load(open(a.bbg_model, 'rb'))
    items, flags = carried(p)
    cf = HERE / 'calibration.json'
    old = json.loads(cf.read_text()) if cf.exists() else {}
    summary = compare(bm, json.load(open(a.public))) if a.public else old.get('summary', {})
    c = {'as_of': a.as_of or f"{p['GVLQUSD'].dropna().index.max():%Y-%m-%d}", 'carried': items, **flags, 'summary': summary}
    cf.write_text(json.dumps(c, indent=1, ensure_ascii=False))
    print(json.dumps(c, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
