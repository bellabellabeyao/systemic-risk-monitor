"""
Signal board: the judgement layer of the monitor (traffic lights), organised on the same spine as the model.

Spine: 4 stages (Fragility -> Triggers -> Amplifiers -> Systemic threshold) x 2 lenses (Broad, AI).
The model's four links map onto the stages (see STAGES). The signal board is NOT scored.

This module is the single source for the dashboard grid, the per-stage tables and the Excel workbook
(tools/build_signal_board_xlsx.py), so they never disagree. It is refreshed by a daily scheduled task
(see README, "Daily refresh"); every reading carries its date and source, and `refreshed=False` marks a
reading carried over from an earlier update.

signal / prev: "GREEN" | "AMBER" | "RED"; prev "" = not tracked at PREV_ASOF (new row).
Rule to place a row: level of an excess = Fragility; a shock or fast change = Triggers;
a mechanism that forces selling or spreads losses = Amplifiers; a buffer, and whether it gives way = Threshold.
"""
AS_OF = "5 Nov 2026 (US close)"
PREV_ASOF = "29 Jul 2026"

# key, number, display name, question, model link (sysrisk.config.PILLARS value)
STAGES = [
    ("fragility", "1", "Fragility", "Why is the system vulnerable?", "Build-up"),
    ("triggers", "2", "Triggers", "What sets it off?", "Trigger"),
    ("amplifiers", "3", "Amplifiers", "Why does it spread?", "Contagion"),
    ("threshold", "4", "Systemic threshold", "When is it systemic?", "Shock absorbers"),
]
LENSES = [("broad", "Broad system"), ("ai", "AI channel")]

# ---------------------------------------------------------------- headline indicators
# key, stage, lens, indicator, signal, prev, comment
SUMMARY = [
    # 1 Fragility - broad
    ("agg_lev", "fragility", "broad", "Aggregate leverage (debt-to-GDP, financial leverage, credit gap)", "AMBER", "AMBER",
     "Total non-financial debt flat at 2.59x GDP (Q2). Government debt is the red spot; corporate debt growth slowed to 4.6%."),
    ("nonbank", "fragility", "broad", "Non-bank leverage (margin debt, private credit, hedge funds)", "RED", "AMBER",
     "Private-credit gates persist through Q3 with record defaults; margin debt 1.5% below its record into the 5 Nov selloff."),
    ("valuation", "fragility", "broad", "Valuation stretch (equity CAPE, risk premia, real estate)", "RED", "RED",
     "CAPE ~40.7 in Oct (99th percentile since 1881); credit spreads still near tights."),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", "AMBER", "AMBER",
     "EM spreads resilient (EMBI GD 187bp) despite US 10y above 5% in Oct; energy importers and weak sovereigns are the soft spots."),
    # 1 Fragility - AI
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", "RED", "",
     "Capex now exceeds operating cash flow at three of four hyperscalers; leases and vendor financing keep much of the build-out off balance sheet."),
    # 2 Triggers - broad
    ("vol", "triggers", "broad", "Volatility (VIX, MOVE, FX vol)", "AMBER", "GREEN",
     "VIX jumped ~70% to ~28 on 5 Nov; MOVE peaked at 114 in early Oct and is back near 94-100."),
    ("spread_chg", "triggers", "broad", "Credit spread widening (HY/IG OAS, CDS indices, sovereign)", "AMBER", "AMBER",
     "Widening has started: HY 340bp (+80bp from Aug low), IG 94bp (+21bp from Jan low). 5 Nov prints pending."),
    ("curve", "triggers", "broad", "Term spreads / yield curve", "AMBER", "AMBER",
     "Curve has steepened out of inversion: 2s10s +38bp, 3m10y about +75bp. Post-inversion steepening is a late-cycle sign."),
    # 2 Triggers - AI
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", "RED", "",
     "The trigger fired on 5 Nov in equities; AI issuers' CDS were already at records and data-centre projects show first cracks."),
    # 3 Amplifiers - broad
    ("crowded", "amplifiers", "broad", "Common exposures / crowded trades", "RED", "AMBER",
     "The crowded AI trade is unwinding: Mag-7 lost >$1tn on 5 Nov. Short-yen and margin positions are still in place."),
    ("corr", "amplifiers", "broad", "Correlation spikes", "AMBER", "GREEN",
     "All 11 S&P sectors fell on 5 Nov (decliners ~6:1); Treasuries still rallied, so the stock-bond hedge worked."),
    ("sifi", "amplifiers", "broad", "SIFI footprint and interbank network", "AMBER", "AMBER",
     "G-SIB footprint structurally large; no interbank counterparty stress. FSB 2026 G-SIB list due mid-Nov."),
    # 3 Amplifiers - AI
    ("ai_amp", "amplifiers", "ai", "AI concentration and leverage on AI exposure", "RED", "",
     "Top 10 stocks ~39% of the S&P 500, near the record; leveraged products and margin sit on the same names."),
    # 4 Systemic threshold - broad
    ("bank_cap", "threshold", "broad", "Bank capital & liquidity (CET1, stress test, LCR/NSFR)", "GREEN", "GREEN",
     "Large banks well capitalised; IMF (Oct) finds core banks resilient to an AI + bond + energy shock, but the weak-bank tail grew to 22% of assets."),
    ("mm_spreads", "threshold", "broad", "Money-market spreads and cross-currency basis", "GREEN", "GREEN",
     "Core funding spreads narrow (3m CP ~4bp over bills); no dollar-shortage signal."),
    ("repo", "threshold", "broad", "Repo and reserves", "AMBER", "AMBER",
     "SOFR 4-7bp above IORB since 29 Oct; reserves ~$2.97tn with no reverse-repo cushion left."),
    ("cb_fac", "threshold", "broad", "Central bank facility usage", "GREEN", "AMBER",
     "Standing Repo Facility take-up near zero; Sep quarter-end passed with SOFR at IORB."),
    ("mkt_liq", "threshold", "broad", "Market liquidity and financial conditions", "GREEN", "GREEN",
     "Conditions still loose (NFCI -0.46) but tighter five weeks in a row."),
    # 4 Systemic threshold - AI
    ("ai_abs", "threshold", "ai", "Absorption of AI credit losses (banks, insurers, credit supply)", "AMBER", "",
     "Banks are hedging and selling down data-centre loans and insurers say capacity is close to full; direct bank exposure is still small."),
]

