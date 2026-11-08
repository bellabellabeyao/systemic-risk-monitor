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
AS_OF = "6 Nov 2026 (US close)"
PREV_ASOF = "29 Jul 2026"

# key, number, display name, question, model link (sysrisk.config.PILLARS value)
STAGES = [
    ("fragility", "1", "Fragility", "Why is the system vulnerable?", "Build-up"),
    ("triggers", "2", "Triggers", "What sets it off?", "Trigger"),
    ("amplifiers", "3", "Amplifiers", "Why does it spread?", "Contagion"),
    ("threshold", "4", "Systemic threshold", "When is it systemic?", "Shock absorbers"),
]
LENSES = [("broad", "Broad system"), ("ai", "AI channel")]

# ---------------------------------------------------------------- themes (one row per thing we monitor)
# key, stage, lens, theme, model series ids (sysrisk.config), comment, July board signal (for "change")
# The theme score is computed (see sysrisk/unified.py) from its model series and judgement series below.
THEMES = [
    ("agg_lev", "fragility", "broad", "Aggregate leverage (household, corporate, government, credit gap)",
     ["credit_gap", "hh_dsr", "hh_debt", "corp_debt", "rzone", "fiscal"],
     "Households deleveraged; corporate and government debt high. Total non-financial debt flat at 2.59x GDP.", "AMBER"),
    ("nonbank", "fragility", "broad", "Non-bank leverage (margin, hedge funds, private credit)",
     ["nbfi_leverage", "margin", "hf_repo", "hf_rv_lev", "bank_nbfi"],
     "Hedge-fund leverage at records; Q3 private-credit tenders only ~40% met, record defaults; margin debt near its June record.", "AMBER"),
    ("valuation", "fragility", "broad", "Valuation stretch (credit pricing, equities, housing)",
     ["ebp_sentiment", "eq_val", "house_gap", "low_vol"],
     "Credit priced for perfection, equities near record valuations (CAPE ~41).", "RED"),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", [],
     "EM spreads resilient; energy importers and weak sovereigns are the soft spots.", "AMBER"),
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", [],
     "Capex exceeds operating cash flow at three of four hyperscalers; Oracle raised $20bn of stock and 7-8.65% bonds; leases keep much off balance sheet.", ""),
    ("vol", "triggers", "broad", "Volatility shock (VIX, MOVE, FX vol)", ["vix", "move", "fx_vol"],
     "VIX 25.6 on 6 Nov, off the 28.2 spike but +32% on the week; MOVE peaked at 114 in Oct.", "GREEN"),
    ("spread_chg", "triggers", "broad", "Credit spread widening", ["credit_widen", "em_stress"],
     "HY 348bp on 5 Nov (+88bp from Aug low), still below the ~400bp line that would confirm credit following equities.", "AMBER"),
    ("stress", "triggers", "broad", "Realised stress (stress indices, bank equity, credit-line draws, lending)",
     ["stlfsi", "nfci", "bank_rel_dd", "ci_draw", "pc_mark", "sloos_ci", "cre_delinq"],
     "Stress indices still below normal; companies drawing credit lines fast; private-credit marks lagging HY.", "GREEN"),
    ("curve", "triggers", "broad", "Term spreads / yield curve", [],
     "Curve positive: 2s10s +35bp, 3m10y +67bp on 6 Nov; strong payrolls (+165k) pushed front-end yields up.", "AMBER"),
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", [],
     "Fired in equities on 5 Nov, part-reversed 6 Nov (chips +4%); AI issuers' CDS at records; first data-centre project cracks.", ""),
    ("crowded", "amplifiers", "broad", "Crowded trades and positioning", ["lf_ust_short"],
     "AI trade unwinding: tech sector -8% on the week despite a 6 Nov bounce; short-yen and Treasury basis positions still large.", "AMBER"),
    ("corr", "amplifiers", "broad", "Correlation and common drivers", ["absorption", "stock_bond", "dy_total", "granger_dgc"],
     "Financials driven by a few common factors; 5 Nov sell-off hit every sector, 6 Nov bounce was narrow; bonds still hedge.", "GREEN"),
    ("sifi", "amplifiers", "broad", "Spillovers from large institutions", ["srisk_gdp", "dcovar_max", "dcovar_private", "dealer_lev"],
     "Capital shortfall in a crash still low; tail spillovers mid-range.", "AMBER"),
    ("ai_amp", "amplifiers", "ai", "AI concentration and leverage on AI exposure", ["concentration"],
     "Top 10 stocks ~39% of the S&P 500; leverage sits on the same names.", ""),
    ("bank_cap", "threshold", "broad", "Bank capital and liquidity", [],
     "Large banks well capitalised; IMF's weak-bank tail grew to 22% of assets.", "GREEN"),
    ("mm_spreads", "threshold", "broad", "Short-term funding (CP, cross-currency basis)", ["cp_spread", "a2p2", "fin_cp"],
     "Bank and corporate short-term funding cheap; no dollar shortage.", "GREEN"),
    ("repo", "threshold", "broad", "Repo, reserves and the reverse-repo cushion", ["reserves_gdp", "rrp_buffer", "sofr_iorb", "tgcr_iorb"],
     "Reverse-repo cushion gone; repo trading above the Fed floor since 29 Oct.", "AMBER"),
    ("cb_fac", "threshold", "broad", "Central bank backstops (repo facility, swap lines)", ["srf_usage", "swap_lines"],
     "Backstops ready and barely used.", "AMBER"),
    ("mkt_liq", "threshold", "broad", "Market liquidity and dollar funding", ["usd_6m"],
     "Dollar range-bound; Treasury depth not refreshed (Bloomberg).", "GREEN"),
    ("ai_abs", "threshold", "ai", "Absorption of AI credit losses (banks, insurers, credit supply)", [],
     "Banks hedging and selling down data-centre loans (ING auction 6 Nov); insurers near capacity; direct bank exposure still small.", ""),
]

