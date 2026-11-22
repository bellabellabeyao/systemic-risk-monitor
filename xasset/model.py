"""Cross-asset sign-restricted decomposition (13 variables; named shocks set by SPEC, plus narrative restrictions). Same sampler as model.py (rotation draws, accept only rotations where every
named shock satisfies its signs; leftover columns are 'Other'), with more variables and shocks."""
import numpy as np, pandas as pd
from scipy.optimize import linear_sum_assignment

# Sign patterns ("fingerprints"). +1 up, -1 down, missing = free. JPY/CNH are USDJPY/USDCNH (-1 = yen/yuan stronger); HY +1 = wider.
SPECS = {
    # first version: ten named shocks
    'v1': {
        'Growth':          dict(EQ=+1, Y2=+1, BE=+1, HY=-1),
        'Monetary':        dict(EQ=-1, Y2=+1, RY=+1, BE=-1, USD=+1, SLOPE=-1),
        'Risk-off':        dict(EQ=-1, Y2=-1, RY=-1, USD=+1, AU=+1, HY=+1, JPY=-1),
        'Liquidity':       dict(EQ=-1, Y2=-1, RY=+1, BE=-1, USD=+1, AU=-1, HY=+1, SLOPE=+1),
        'US risk premium': dict(EQ=-1, RY=+1, USD=-1, AU=+1),
        'Term premium':    dict(EQ=-1, Y2=+1, SLOPE=+1, RY=+1, AU=-1),
        'Oil supply':      dict(EQ=-1, BE=+1, OIL=+1),
        'AI / tech':       dict(TECH=+1, EQ=+1),
        'Global growth':   dict(EQ=+1, USD=-1, OIL=+1, CU=+1, CNH=-1),
        'Yen / carry':     dict(EQ=-1, USD=-1, JPY=-1),
    },
    # merged: yen / carry folded into risk-off (both: yen bought, equities and yields down); US and global growth folded
    # into one demand shock. The two pairs the sampler confused most often (see xasset/README) are pinned by narrative
    # restrictions instead.
    'v2': {
        'Growth':           dict(EQ=+1, Y2=+1, BE=+1, CU=+1, HY=-1),
        'Monetary':         dict(EQ=-1, Y2=+1, RY=+1, BE=-1, USD=+1, SLOPE=-1),
        'Risk-off / carry': dict(EQ=-1, Y2=-1, RY=-1, JPY=-1, HY=+1),
        'Liquidity':        dict(EQ=-1, Y2=-1, RY=+1, BE=-1, USD=+1, AU=-1, HY=+1, SLOPE=+1),
        'US risk premium':  dict(EQ=-1, RY=+1, USD=-1, AU=+1),
        'Term premium':     dict(EQ=-1, Y2=+1, SLOPE=+1, RY=+1, AU=-1),
        'Oil supply':       dict(EQ=-1, BE=+1, OIL=+1),
        'AI / tech':        dict(TECH=+1, EQ=+1),
    },
}
# v3: v2 with global (China) growth kept separate. It was never confused with US growth; folding it in pushed copper,
# oil and yuan moves into 'other'.
SPECS['v3'] = {k: v for k, v in SPECS['v2'].items()}
SPECS['v3']['Growth'] = dict(EQ=+1, Y2=+1, BE=+1, HY=-1)
SPECS['v3']['Global growth'] = dict(EQ=+1, USD=-1, OIL=+1, CU=+1, CNH=-1)
SPEC = 'v3'

# Narrative restrictions: (day, shock name(s) by spec, sign, variable it must be the largest contributor to).
NARR = [
    ('2020-03-18', ['Liquidity'], +1, 'RY'),                           # dash for cash: real yields +18bp while stocks and gold crashed
    ('2024-08-05', ['Risk-off / carry', 'Yen / carry'], +1, 'JPY'),    # BOJ hike + carry unwind, yen +1.6%
    ('2025-04-10', ['US risk premium'], +1, 'USD'),                    # sell America: dollar -1.5%, real yields +22bp, gold +3%
    ('2022-06-13', ['Monetary'], +1, 'Y2'),                            # 75bp repricing: 2y +29bp, curve flatter
    ('2023-10-03', ['Term premium'], +1, 'SLOPE'),                     # long-end selloff: 30s2s +9bp
    ('2025-01-27', ['AI / tech'], -1, 'TECH'),                         # DeepSeek: semis -6% beyond beta
    ('2022-03-08', ['Oil supply'], +1, 'OIL'),                         # US ban on Russian oil
    ('2015-08-11', ['Global growth', 'Growth'], -1, 'CU'),             # CNY devaluation: copper -2.9%
]