# ---------------------------------------------------------------- underlying series
# key (-> SUMMARY), metric, signal, prev, reading, note/what to watch, source, as of, refresh code, refreshed
DETAIL = [
    # agg_lev
    ("agg_lev", "Household debt-to-GDP", "GREEN", "GREEN",
     "$21.4tn (Q2), ~66% of GDP on a Z.1 basis. Growth picked up to 5.0% annualised.",
     "Still deleveraged vs 2008. July used the BIS-basis series (~60%); levels not comparable.",
     "Fed Z.1, 11 Sep 2026", "Q2 2026", "FRED: CMDEBT / GDP", True),
    ("agg_lev", "Corporate debt-to-GDP", "AMBER", "AMBER",
     "Non-financial business debt $24.0tn (~74% of GDP). Growth slowed to 4.6% from 7.0%.",
     "AI capex is increasingly debt-funded (see AI rows).",
     "Fed Z.1, 11 Sep 2026", "Q2 2026", "FRED: TBSDODNS / GDP", True),
    ("agg_lev", "Government debt-to-GDP", "RED", "RED",
     "Total government debt $38.7tn (~119% of GDP on Z.1). 10y Treasury hit ~5.36% in early Oct.",
     "IMF GFSR names a sovereign-yield shock as one of three main risks.",
     "Fed Z.1; IMF GFSR Oct 2026", "Q2 2026", "FRED: GFDEGDQ188S", True),
    ("agg_lev", "Total non-financial debt-to-GDP", "AMBER", "AMBER",
     "2.59x GDP in Q2, flat; $84.1tn outstanding.", "Stable in aggregate; mix tilting to government.",
     "Fed Z.1, 11 Sep 2026", "Q2 2026", "Z.1 table D.3", True),
    ("agg_lev", "BIS credit-to-GDP gap", "AMBER", "AMBER",
     "Not refreshed; the model's own one-sided-HP gap is in the Fragility charts.", "Slow-moving early-warning indicator.",
     "BIS (carried from Jul)", "Jul 2026", "FRED: QUSPAM770A", False),
    # nonbank
    ("nonbank", "FINRA margin debt", "AMBER", "AMBER",
     "$1.48tn in Sep (+1.8% m/m, +31.4% y/y), 1.5% below June's $1.50tn record.",
     "Growth slowed from 53.7% y/y in May; such slowdowns preceded past tops. Oct data due ~3rd week Nov.",
     "FINRA via Advisor Perspectives 23 Oct; CNBC 27 Oct", "Sep 2026", "FINRA margin statistics", True),
    ("nonbank", "Private credit", "RED", "AMBER",
     "Q3 redemption requests still above 5% caps (Blue Owl OTIC ~39%, Cliffwater ~16%). Fitch default rate ~6%, a record.",
     "Gates hold, so stress shows in marks, PIK and gates. Watch Q3 BDC non-accruals.",
     "Valuation Research Q3 2026; Yardeni PC monitor; IMF GFSR Oct 2026", "Oct 2026", "manual_overlay: bdc_nonaccrual", True),
    ("nonbank", "Hedge-fund basis-trade leverage", "AMBER", "AMBER",
     "Basis trade down ~20% to ~$1.2tn (MS est.); hedge funds still hold a record ~7% of Treasuries.",
     "Leverage moved into other relative-value trades; a repo or margin shock is the amplifier.",
     "OFR blog 19 Aug; CNBC 30 Sep; Fed FSR May 2026", "Sep 2026", "OFR HFM: FPF-BORROW_REPO_SUM", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct, 98.9th percentile since 1881; only 1999-2000 was higher.",
     "Signals low 10-year returns; not a timing tool.", "Shiller data via thetrading.tools", "Oct 2026", "multpl / Shiller ie_data", True),
    ("valuation", "Risk-premia compression (credit levels)", "RED", "RED",
     "HY 340bp and IG 94bp still near multi-decade tights.", "Little pay for risk.",
     "FRED ICE BofA OAS", "3 Nov 2026", "FRED: BAMLH0A0HYM2, BAMLC0A0CM", True),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "30y mortgage 7.24% (29 Oct), off a 7.40% Oct peak. Case-Shiller +2.1-2.7% y/y; real prices falling.",
     "Affordability worse than July.", "Freddie Mac PMMS; S&P Cotality Case-Shiller", "29 Oct 2026", "FRED: MORTGAGE30US", True),
    # em_imb
    ("em_imb", "EM external positions", "AMBER", "AMBER",
     "EMBI GD spread 187bp end-Q3 despite 10y +82bp in Q3; EM debt inflows above 2025's total.",
     "Risk is a dollar + US rates shock hitting energy importers.", "SSGA Q3 2026; UBS Oct 2026", "Sep 2026", "-", True),
    ("em_imb", "Reserve adequacy / external debt", "AMBER", "AMBER",
     "Uneven across EMs; weaker sovereigns face higher rollover costs (carried).", "Short-dated external debt is the weak spot.",
     "World Bank GEP (carried)", "Jun 2026", "-", False),
    # ai_fin
    ("ai_fin", "Off-balance-sheet obligations", "RED", "",
     "Moody's: ~$970bn of hyperscaler lease commitments, ~$660bn not yet on balance sheet; a WSJ tally incl. chip purchase commitments is ~$2.4tn.",
     "Fixed commitments behave like debt in a downturn but are not counted as debt.",
     "Van Nieuwerburgh (2026) BPEA draft, citing Moody's and WSJ", "Sep 2026", "narrative: ai_obs", True),
    ("ai_fin", "Circular and vendor financing", "AMBER", "",
     "Nvidia invested $30bn in OpenAI (Feb); its Ohio data-centre backstop was cut from $250bn to $120bn after investor pushback; up to $350bn of GPU financing under discussion.",
     "Supplier, investor and lender are the same party: one problem becomes two.",
     "Axios 27 Jul; Benzinga 17 Aug; Yahoo Finance", "Aug 2026", "-", True),
    ("ai_fin", "Debt-funded capex", "RED", "",
     "Big-4 Q3 capex ~$203bn; capex exceeded operating cash flow at Alphabet, Amazon and Meta. 2026 guides $720-740bn; 2027 consensus ~$935bn.",
     "Each step up in capex now needs external funding.",
     "Company Q3 results via Decoding Discontinuity; Yield Theory 4 Oct", "Q3 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", True),
    # vol
    ("vol", "VIX (equity)", "AMBER", "GREEN",
     "~28.2 on 5 Nov (+11.6pts), highest since 31 Mar; 16.6 the day before.",
     "Some feeds show ~23 at the close: confirm the official print.", "CNBC 5 Nov; Cboe", "5 Nov 2026", "FRED: VIXCLS", True),
    ("vol", "MOVE (rates)", "AMBER", "GREEN",
     "Peaked at 113.6 on 5 Oct; ~94-100 in early Nov.", "A new break above ~110 would confirm rates-driven stress.",
     "StreetStats; Amundi Oct 2026", "4 Nov 2026", "Yahoo: ^MOVE", True),
    ("vol", "FX volatility / DXY", "GREEN", "GREEN",
     "DXY ~101-102; no haven bid for the dollar on 5 Nov.", "Dollar strength + FX-vol spike = global dollar stress.",
     "Vantage 5 Nov", "5 Nov 2026", "DXY Curncy", True),
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "340bp (3 Nov), from 260bp on 28 Aug and 314bp on 28 Oct. CCC 1,316bp.",
     "Speed matters: a gap above ~400bp would confirm credit is following equities.", "FRED BAMLH0A0HYM2", "3 Nov 2026", "FRED: BAMLH0A0HYM2", True),
    ("spread_chg", "IG / BBB OAS (change)", "AMBER", "GREEN",
     "IG 94bp (30 Oct), from 82bp in early Oct.", "IG above 100bp would show repricing beyond AI issuers.",
     "FRED BAMLC0A0CM", "30 Oct 2026", "FRED: BAMLC0A0CM", True),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", True),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "EM contained; French-German 10y ~140bp, about double this year.", "Sovereign-yield shock is an IMF headline risk.",
     "SSGA Q3 EMD; NBC Oct 2026", "Oct 2026", "-", True),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "+38bp on 5 Nov (10y 4.84%, 2y 4.47%). Fed hiked to 3.75-4.00% in Sep; held 28 Oct.", "Bull steepener on the selloff.",
     "Closing Look 5 Nov; Fed 28 Oct", "5 Nov 2026", "FRED: T10Y2Y", True),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "About +75bp on 4 Nov, positive again after the early-2026 inversion.", "Recessions tend to start after the re-steepening.",
     "StreetStats 4 Nov", "4 Nov 2026", "FRED: T10Y3M", True),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "Oracle 5y CDS ~263bp and CoreWeave ~982bp, both records; spreads widening across the AI complex.",
     "Credit priced AI risk before equities did. Watch spread from AI names into IG indices.",
     "Motley Fool 5 Nov; GSAM Market Pulse Nov 2026", "5 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", True),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "5 Nov: Qualcomm miss, Micron -12% on order doubts; Democratic Congress raises AI regulation risk. Hyperscalers still guide 2027 capex higher.",
     "A capex guidance cut would be the decisive trigger; next test is Q4 guidance in late Jan.",
     "investingLive 5 Nov; Bloomberg 5 Nov; company Q3 calls", "5 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure; BDC outflows tied to AI-software fears.",
     "First project-level cracks. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; FT via Disruption Banking 24 Sep; PitchBook LCD Q3", "Oct 2026", "narrative: ai_obs", True),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "Mag-7 lost >$1tn and Nvidia -9% on 5 Nov; Nasdaq 100 -6.4%. Short yen (USDJPY ~158) and near-record margin debt still in place.",
     "Unwind risk is live. Watch spread to credit and the yen carry trade.", "CNBC 5 Nov; investingLive 5 Nov", "5 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "5 Nov: all 11 sectors red, decliners 2,344 vs 416 advancers; 2y yield -12bp so stocks and bonds still moved apart.",
     "Stocks and bonds falling together would flag broad deleveraging.", "CNBC 5 Nov; investingLive 5 Nov", "5 Nov 2026", "model: stock_bond", True),
    # sifi
    ("sifi", "G-SIB systemic footprint", "AMBER", "AMBER",
     "Size and cross-border activity remain structurally high.", "FSB 2026 list due mid-Nov.",
     "FSB / BCBS", "Nov 2025 list", "manual_overlay: gsib_score_max", False),
    ("sifi", "Interbank counterparty stress", "GREEN", "GREEN",
     "No elevated interbank stress; funding orderly.", "Data lag; read via money-market spreads.", "Composite", "Nov 2026", "-", True),
    # ai_amp
    ("ai_amp", "Index concentration", "RED", "",
     "Top 10 ~39% of the S&P 500 (Nov), top 15 a record ~47% (Oct); Nvidia alone ~7-8%.",
     "Passive and benchmarked money is one AI trade; losses correlate.", "Chartrow Nov 2026; Crypto Briefing 20 Oct", "Nov 2026", "model: concentration", True),
    ("ai_amp", "Leverage on AI exposure", "AMBER", "",
     "Leveraged ETFs more than doubled in assets over the past year; margin debt $1.48tn; retail sold a net $358m of single stocks on 5 Nov.",
     "Forced selling would hit the same names first.", "TheStreet Sep 2026; Pomegra 5 Nov; FINRA", "Nov 2026", "-", True),
    # bank_cap
    ("bank_cap", "CET1 and stress test", "GREEN", "GREEN",
     "All 32 banks passed DFAST 2026 (trough 11.2% vs 4.5% min). IMF Oct stress test: core banks hold under AI + bond + energy shock.",
     "Refresh with Q3 aggregate CET1.", "Fed DFAST 2026; IMF GFSR Oct 2026", "Oct 2026", "manual_overlay: cet1_aggregate", True),
    ("bank_cap", "Liquidity (LCR / NSFR)", "GREEN", "GREEN",
     "Comfortably above requirements (carried).", "Deposit stability better than 2023.", "Bank 10-Qs (carried)", "Jun 2026", "-", False),
    # mm_spreads
    ("mm_spreads", "SOFR-OIS / commercial paper", "GREEN", "GREEN",
     "3m CP averaged 3.95% vs 3.91% for T-bills in Q3 (~4bp).", "Short-term funding orderly.",
     "H.15 via US Dept of Education", "Q3 2026", "FRED: CPF3M - DTB3", True),
    ("mm_spreads", "Cross-currency basis (EUR, JPY)", "GREEN", "GREEN",
     "Basis not refreshed; USD/JPY ~158, off the 163.9 high of 29 Jul.", "Basis widening + yen squeeze = stress trigger.",
     "BBG (carried); Trading Economics", "5 Nov 2026", "BBG: .JYCCBS3M G Index", False),
    # repo
    ("repo", "SOFR vs IORB", "AMBER", "AMBER",
     "Sep 30 quarter-end SOFR 3.90% = IORB. Since 29 Oct SOFR 3.94-3.97%, 4-7bp above IORB.",
     "Weeks above IORB = reserves no longer ample.", "FRED SOFR; Fed 28 Oct", "4 Nov 2026", "FRED: SOFR - IORB", True),
    ("repo", "Reserves and reverse repo", "AMBER", "AMBER",
     "Reserves ~$2.97tn (21 Oct); ON RRP ~$0-5bn; TGA ~$0.95tn.", "No RRP cushion: the next drain hits reserves.",
     "Fed H.4.1", "21 Oct 2026", "FRED: WRESBAL, RRPONTSYD", True),
    # cb_fac
    ("cb_fac", "Standing Repo Facility", "GREEN", "AMBER",
     "Take-up near zero by Oct 2026 (record $74.6bn on 31 Dec 2025).", "Heavy repeated use would be a red flag.",
     "NY Fed via YX Insights", "Oct 2026", "FRED: RPONTSYD", True),
    ("cb_fac", "Discount window / FX swap lines", "GREEN", "GREEN",
     "No elevated usage (carried).", "Swap-line draws = global dollar stress.", "Fed H.4.1 (carried)", "Jul 2026", "FRED: SWPT", False),
    # mkt_liq
    ("mkt_liq", "Financial conditions (NFCI)", "GREEN", "GREEN",
     "NFCI -0.46 (30 Oct), tighter for 5 weeks from -0.50.", "Still loose; direction has turned.", "FRED NFCI", "30 Oct 2026", "FRED: NFCI", True),
    ("mkt_liq", "Treasury market depth", "GREEN", "GREEN",
     "Not refreshed; MOVE >110 in Oct passed without reported dysfunction.", "Watch auction tails.",
     "BBG (carried)", "Jul 2026", "model: ust_liq", False),
    # ai_abs
    ("ai_abs", "Bank and insurer exposure", "AMBER", "",
     "HSBC working on an SRT on >$1bn of data-centre loans; Barclays seeking insurance on >$10bn of AI-infrastructure credit; Deutsche ~$2bn SRT. Some insurers near capacity.",
     "Direct bank exposure to AI-adjacent industries is ~0.8% of assets (Chicago Fed): small, but rising and indirect via private credit.",
     "Insurance Journal 30 Oct; Disruption Banking 24 Sep", "30 Oct 2026", "-", True),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Yields on AI-linked bonds and loans have jumped; large data-centre loan syndications have dragged for months.",
     "If banks and insurers stop taking AI credit, the build-out loses funding and the trigger becomes systemic.",
     "Insurance Journal 30 Oct; Startup Fortune 11 Oct", "Oct 2026", "-", True),
]