# ---------------------------------------------------------------- underlying series
# judgement series (no usable model time series, or a different measure)
# key (-> THEMES), metric, signal, prev, reading, note/what to watch, source, as of, refresh code, refreshed
DETAIL = [
    # agg_lev
    ("agg_lev", "Total non-financial debt-to-GDP", "AMBER", "AMBER",
     "2.59x GDP in Q2, flat; $84.1tn outstanding.", "Stable in aggregate; mix tilting to government.",
     "Fed Z.1, 11 Sep 2026", "Q2 2026", "Z.1 table D.3", False),
    # nonbank
    ("nonbank", "Private credit", "RED", "AMBER",
     "Q3 tenders: NAV BDCs asked $13.8bn (11.5% of NAV), ~40% met, $8.2bn unmet. Final filings to 5 Nov: Blue Owl OTIC 39% asked / 12.8% paid, Apollo ADS 33.9% paid, BCRED 49.9% paid. Fitch default rate ~6%, a record (carried).",
     "Gates hold, so stress shows in marks, PIK and gates. Stanger: demand may have peaked in Q2. Watch Q4 tenders and Q3 BDC non-accruals.",
     "SEC Schedule TO-I/A via CrowdfundedWealth tracker (upd. 7 Nov); Stanger via AITech Model 5 Oct; Valuation Research Q3 2026", "5 Nov 2026", "manual_overlay: bdc_nonaccrual", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct, 98.9th percentile since 1881; only 1999-2000 was higher.",
     "Signals low 10-year returns; not a timing tool.", "Shiller data via thetrading.tools", "Oct 2026", "multpl / Shiller ie_data", False),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "30y mortgage 7.24% (29 Oct), off a 7.40% Oct peak. Case-Shiller +2.1-2.7% y/y; real prices falling.",
     "Affordability worse than July.", "Freddie Mac PMMS; S&P Cotality Case-Shiller", "29 Oct 2026", "FRED: MORTGAGE30US", False),
    # em_imb
    ("em_imb", "EM external positions", "AMBER", "AMBER",
     "EMBI GD spread 187bp end-Q3 despite 10y +82bp in Q3; EM debt inflows above 2025's total.",
     "Risk is a dollar + US rates shock hitting energy importers.", "SSGA Q3 2026; UBS Oct 2026", "Sep 2026", "-", False),
    ("em_imb", "Reserve adequacy / external debt", "AMBER", "AMBER",
     "Uneven across EMs; weaker sovereigns face higher rollover costs (carried).", "Short-dated external debt is the weak spot.",
     "World Bank GEP (carried)", "Jun 2026", "-", False),
    # ai_fin
    ("ai_fin", "Off-balance-sheet obligations", "RED", "",
     "Moody's: ~$970bn of hyperscaler lease commitments, ~$660bn not yet on balance sheet; a WSJ tally incl. chip purchase commitments is ~$2.4tn.",
     "Fixed commitments behave like debt in a downturn but are not counted as debt.",
     "Van Nieuwerburgh (2026) BPEA draft, citing Moody's and WSJ", "Sep 2026", "narrative: ai_obs", False),
    ("ai_fin", "Circular and vendor financing", "AMBER", "",
     "Nvidia invested $30bn in OpenAI (Feb); its Ohio data-centre backstop was cut from $250bn to $120bn after investor pushback; up to $350bn of GPU financing under discussion.",
     "Supplier, investor and lender are the same party: one problem becomes two.",
     "Axios 27 Jul; Benzinga 17 Aug; Yahoo Finance", "Aug 2026", "-", False),
    ("ai_fin", "Debt-funded capex", "RED", "",
     "Big-4 Q3 capex ~$203bn; capex exceeded operating cash flow at Alphabet, Amazon and Meta. Oracle priced $20bn on 2 Nov: ~$10bn stock at $116 plus $10bn notes at 7-8.65%, part of ~$40bn planned for FY27.",
     "Each step up in capex now needs external funding, at rising coupons.",
     "Company Q3 results via Decoding Discontinuity; Yahoo Finance / TIKR 3 Nov", "2 Nov 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", True),
    # vol
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "348bp (5 Nov), from 340bp on 3 Nov, 314bp on 28 Oct and 260bp on 28 Aug. CCC 1,316bp (3 Nov, carried).",
     "Speed matters: a gap above ~400bp would confirm credit is following equities.", "FRED BAMLH0A0HYM2 (ICE BofA)", "5 Nov 2026", "FRED: BAMLH0A0HYM2", True),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", False),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "EM contained; French-German 10y ~140bp, about double this year.", "Sovereign-yield shock is an IMF headline risk.",
     "SSGA Q3 EMD; NBC Oct 2026", "Oct 2026", "-", False),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "+35bp on 6 Nov (10y 4.86%, 2y 4.51%). Oct payrolls +165k, unemployment 4.1%; December hike odds rose. Fed at 3.75-4.00%.",
     "Front end sold off on the jobs beat: bear flattening after the 5 Nov steepener.",
     "FRED T10Y2Y; Closing Look 6 Nov; Yahoo Finance 6 Nov", "6 Nov 2026", "FRED: T10Y2Y", True),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "+67bp on 6 Nov (+69bp on 4 Nov, +74bp on 3 Nov), positive since the early-2026 inversion ended.", "Recessions tend to start after the re-steepening.",
     "FRED T10Y3M", "6 Nov 2026", "FRED: T10Y3M", True),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "Oracle 5y CDS ~263bp and CoreWeave ~982bp, both records; spreads widening across the AI complex.",
     "Credit priced AI risk before equities did. Watch spread from AI names into IG indices.",
     "Motley Fool 5 Nov; GSAM Market Pulse Nov 2026", "5 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", False),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "5 Nov: Qualcomm miss, Micron -12%, Democratic Congress raises AI/data-centre regulation risk. 6 Nov part-reversal: SOX +4.2%, Nvidia +2.8%, AMD +11%; tech sector still -8% on the week.",
     "A capex guidance cut would be the decisive trigger; next tests CoreWeave results 10 Nov, Q4 guidance late Jan.",
     "investingLive 5 Nov; The Closing Print 6 Nov; Closing Look 6 Nov", "6 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure; BDC outflows tied to AI-software fears.",
     "First project-level cracks. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; FT via Disruption Banking 24 Sep; PitchBook LCD Q3", "Oct 2026", "narrative: ai_obs", False),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "Week to 6 Nov: S&P 500 -2.7%, Nasdaq -3.4%, tech sector -8.2% despite a 6 Nov bounce. 5 Nov ETF outflows: SPY -$5.4bn, QQQ -$2.3bn. Short yen (USDJPY ~158.4) and near-record margin debt still in place.",
     "Unwind risk is live. Watch spread to credit and the yen carry trade.", "The Closing Print 6 Nov; Closing Look 6 Nov; CNBC 5 Nov", "6 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "5 Nov: all 11 sectors red, 2y yield -12bp. 6 Nov bounce narrow: S&P ~184 up vs ~318 down, equal-weight -0.4%; yields rose on jobs as stocks rose.",
     "Stocks and bonds falling together would flag broad deleveraging.", "The Closing Print 6 Nov; Closing Look 6 Nov; CNBC 5 Nov", "6 Nov 2026", "model: stock_bond", True),
    # sifi
    ("sifi", "G-SIB systemic footprint", "AMBER", "AMBER",
     "Size and cross-border activity remain structurally high.", "FSB 2026 list due mid-Nov.",
     "FSB / BCBS", "Nov 2025 list", "manual_overlay: gsib_score_max", False),
    ("sifi", "Interbank counterparty stress", "GREEN", "GREEN",
     "No elevated interbank stress; funding orderly.", "Data lag; read via money-market spreads.", "Composite", "Nov 2026", "-", False),
    # ai_amp
    ("ai_amp", "Index concentration", "RED", "",
     "Top 10 ~39% of the S&P 500 (Nov), top 15 a record ~47% (Oct); Nvidia alone ~7-8%.",
     "Passive and benchmarked money is one AI trade; losses correlate.", "Chartrow Nov 2026; Crypto Briefing 20 Oct", "Nov 2026", "model: concentration", False),
    ("ai_amp", "Leverage on AI exposure", "AMBER", "",
     "Leveraged ETFs more than doubled in assets over the past year; margin debt $1.48tn; retail sold a net $358m of single stocks on 5 Nov.",
     "Forced selling would hit the same names first.", "TheStreet Sep 2026; Pomegra 5 Nov; FINRA", "Nov 2026", "-", False),
    # bank_cap
    ("bank_cap", "CET1 and stress test", "GREEN", "GREEN",
     "All 32 banks passed DFAST 2026 (trough 11.2% vs 4.5% min). IMF Oct stress test: core banks hold under AI + bond + energy shock.",
     "Refresh with Q3 aggregate CET1.", "Fed DFAST 2026; IMF GFSR Oct 2026", "Oct 2026", "manual_overlay: cet1_aggregate", False),
    ("bank_cap", "Liquidity (LCR / NSFR)", "GREEN", "GREEN",
     "Comfortably above requirements (carried).", "Deposit stability better than 2023.", "Bank 10-Qs (carried)", "Jun 2026", "-", False),
    # mm_spreads
    ("mm_spreads", "Cross-currency basis (EUR, JPY)", "GREEN", "GREEN",
     "Basis not refreshed; USD/JPY ~158, off the 163.9 high of 29 Jul.", "Basis widening + yen squeeze = stress trigger.",
     "BBG (carried); Trading Economics", "5 Nov 2026", "BBG: .JYCCBS3M G Index", False),
    # repo
    # cb_fac
    # mkt_liq
    ("mkt_liq", "Treasury market depth", "GREEN", "GREEN",
     "Not refreshed; MOVE >110 in Oct passed without reported dysfunction.", "Watch auction tails.",
     "BBG (carried)", "Jul 2026", "model: ust_liq", False),
    # ai_abs
    ("ai_abs", "Bank and insurer exposure", "AMBER", "",
     "ING auctioning ~$500m of 12 data-centre loans incl. a $25m Stargate New Mexico slice, bids due 19 Nov. HSBC SRT on >$1bn; Barclays seeking insurance on >$10bn; Deutsche ~$2bn SRT. Some insurers near capacity.",
     "Direct bank exposure to AI-adjacent industries is ~0.8% of assets (Chicago Fed): small, but rising and indirect via private credit.",
     "Bloomberg via Briefs 6 Nov; Insurance Journal 30 Oct; Disruption Banking 24 Sep", "6 Nov 2026", "-", True),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Yields on AI-linked bonds and loans have jumped; large data-centre loan syndications have dragged for months.",
     "If banks and insurers stop taking AI credit, the build-out loses funding and the trigger becomes systemic.",
     "Insurance Journal 30 Oct; Startup Fortune 11 Oct", "Oct 2026", "-", False),
]

