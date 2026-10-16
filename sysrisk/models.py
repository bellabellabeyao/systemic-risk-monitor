"""
Systemic-risk models. Pure numpy / pandas / scipy (no statsmodels dependency).

Every function returns a tidy pandas object indexed by date. Conventions:
  * returns are simple returns in decimals; losses are negative
  * risk outputs are reported as POSITIVE numbers = bigger risk (e.g. dCoVaR loss in %)
  * no function looks ahead: rolling / expanding estimators only use data up to t
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse, stats
from scipy.optimize import linprog
from scipy.sparse.linalg import spsolve


# =============================================================== 1. quantile regression
def quantreg(y: np.ndarray, X: np.ndarray, tau: float) -> np.ndarray:
    """
    Koenker-Bassett quantile regression solved as a linear programme.

        min_b  sum_t rho_tau(y_t - x_t'b),   rho_tau(u) = u (tau - 1{u<0})

    Split b = b+ - b-, residual u = u+ - u-, all >= 0:
        min  tau*1'u+ + (1-tau)*1'u-     s.t.  X b+ - X b- + u+ - u- = y
    X must already contain a constant column.
    """
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    c = np.concatenate([np.zeros(2 * k), tau * np.ones(n), (1 - tau) * np.ones(n)])
    A_eq = sparse.hstack([sparse.csr_matrix(X), sparse.csr_matrix(-X),
                          sparse.identity(n, format="csr"), -sparse.identity(n, format="csr")]).tocsr()
    res = linprog(c, A_eq=A_eq, b_eq=y, bounds=(0, None), method="highs")
    if not res.success:
        raise RuntimeError(f"quantile regression failed: {res.message}")
    return res.x[:k] - res.x[k:2 * k]


# =============================================================== 2. CoVaR / dCoVaR
def delta_covar(x_i: pd.Series, x_sys: pd.Series, state: pd.DataFrame, q: float = 0.05,
                min_obs: int = 260, refit_every: int = 52) -> pd.DataFrame:
    """
    Time-varying dCoVaR (Adrian & Brunnermeier 2016, eqs. 6-11), weekly data.

    Step 1  VaR of institution i conditional on lagged state M_{t-1}:
                X^i_t = a^i_q + c^i_q' M_{t-1} + e        (quantile q and median 0.5)
            -> VaR^i_{q,t} = a^i_q + c^i_q' M_{t-1}
    Step 2  System quantile conditional on i and the state:
                X^sys_t = a_q + g_q X^i_t + b_q' M_{t-1} + e   (quantile q)
    Step 3  CoVaR^i_{q,t} = a_q + g_q VaR^i_{q,t} + b_q' M_{t-1}
            dCoVaR^i_{q,t} = g_q (VaR^i_{q,t} - VaR^i_{0.5,t})

    Estimation is EXPANDING-window, re-fitted every `refit_every` weeks, so the value at t only
    uses parameters estimated on data up to t (no look-ahead). Output dCoVaR is reported as a
    positive loss in % of the system's weekly return.
    """
    M = state.shift(1)                                   # M_{t-1}
    df = pd.concat({"xi": x_i, "xs": x_sys}, axis=1).join(M, how="inner").dropna()
    if len(df) < min_obs + 10:
        return pd.DataFrame(columns=["VaR_i", "CoVaR", "dCoVaR", "gamma"])
    Mcols = list(state.columns)
    Z = np.column_stack([np.ones(len(df)), df[Mcols].values])   # [1, M_{t-1}]
    out = []
    fit_points = list(range(min_obs, len(df), refit_every)) + [len(df)]
    for s, e in zip(fit_points[:-1], fit_points[1:]):
        Ztr, xi_tr, xs_tr = Z[:s], df["xi"].values[:s], df["xs"].values[:s]
        c_q = quantreg(xi_tr, Ztr, q)                       # step 1 (q)
        c_50 = quantreg(xi_tr, Ztr, 0.5)                    # step 1 (median)
        theta = quantreg(xs_tr, np.column_stack([Ztr[:, :1], xi_tr, Ztr[:, 1:]]), q)  # step 2
        a_q, g_q, b_q = theta[0], theta[1], theta[2:]
        Zo = Z[s:e]
        var_q = Zo @ c_q
        var_50 = Zo @ c_50
        covar = a_q + g_q * var_q + Zo[:, 1:] @ b_q          # step 3
        dcovar = g_q * (var_q - var_50)
        out.append(pd.DataFrame({"VaR_i": -var_q * 100, "CoVaR": -covar * 100,
                                 "dCoVaR": -dcovar * 100, "gamma": g_q}, index=df.index[s:e]))
    return pd.concat(out)


# =============================================================== 3. MES / LRMES / SRISK
def ewma_beta(r_i: pd.DataFrame, r_m: pd.Series, halflife: int = 63) -> pd.DataFrame:
    """Time-varying beta = EWMA cov(r_i, r_m) / EWMA var(r_m). Stand-in for GARCH-DCC."""
    r = r_i.join(r_m.rename("_m"), how="inner")
    cov = r.ewm(halflife=halflife, min_periods=halflife * 2).cov(pairwise=True)
    var_m = r["_m"].ewm(halflife=halflife, min_periods=halflife * 2).var()
    betas = {c: cov.xs(c, level=1)["_m"] / var_m for c in r_i.columns}
    return pd.DataFrame(betas)


def tail_mes(r_i: pd.DataFrame, r_m: pd.Series, window: int = 504, alpha: float = 0.05) -> pd.DataFrame:
    """
    Non-parametric MES (Acharya et al. 2017):  MES^i_t = -E[R^i | R^m <= VaR^m_alpha]
    over a trailing window. Reported in % (positive = expected daily loss on market tail days).
    """
    r = r_i.join(r_m.rename("_m"), how="inner")

    def _mes(block: pd.DataFrame) -> pd.Series:
        thr = block["_m"].quantile(alpha)
        return -block.loc[block["_m"] <= thr].drop(columns="_m").mean() * 100

    idx = r.index[window - 1::5]                            # every 5 days for speed
    rows = {d: _mes(r.loc[:d].iloc[-window:]) for d in idx}
    return pd.DataFrame(rows).T


def lrmes_from_beta(beta: pd.DataFrame, crash: float = 0.40) -> pd.DataFrame:
    """
    Long-run MES under a `crash` (default 40%) six-month market decline, V-Lab approximation:
        LRMES = 1 - exp( log(1 - crash) * beta )
    """
    return 1 - np.exp(np.log(1 - crash) * beta)


def srisk(mkt_cap: pd.DataFrame, liabilities: pd.DataFrame, lrmes: pd.DataFrame,
          k: float = 0.08) -> pd.DataFrame:
    """
    Brownlees & Engle (2017):
        SRISK_i = k*D_i - (1-k) * W_i * (1 - LRMES_i)
                = W_i [ k*LVG_i + (1-k)*LRMES_i - 1 ],   LVG = (D + W) / W
    D = book liabilities, W = market cap (same currency units). Returns SRISK per firm (can be < 0).
    Aggregate systemic SRISK should sum only the positive parts (a surplus is not transferable).
    """
    idx = mkt_cap.index.intersection(lrmes.index)
    cols = [c for c in mkt_cap.columns if c in liabilities.columns and c in lrmes.columns]
    W = mkt_cap.loc[idx, cols]
    D = liabilities.reindex(idx).ffill()[cols]
    L = lrmes.loc[idx, cols]
    return k * D - (1 - k) * W * (1 - L)


# =============================================================== 4. Diebold-Yilmaz
def parkinson_vol(high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    """Daily range-based variance sigma^2 = (ln H - ln L)^2 / (4 ln 2); returned as log annualised vol."""
    var = (np.log(high) - np.log(low)) ** 2 / (4 * np.log(2))
    vol = np.sqrt(252 * var).replace(0, np.nan)
    return np.log(vol)


def _var_ols(Y: np.ndarray, p: int):
    """VAR(p) by OLS. Returns list of A_k (N x N) and residual covariance Sigma."""
    T, N = Y.shape
    X = np.column_stack([np.ones(T - p)] + [Y[p - k:T - k] for k in range(1, p + 1)])
    B, *_ = np.linalg.lstsq(X, Y[p:], rcond=None)
    U = Y[p:] - X @ B
    Sigma = U.T @ U / (T - p - X.shape[1])
    A = [B[1 + (k - 1) * N: 1 + k * N].T for k in range(1, p + 1)]
    return A, Sigma


def gfevd(A: list, Sigma: np.ndarray, H: int = 10) -> np.ndarray:
    """
    Generalised FEVD (Pesaran-Shin 1998), as used in Diebold-Yilmaz (2012):
        theta_ij(H) = sigma_jj^-1 sum_{h<H} (e_i' Psi_h Sigma e_j)^2
                      / sum_{h<H} (e_i' Psi_h Sigma Psi_h' e_i)
    MA coefficients: Psi_0 = I, Psi_h = sum_k A_k Psi_{h-k}. Rows are normalised to sum to 1.
    """
    N = Sigma.shape[0]
    p = len(A)
    Psi = [np.eye(N)]
    for h in range(1, H):
        Psi.append(sum(A[k] @ Psi[h - 1 - k] for k in range(min(p, h))))
    num = np.zeros((N, N))
    den = np.zeros(N)
    for P in Psi:
        PS = P @ Sigma
        num += PS ** 2
        den += np.diag(PS @ P.T)
    theta = (num / np.diag(Sigma)[None, :]) / den[:, None]
    return theta / theta.sum(axis=1, keepdims=True)


def connectedness_table(theta: np.ndarray, names: list) -> dict:
    N = len(names)
    off = theta * (1 - np.eye(N))
    frm = off.sum(axis=1) * 100            # FROM others (row)
    to = off.sum(axis=0) * 100             # TO others (column)
    return {"total": off.sum() / N * 100,
            "to": pd.Series(to, names), "from": pd.Series(frm, names),
            "net": pd.Series(to - frm, names),
            "pairwise": pd.DataFrame(theta * 100, index=names, columns=names)}


def diebold_yilmaz(vol: pd.DataFrame, window: int = 200, p: int = 2, H: int = 10,
                   step: int = 5) -> dict:
    """Rolling DY connectedness. Returns total (Series), net (DataFrame), latest pairwise table."""
    v = vol.dropna()
    names = list(v.columns)
    tot, net, last = {}, {}, None
    for end in range(window, len(v) + 1, step):
        Y = v.values[end - window:end]
        A, S = _var_ols(Y, p)
        tab = connectedness_table(gfevd(A, S, H), names)
        d = v.index[end - 1]
        tot[d] = tab["total"]
        net[d] = tab["net"]
        last = tab
    return {"total": pd.Series(tot, name="DY total"), "net": pd.DataFrame(net).T, "latest": last}


# =============================================================== 5. Absorption ratio
def absorption_ratio(returns: pd.DataFrame, window: int = 500, frac: float = 0.2,
                     halflife: int = 250, step: int = 5) -> pd.DataFrame:
    """
    Kritzman, Li, Page & Rigobon (2011):
        AR = sum_{i<=n} var(PC_i) / sum_j var(asset_j),  n = frac * N
    Covariance is exponentially weighted (half-life 250d) over a 500d window.
    dAR = (AR_15d mean - AR_1y mean) / AR_1y std  (the published 'shift' signal; > +1 is a warning).
    """
    r = returns.dropna(how="all")
    w = 0.5 ** (np.arange(window)[::-1] / halflife)
    w = w / w.sum()
    out = {}
    for end in range(window, len(r) + 1, step):
        blk = r.iloc[end - window:end]
        blk = blk.loc[:, blk.notna().mean() > 0.98].fillna(0.0)   # names with a full window only
        if blk.shape[1] < 5:
            continue
        X = blk.values
        n = max(1, int(round(frac * X.shape[1])))
        Xc = X - (w[:, None] * X).sum(0)
        C = (Xc * w[:, None]).T @ Xc
        ev = np.sort(np.linalg.eigvalsh(C))[::-1]
        out[r.index[end - 1]] = ev[:n].sum() / ev.sum()
    ar = pd.Series(out, name="AR")
    per_year = 252 // step
    shift = (ar.rolling(3).mean() - ar.rolling(per_year).mean()) / ar.rolling(per_year).std()
    return pd.DataFrame({"AR": ar, "AR_shift": shift})


# =============================================================== 6. Granger network
def granger_dgc(returns: pd.DataFrame, window: int = 36, alpha: float = 0.05) -> dict:
    """
    Billio, Getmansky, Lo & Pelizzon (2012). Monthly returns, rolling window.
    j Granger-causes i if b_ij != 0 in   r_i,t = a + a_ii r_i,t-1 + b_ij r_j,t-1 + e.
        DGC = (1 / N(N-1)) sum_{i != j} 1(j -> i)
    Returns DGC series and the latest adjacency matrix (row i caused by column j).
    """
    m = returns.dropna()
    names = list(m.columns)
    N = len(names)
    dgc, adj_last = {}, None
    for end in range(window, len(m) + 1):
        blk = m.values[end - window:end]
        adj = np.zeros((N, N))
        y_lag, y = blk[:-1], blk[1:]
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                X = np.column_stack([np.ones(len(y)), y_lag[:, i], y_lag[:, j]])
                b, *_ = np.linalg.lstsq(X, y[:, i], rcond=None)
                e = y[:, i] - X @ b
                dof = len(y) - 3
                s2 = e @ e / dof
                se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[2, 2])
                pval = 2 * stats.t.sf(abs(b[2] / se), dof)
                adj[i, j] = pval < alpha
        dgc[m.index[end - 1]] = adj.sum() / (N * (N - 1))
        adj_last = adj
    return {"dgc": pd.Series(dgc, name="DGC"),
            "adjacency": pd.DataFrame(adj_last, index=names, columns=names)}


# =============================================================== 7. Credit gap (BIS)
def hp_trend(y: np.ndarray, lam: float) -> np.ndarray:
    """Two-sided HP trend: solve (I + lam D'D) tau = y with D the 2nd-difference operator."""
    n = len(y)
    D = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)], [0, 1, 2], shape=(n - 2, n))
    return spsolve((sparse.identity(n) + lam * (D.T @ D)).tocsc(), y)


