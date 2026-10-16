"""Known-answer checks for the model math. Run: python -m pytest tests -q  (or python tests/test_models.py)"""
import numpy as np, pandas as pd
from sysrisk import models as M

rng = np.random.default_rng(0)

def test_quantreg_recovers_location_shift():
    # y = 1 + 2x + e, e ~ N(0,1): the q-quantile line is (1 + z_q) + 2x
    n = 4000; x = rng.normal(size=n); y = 1 + 2 * x + rng.normal(size=n)
    X = np.column_stack([np.ones(n), x])
    for tau, z in [(0.05, -1.6449), (0.5, 0.0), (0.95, 1.6449)]:
        b = M.quantreg(y, X, tau)
        assert abs(b[0] - (1 + z)) < 0.12 and abs(b[1] - 2) < 0.08, (tau, b)

def test_quantreg_heteroskedastic_slope():
    # y = x*(1+e): scale grows with x, so tail slope != median slope (the reason CoVaR uses QR)
    n = 4000; x = rng.uniform(0, 2, n); y = x + x * rng.normal(size=n)
    X = np.column_stack([np.ones(n), x])
    assert abs(M.quantreg(y, X, 0.05)[1] - (1 - 1.6449)) < 0.15

def test_gfevd_rows_sum_and_independence():
    # independent series -> no spillover: theta ~ identity, total connectedness ~ 0
    A = [np.diag([0.5, 0.2, 0.1])]; S = np.diag([1.0, 2.0, 0.5])
    th = M.gfevd(A, S, 10)
    assert np.allclose(th.sum(1), 1) and np.allclose(th, np.eye(3))
    # one-way spillover 0 -> 1: series 1 should receive, series 0 should transmit
    A = [np.array([[0.5, 0, 0], [0.8, 0.2, 0], [0, 0, 0.1]])]; S = np.eye(3)
    tab = M.connectedness_table(M.gfevd(A, S, 10), list("abc"))
    assert tab["net"]["a"] > 0 > tab["net"]["b"] and abs(tab["net"]["c"]) < 1e-9
    assert abs(tab["net"].sum()) < 1e-9

def test_var_ols_recovers_coefficients():
    A1 = np.array([[0.5, 0.1], [0.0, 0.3]]); T = 20000; Y = np.zeros((T, 2))
    for t in range(1, T): Y[t] = A1 @ Y[t - 1] + rng.normal(size=2)
    A, S = M._var_ols(Y, 1)
    assert np.allclose(A[0], A1, atol=0.03) and np.allclose(S, np.eye(2), atol=0.05)

def test_srisk_identity():
    W = pd.DataFrame({"x": [100.0]}); D = pd.DataFrame({"x": [900.0]}); L = pd.DataFrame({"x": [0.3]})
    k = 0.08
    s = M.srisk(W, D, L, k).iloc[0, 0]
    lvg = (900 + 100) / 100
    assert np.isclose(s, k * 900 - (1 - k) * 100 * 0.7)
    assert np.isclose(s, 100 * (k * lvg + (1 - k) * 0.3 - 1))

def test_lrmes_bounds():
    b = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
    l = M.lrmes_from_beta(b, 0.4)["x"].values
    assert np.isclose(l[0], 0) and np.isclose(l[1], 0.4) and np.isclose(l[2], 1 - 0.6 ** 2)

def test_hp_linear_trend_passthrough_and_gap():
    # HP trend of a straight line is the line itself
    y = np.arange(100.0) * 0.5 + 3
    assert np.allclose(M.hp_trend(y, 400_000), y, atol=1e-6)
    s = pd.Series(np.r_[np.arange(60.0), 60 + np.arange(20.0) * 3],
                  index=pd.period_range("2000Q1", periods=80, freq="Q").to_timestamp())
    g = M.credit_gap(s, min_obs=40)["gap"]
    assert g.iloc[:40].isna().iloc[:-1].all() and g.iloc[-1] > 5          # boom -> positive gap

def test_absorption_ratio_one_factor():
    n = 900; f = rng.normal(size=n)
    r1 = pd.DataFrame({i: f + 0.1 * rng.normal(size=n) for i in range(10)}, index=pd.bdate_range("2020", periods=n))
    r0 = pd.DataFrame(rng.normal(size=(n, 10)), index=r1.index)
    assert M.absorption_ratio(r1)["AR"].iloc[-1] > 0.95
    assert M.absorption_ratio(r0)["AR"].iloc[-1] < 0.35        # 2 of 10 PCs of noise ~ 0.2-0.3

def test_granger_detects_lead():
    n = 300; a = rng.normal(size=n); b = np.r_[0, 0.8 * a[:-1]] + 0.3 * rng.normal(size=n)
    m = pd.DataFrame({"a": a, "b": b, "c": rng.normal(size=n)}, index=pd.date_range("2000", periods=n, freq="ME"))
    adj = M.granger_dgc(m, window=120)["adjacency"]
    assert adj.loc["b", "a"] == 1 and adj.loc["a", "b"] == 0

def test_delta_covar_sign_and_tail_dependence():
    # system loads on i only in i's left tail -> dCoVaR > 0 and larger than for an independent firm
    n = 900; idx = pd.date_range("2005", periods=n, freq="W-FRI")
    xi = pd.Series(rng.standard_t(4, n) * 0.03, idx)
    xs = pd.Series(0.5 * np.minimum(xi, 0) + 0.01 * rng.normal(size=n), idx)
    xj = pd.Series(rng.standard_t(4, n) * 0.03, idx)
    st = pd.DataFrame({"m": rng.normal(size=n) * 0.01}, idx)
    di = M.delta_covar(xi, xs, st)["dCoVaR"].mean(); dj = M.delta_covar(xj, xs, st)["dCoVaR"].mean()
    assert di > 1.0 and di > 5 * abs(dj)

if __name__ == "__main__":
    import sys
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try: f(); print("PASS", k)
            except AssertionError as e: fails += 1; print("FAIL", k, e)
    sys.exit(fails)