SOURCES = ("FRED / St. Louis Fed; Federal Reserve (Z.1 Sep 2026, H.4.1, FOMC 28 Oct 2026); NY Fed; IMF GFSR & WEO (Oct 2026); "
           "FINRA via Advisor Perspectives; ICE BofA OAS; Cboe; Freddie Mac; S&P Cotality Case-Shiller; Shiller CAPE; "
           "SSGA / UBS EM notes; OFR; company Q3 2026 results; press coverage (CNBC, Bloomberg, Insurance Journal, investingLive). "
           "Signals apply judgement to illustrative thresholds and are not an official risk view.")

RANK = {"GREEN": 0, "AMBER": 1, "RED": 2}


def rollup(signals):
    """Stage x lens roll-up: mean rank (GREEN 0, AMBER 1, RED 2); RED if >= 1.5, AMBER if >= 0.75."""
    s = [RANK[x] for x in signals if x in RANK]
    if not s:
        return ""
    m = sum(s) / len(s)
    return "RED" if m >= 1.5 else "AMBER" if m >= 0.75 else "GREEN"


def payload():
    by_key = {r[0]: r for r in SUMMARY}
    summary = [dict(zip(["key", "stage", "lens", "indicator", "signal", "prev", "comment"], r)) for r in SUMMARY]
    detail = []
    for r in DETAIL:
        d = dict(zip(["key", "metric", "signal", "prev", "reading", "note", "source", "asof", "code", "refreshed"], r))
        d["stage"], d["lens"] = by_key[d["key"]][1], by_key[d["key"]][2]
        detail.append(d)
    grid = {}
    for sk, *_ in STAGES:
        for lk, _ in LENSES:
            rows = [s for s in summary if s["stage"] == sk and s["lens"] == lk]
            grid[f"{sk}|{lk}"] = {"now": rollup([r["signal"] for r in rows]),
                                  "prev": rollup([r["prev"] for r in rows]),
                                  "n": {k: sum(r["signal"] == k for r in rows) for k in RANK}}
    return {"asof": AS_OF, "prev_asof": PREV_ASOF, "sources": SOURCES,
            "stages": [dict(zip(["key", "n", "name", "q", "model_link"], s)) for s in STAGES],
            "lenses": [dict(zip(["key", "name"], l)) for l in LENSES],
            "summary": summary, "detail": detail, "grid": grid}


def _check():
    keys = {r[0] for r in SUMMARY}
    assert all(r[0] in keys for r in DETAIL), "detail row points to unknown key"
    assert all(any(d[0] == k for d in DETAIL) for k in keys), "summary row without detail"


_check()