def credit_gap(credit_gdp: pd.Series, lam: float = 400_000, min_obs: int = 40) -> pd.DataFrame:
    """
    BIS credit-to-GDP gap: ratio minus its ONE-SIDED HP trend (lambda = 400,000, quarterly).
    The one-sided trend at t is the endpoint of a two-sided filter run on data up to t,
    i.e. exactly what a policymaker could have computed in real time.
    Basel III CCyB guide: buffer starts at gap = 2pp, maximum at 10pp.
    """
    s = credit_gdp.dropna()
    trend = pd.Series(np.nan, index=s.index)
    for t in range(min_obs, len(s) + 1):
        trend.iloc[t - 1] = hp_trend(s.values[:t], lam)[-1]
    return pd.DataFrame({"ratio": s, "trend": trend, "gap": s - trend})


# =============================================================== 8. R-zone (GHSS 2022)
def rzone(credit_gdp: pd.Series, asset_prices: pd.DataFrame, horizon_q: int = 12,
          min_obs: int = 40) -> pd.DataFrame:
    """
    Greenwood, Hanson, Shleifer & Sorensen (2022) 'Predictable Financial Crises'.
    Quarterly. Credit growth = 3y change in credit/GDP (pp); asset growth = 3y log price change.
    Each is converted to an expanding percentile; the R-zone intensity is
        min( pct(credit growth), max_k pct(asset growth_k) )
    so it is high only when BOTH a credit boom and an asset boom are present.
    R-zone flag: intensity >= 0.8 (both in top quintile of their own history).
    """
    cg = credit_gdp.diff(horizon_q)
    ag = np.log(asset_prices).diff(horizon_q)
    pc = cg.expanding(min_obs).rank(pct=True)
    pa = ag.apply(lambda s: s.expanding(min_obs).rank(pct=True)).max(axis=1)
    inten = pd.concat([pc, pa], axis=1).min(axis=1, skipna=False)
    return pd.DataFrame({"credit_growth_3y": cg, "credit_pct": pc, "asset_pct": pa,
                         "rzone": inten, "flag": inten >= 0.8})


