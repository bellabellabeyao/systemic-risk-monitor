"""Offline checks for the cross-asset decomposition (no downloads). Run: python tests/test_xasset.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from xasset.model import build, changes, identify
from xasset.data import assemble, CORE
from xasset.pipeline import V


def test_restrictions():
    shocks, SGN, names, _ = build(V)
    assert len(shocks) == 10 and len(names) == 13 and SGN.shape == (10, 13)
    assert SGN[list(shocks).index('Liquidity'), V.index('AU')] == -1      # gold sold in a dash for cash
    assert SGN[list(shocks).index('Risk-off'), V.index('AU')] == +1


def test_assemble_cuts_stale_rows():
    d = pd.bdate_range('2020-01-01', periods=10)
    px = pd.DataFrame({c: np.linspace(100, 110, 10) for c in CORE if c not in ('UST2', 'UST10', 'UST30', 'REAL10')}, index=d)
    tsy = pd.DataFrame({'UST2': 1.0, 'UST10': 2.0, 'UST30': 2.5, 'REAL10': 0.5}, index=d[:8])
    p = assemble(px, tsy)
    assert p.index.max() == d[7], 'rows after the last yield print must be cut'
    assert np.allclose(p['BE10'], 1.5)


def test_identify_adds_up():
    rng = np.random.default_rng(0)
    k = 4; SGN = np.array([[1, 1, 0, 0], [1, -1, 0, 0]], float)
    U = rng.standard_normal((600, k)) @ rng.standard_normal((k, k))
    acc, _ = identify(U / U.std(0), SGN, ndraw=4000, seed=1)
    assert len(acc) > 0
    B = acc[0]; E = np.linalg.solve(B, (U / U.std(0)).T)
    assert np.allclose(B @ E, (U / U.std(0)).T)
    cols = B[:, :2]
    assert all(np.all(np.sign(cols[:2, j]) == SGN[j, :2]) for j in range(2))


if __name__ == '__main__':
    for f in [test_restrictions, test_assemble_cuts_stale_rows, test_identify_adds_up]:
        f(); print('ok', f.__name__)
