# Systemic Risk Monitor

One dashboard that answers: **how fragile is the system, is it being tested, and could the AI build-out become a systemic problem?**

## Structure: 4 stages x 2 lenses x 3 kinds of evidence

| Stage | Question | Model link |
|---|---|---|
| 1 Fragility | Why is the system vulnerable? | Build-up |
| 2 Triggers | What sets it off? | Trigger |
| 3 Amplifiers | Why does it spread? | Contagion |
| 4 Systemic threshold | When is it systemic? | Shock absorbers |

Lenses: **Broad system** and **AI channel** (off-balance-sheet commitments, circular financing, debt-funded capex, AI credit, concentration, bank/insurer absorption).

**One evaluation for every row** (`sysrisk/unified.py`): every series scores 0-100, higher = riskier. Model series: percentile of its own history, real time. Judgement series (no usable time series, in `sysrisk/signal_board.py`): GREEN 25, AMBER 52, RED 80. Theme = weighted average of its series (series passing the evidence test 1.0, other model series 0.5, judgement 0.5); stage condition = average of its themes; colour from the rounded score: GREEN < 40 <= AMBER < 65 <= RED.

**Two aggregates, two jobs.** *Condition* (all series) says how stretched each stage is today; it is descriptive. *Early warning* (the evidence-screened index) is the only number tested out of sample. Adding the untested context series to the early-warning index turned its out-of-sample drawdown R2 negative (Nov 2026 test), so they stay separate. A stage whose early-warning score rests on one tested series is marked "thin".

Placement rule: level of an excess = Fragility; shock or fast change = Trigger; mechanism that forces selling or spreads losses = Amplifier; buffer and whether it gives way = Threshold.

The page and the Excel download (`Systemic_Risk_Dashboard.xlsx`, linked in the page header) are built from the same files on every run.

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
- `sysrisk/signal_board.py` hand-maintained traffic-light monitor (18 indicators, 41 series), shown as the *Signal board* section; not scored
- `tools/build_signal_board_xlsx.py` builds the same signal board as an Excel workbook: `python tools/build_signal_board_xlsx.py --out Systemic_Risk_Dashboard.xlsx`

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

The judgement series are refreshed by a daily Claude scheduled task that researches new readings, edits `sysrisk/signal_board.py` (DETAIL rows only; model series refresh themselves) and pushes to `main`; the push triggers the same rebuild. Rows it cannot refresh keep `refreshed=False` and show as "carried". Bloomberg-only series need a session linked to the Terminal machine.

If a run fails, open it in the Actions tab; the log shows which data source failed. Yahoo rate limits
are retried with backoff; a failed run leaves the previous day's page live.