# =============================================================== 9. Growth-at-Risk
def growth_at_risk(gdp_real: pd.Series, fci: pd.Series, h: int = 4, taus=(0.05, 0.5, 0.95),
                   min_obs: int = 80) -> pd.DataFrame:
    """
    Adrian, Boyarchenko & Giannone (2019). Quarterly.
        y_{t+h} = (400/h) * [ln GDP_{t+h} - ln GDP_t]          (annualised h-quarter growth)
        Q_tau(y_{t+h} | x_t) = b0 + b1 * FCI_t + b2 * y_t      (y_t = last-quarter annualised growth)
    Expanding-window fit; prediction at t uses only pairs whose outcome was known at t.
    Output: the predicted distribution quantiles of growth h quarters ahead, made at t.
    """
    g = np.log(gdp_real)
    yfwd = (400 / h) * (g.shift(-h) - g)
    ycur = 400 * g.diff()
    df = pd.concat({"y": yfwd, "fci": fci, "ycur": ycur}, axis=1)
    rows = {}
    for t in range(min_obs, len(df)):
        train = df.iloc[: t - h + 1].dropna()            # outcomes realised by t
        x_t = df[["fci", "ycur"]].iloc[t]
        if len(train) < min_obs // 2 or x_t.isna().any():
            continue
        X = np.column_stack([np.ones(len(train)), train["fci"], train["ycur"]])
        xt = np.r_[1.0, x_t.values]
        rows[df.index[t]] = {f"q{int(tau * 100):02d}": xt @ quantreg(train["y"].values, X, tau) for tau in taus}
    return pd.DataFrame(rows).T