SOURCES = ("FRED / St. Louis Fed; Federal Reserve (Z.1 Sep 2026, H.4.1, FOMC 28 Oct 2026); NY Fed; IMF GFSR & WEO (Oct 2026); "
           "FINRA via Advisor Perspectives; ICE BofA OAS; Cboe; Freddie Mac; S&P Cotality Case-Shiller; Shiller CAPE; "
           "SSGA / UBS EM notes; OFR; company Q3 2026 results; press coverage (CNBC, Bloomberg, Insurance Journal, investingLive). "
           "Signals apply judgement to illustrative thresholds and are not an official risk view.")

RANK = {"GREEN": 0, "AMBER": 1, "RED": 2}
# One scale for every row: 0-100, higher = riskier. Colour bands match the index levels.
BANDS = (40, 65)                                   # GREEN < 40 <= AMBER < 65 <= RED
JUDGEMENT_SCORE = {"GREEN": 25, "AMBER": 52, "RED": 80}   # analyst traffic light -> score (mid-band)
WEIGHTS = {"screened": 1.0, "context": 0.5, "judgement": 0.5}


def colour(score):
    if score is None:
        return ""
    score = round(score)                            # colour the number people see
    return "RED" if score >= BANDS[1] else "AMBER" if score >= BANDS[0] else "GREEN"


def _check():
    keys = {t[0] for t in THEMES}
    assert all(r[0] in keys for r in DETAIL), "detail row points to unknown theme"
    assert all(t[4] or any(d[0] == t[0] for d in DETAIL) for t in THEMES), "theme with no series"


_check()