def build(vars_, spec=None):
    spec = spec or SPEC
    LAB = {'EQ': 'US equities (SPX)', 'TECH': 'Semis, beta-adjusted (SOX)', 'Y2': '2y UST yield', 'SLOPE': '30y − 2y slope',
           'RY': '10y real yield', 'BE': '10y breakeven', 'USD': 'US dollar (DXY)', 'JPY': 'USDJPY', 'AU': 'Gold',
           'OIL': 'Brent', 'CU': 'Copper', 'HY': 'HY spread (proxy)', 'CNH': 'USDCNH'}
    S = SPECS[spec]
    need = {'Term premium': 'SLOPE', 'AI / tech': 'TECH', 'Yen / carry': 'JPY', 'Global growth': 'CU', 'Risk-off / carry': 'JPY'}
    shocks = {k: {v: s for v, s in d.items() if v in vars_} for k, d in S.items() if need.get(k, vars_[0]) in vars_}
    SGN = np.array([[shocks[s].get(v, 0) for v in vars_] for s in shocks], float)
    nother = len(vars_) - len(shocks)
    names = list(shocks) + (['Other'] if nother == 1 else [f'Other {i+1}' for i in range(nother)])
    return shocks, SGN, names, LAB

def narrative(names, vars_, dates, idx):
    """Narrative restrictions that fall inside a window: list of (row in window, shock column, sign, variable column).
    Each says: on this known day the shock had this sign AND was the largest contributor to this variable's move
    (Antolin-Diaz and Rubio-Ramirez, 2018, type-B restriction)."""
    out = []
    for day, cands, sgn, var in NARR:
        t = pd.Timestamp(day)
        sh = next((c for c in cands if c in names), None)
        if sh is None or var not in vars_ or t not in idx:
            continue
        out.append((idx.get_loc(t), names.index(sh), sgn, vars_.index(var)))
    return out


def _beta_adj(y, x, win=252):
    """Semis return net of market beta; beta from the trailing 252 days, lagged one day (no look-ahead)."""
    j = pd.concat([y, x], axis=1).dropna(); j.columns = ['y', 'x']
    b = (j['y'].rolling(win, min_periods=120).cov(j['x']) / j['x'].rolling(win, min_periods=120).var()).shift(1)
    return (j['y'] - b * j['x']).reindex(y.index)

def changes(panel, vars_):
    d = pd.DataFrame(index=panel.index)
    lg = lambda c: np.log(panel[c]).diff() * 100
    m = {'EQ': lambda: lg('SPX'), 'TECH': lambda: _beta_adj(lg('SOX'), lg('SPX')), 'Y2': lambda: panel['UST2'].diff() * 100,
         'SLOPE': lambda: (panel['UST30'] - panel['UST2']).diff() * 100, 'RY': lambda: panel['REAL10'].diff() * 100,
         'BE': lambda: panel['BE10'].diff() * 100, 'USD': lambda: lg('USD'), 'JPY': lambda: lg('USDJPY'), 'AU': lambda: lg('GOLD'),
         'OIL': lambda: lg('BRENT'), 'CU': lambda: lg('COPPER'), 'HY': lambda: panel['HYPROXY'].diff(), 'CNH': lambda: lg('USDCNH')}
    for v in vars_: d[v] = m[v]()
    d = d.dropna()
    d = d[(d != 0).sum(axis=1) >= len(vars_) - 2]
    return d

def rand_orth(n, k, rng):
    X = rng.standard_normal((n, k, k)); Q, R = np.linalg.qr(X)
    return Q * np.sign(np.diagonal(R, axis1=1, axis2=2))[:, None, :]

def identify(U, SGN, ndraw=50000, seed=0, batch=10000, narr=()):
    rng = np.random.default_rng(seed); k = U.shape[1]; ns = SGN.shape[0]
    P = np.linalg.cholesky(np.cov(U.T)); acc = []; ncand = 0
    for b in range(0, ndraw, batch):
        Q = rand_orth(min(batch, ndraw - b), k, rng)
        Bs = np.einsum('ij,njk->nik', P, Q); cols = np.transpose(Bs, (0, 2, 1)); sig = np.sign(cols)
        Z = (SGN == 0)[None, None]
        okp = np.all(Z | (sig[:, :, None, :] == SGN[None, None]), axis=3)
        okn = np.all(Z | (-sig[:, :, None, :] == SGN[None, None]), axis=3)
        ok = okp | okn
        cand = np.where(ok.any(axis=1).all(axis=1))[0]; ncand += len(cand)
        for n in cand:
            cost = np.where(ok[n].T, 0.0, 1.0); r, c = linear_sum_assignment(cost)
            if cost[r, c].sum(): continue
            B = np.empty((k, k)); used = set(c)
            for j, col in zip(r, c):
                v = Bs[n][:, col]; B[:, j] = v if okp[n, col, j] else -v
            for i, col in enumerate(sorted(set(range(k)) - used)):
                v = Bs[n][:, col]; B[:, ns + i] = v * (np.sign(v[0]) or 1)
            if narr and not _narr_ok(B, U, narr):
                continue
            acc.append(B)
    return np.array(acc), ncand


def _narr_ok(B, U, narr):
    for t, j, sgn, v in narr:
        e = np.linalg.solve(B, U[t]); c = np.abs(B[v] * e)
        if np.sign(e[j]) != sgn or c[j] < c.max():
            return False
    return True
