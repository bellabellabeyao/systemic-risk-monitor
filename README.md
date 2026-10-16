# Systemic Risk Monitor

One dashboard that answers: **how much fragility is building, and is it being tested?**

```
Systemic risk = Vulnerability (Build-up + Amplifiers) x Stress (Plumbing + Outcome)
```

| Pillar | Question | Models / series | Frequency |
|---|---|---|---|
| A Build-up | Is leverage accumulating? | BIS credit gap (1-sided HP), GHSS R-zone, LSZ credit sentiment, NFCI leverage, HH and corporate debt/GDP | Quarterly / weekly |
| B Amplifiers | Would a loss spread? | SRISK, dCoVaR (incl. alt managers + BDCs), Diebold-Yilmaz, absorption ratio, Granger network | Weekly |
| C Plumbing | Is funding clearing? | SOFR-IORB, reserves, ON RRP, SRF take-up, financial CP spread, KRE/SPY drawdown, xccy basis (BBG) | Daily |
| D Outcome | Is stress realised, and what does it do to growth? | STLFSI4, NFCI, Growth-at-Risk | Weekly / quarterly |

Market-top indicators (VIX, MOVE, OAS levels, CAPE, curve, positioning) are **not re-scored**; VIX, term spread and HY OAS enter dCoVaR as state variables.

## Run

```bash
pip install -r requirements.txt
python -m sysrisk.pipeline --source free --out output        # Yahoo + FRED, ~2-3 min
python -m sysrisk.report  --results output/results.pkl --out systemic_risk_monitor.html
streamlit run app.py                                          # interactive version
python tests/test_models.py                                   # known-answer checks on the maths
```

`--source bbg` uses `xbbg` on a Terminal machine (long SRISK history via BS_TOT_LIAB2 / CUR_MKT_CAP); `--source demo` runs offline on synthetic data.

## Files
- `sysrisk/config.py` indicator registry: pillar, source, direction, thresholds, why it matters, how it transmits, owner
- `sysrisk/data.py` providers (Yahoo+FRED, Bloomberg, synthetic)
- `sysrisk/models.py` the maths, numpy/scipy only
- `sysrisk/pipeline.py` weekly panel, percentile scoring, pillars, regime
- `sysrisk/report.py` + `dashboard_template.html` single-file HTML dashboard
- `manual_overlay.csv` supervisory data with no free feed

## Known limits
- Yahoo returns only ~5-8 quarters of balance sheets, so pre-2024 SRISK uses back-filled liabilities (flagged). Use Bloomberg or NYU V-Lab for history.
- EWMA beta stands in for GARCH-DCC in LRMES; dCoVaR uses equity returns, not market-valued asset growth.
- Basket returns are equal-weighted.
- TED spread was discontinued with LIBOR (Jan 2022); financial CP minus T-bill replaces it.

## Daily refresh on GitHub Pages

1. Push this folder to a GitHub repo (keep `.github/workflows/daily-refresh.yml`).
2. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions** tab → *Daily refresh* → **Run workflow** once to publish now.
4. After that it runs every weekday at 07:45 Singapore time and republishes `index.html`
   (plus the CSVs) at `https://<user>.github.io/<repo>/`.

If a run fails, open it in the Actions tab; the log shows which data source failed. Yahoo rate limits
are retried with backoff; a failed run leaves the previous day's page live.