# =============================================================== 10. Out-of-sample evaluation
def qloss(y, q, tau):
    u = y - q
    return np.mean(u * (tau - (u < 0)))


def oos_quantile_test(target: pd.Series, preds: dict, tau: float = 0.10, start_oos: str = "2010-01-01",
                      min_train: int = 60) -> pd.DataFrame:
    """
    Giglio, Kelly & Pruitt (2016) style test. Monthly data.
    For each predictor x: expanding-window quantile regression  Q_tau(y_{t+h} | x_t) = a + b x_t,
    fitted only on (x_s, y_{s+h}) pairs already realised at t. Score = OOS quantile R^2
        R2_oos = 1 - L(model) / L(historical quantile)
    > 0 means the predictor beats the unconditional quantile out of sample.
    `target` must already be aligned so that target[t] is the outcome realised h months after t,
    and `h` is inferred from the trailing NaNs in target.
    """
    h = int(target.isna()[::-1].cumprod().sum())  # trailing NaNs = horizon
    out = {}
    for name, x in preds.items():
        df = pd.concat({"y": target, "x": x}, axis=1).dropna(subset=["x"])
        lm, lu, n = [], [], 0
        for t in range(len(df)):
            d = df.index[t]
            if d < pd.Timestamp(start_oos) or pd.isna(df["y"].iloc[t]):
                continue
            tr = df.iloc[: max(0, t - h + 1)].dropna()
            if len(tr) < min_train:
                continue
            X = np.column_stack([np.ones(len(tr)), tr["x"]])
            b = quantreg(tr["y"].values, X, tau)
            qm = b[0] + b[1] * df["x"].iloc[t]
            qu = np.quantile(tr["y"].values, tau)
            y = df["y"].iloc[t]
            lm.append(qloss(np.array([y]), qm, tau)); lu.append(qloss(np.array([y]), qu, tau)); n += 1
        out[name] = {"R2_oos": 1 - np.sum(lm) / np.sum(lu) if n else np.nan, "n": n}
    return pd.DataFrame(out).T
