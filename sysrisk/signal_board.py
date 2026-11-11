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
AS_OF = "11 Nov 2026 (US close)"
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
     "Hedge-fund leverage at records; Q3 private-credit tenders only ~40% met, record defaults; a small listed BDC sold at 90% of NAV after trading ~78% below it; margin debt near record.", "AMBER"),
    ("valuation", "fragility", "broad", "Valuation stretch (credit pricing, equities, housing)",
     ["ebp_sentiment", "eq_val", "house_gap", "low_vol"],
     "Credit priced for perfection, equities near record valuations (CAPE ~41); 30y mortgage 7.18%.", "RED"),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", [],
     "EM spreads resilient; energy importers and weak sovereigns are the soft spots.", "AMBER"),
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", [],
     "Capex exceeds operating cash flow at three of four hyperscalers; Oracle raised $20bn of stock and 7-8.65% bonds; leases keep much off balance sheet.", ""),
    ("vol", "triggers", "broad", "Volatility shock (VIX, MOVE, FX vol)", ["vix", "move", "fx_vol"],
     "VIX 17.5 on 11 Nov, a one-week low and fourth daily fall; down from the 28.2 spike; MOVE peaked at 114 in Oct.", "GREEN"),
    ("spread_chg", "triggers", "broad", "Credit spread widening", ["credit_widen", "em_stress"],
     "HY 334bp on 9 Nov (348bp peak on 5 Nov, +74bp from Aug low), CCC ~1,317bp on 6 Nov; easing, and well below the ~400bp line that would confirm credit following equities.", "AMBER"),
    ("stress", "triggers", "broad", "Realised stress (stress indices, bank equity, credit-line draws, lending)",
     ["stlfsi", "nfci", "bank_rel_dd", "ci_draw", "pc_mark", "sloos_ci", "cre_delinq"],
     "Stress indices still below normal; companies drawing credit lines fast; private-credit marks lagging HY.", "GREEN"),
    ("curve", "triggers", "broad", "Term spreads / yield curve", [],
     "Bear flattening after hot Oct CPI: 2y +17bp to 4.73%, 10y 4.98%, 2s10s ~+25bp on 10 Nov; a December hike is now priced.", "AMBER"),
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", [],
     "Fired in equities on 5 Nov; CoreWeave results sparked a relief rally on 11 Nov (CoreWeave +25%, chips +5.7%), but AI issuers' CDS were last seen at records and CoreWeave says it will not borrow unsecured at current yields.", ""),
    ("crowded", "amplifiers", "broad", "Crowded trades and positioning", ["lf_ust_short"],
     "AI trade unwound last week (tech -8%); whipsaw since: 9 Nov up, 10 Nov down, 11 Nov up again (Nasdaq +1.6%, chips +5.7%); short-yen (USD/JPY ~158.8) still large.", "AMBER"),
    ("corr", "amplifiers", "broad", "Correlation and common drivers", ["absorption", "stock_bond", "dy_total", "granger_dgc"],
     "Financials driven by a few common factors; stocks moving as one block, with tech driving the index both ways; on 10 Nov stocks and bonds fell together on inflation.", "GREEN"),
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
     "Banks hedging and selling down data-centre loans (ING auction, bids 19 Nov); insurers of AI loans lobbying for capital relief; lenders wary of new AI deals; JPMorgan holds $29bn of data-centre loans.", ""),
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
     "Q3 tenders: NAV BDCs asked $13.8bn (11.5% of NAV), ~40% met, $8.2bn unmet. Final filings to 5 Nov: Blue Owl OTIC 39% asked / 12.8% paid, Apollo ADS 33.9% paid, BCRED 49.9% paid. Fitch default rate ~6%, a record (carried). Australia's ASIC (10 Nov): opacity and weak disclosure persist. 11 Nov: Investcorp Credit BDC (ICMB) agreed to merge into BC Partners' BCIC at 90% of its $2.76 NAV; ICMB closed at $0.61 on 9 Nov, ~78% below NAV; its committee cites a 'late-stage credit cycle'.",
     "Gates hold, so stress shows in marks, PIK, gates and now consolidation of sub-scale BDCs. Stanger: demand may have peaked in Q2. Watch Q4 tenders and Q3 BDC non-accruals.",
     "SEC Schedule TO-I/A via CrowdfundedWealth tracker (upd. 7 Nov); ABC News 10 Nov (ASIC); ICMB/BCIC release, GlobeNewswire 11 Nov; Valuation Research Q3 2026", "11 Nov 2026", "manual_overlay: bdc_nonaccrual", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct, 98.9th percentile since 1881; only 1999-2000 was higher.",
     "Signals low 10-year returns; not a timing tool.", "Shiller data via thetrading.tools", "Oct 2026", "multpl / Shiller ie_data", False),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "30y mortgage 7.18% (5 Nov), from 7.24% on 29 Oct and a 7.40% Oct peak; ~6.2% a year ago. Case-Shiller +2.1-2.7% y/y; real prices falling.",
     "Affordability worse than July. Next PMMS 12 Nov.", "Freddie Mac PMMS via MoveWithMomentum 5 Nov; S&P Cotality Case-Shiller", "5 Nov 2026", "FRED: MORTGAGE30US", False),
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
     "Company Q3 results via Decoding Discontinuity; Yahoo Finance / TIKR 3 Nov", "2 Nov 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", False),
    # vol
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "334bp (9 Nov), from 342bp on 6 Nov and a 348bp peak on 5 Nov (the 52-week high); 260bp on 28 Aug. CCC 1,317bp on 6 Nov (no newer CCC print found). No print yet for 10 Nov; 11 Nov bond market closed.",
     "Speed matters: a gap above ~400bp would confirm credit is following equities.", "FRED BAMLH0A0HYM2 via Equibles; BAMLH0A3HYC (ICE BofA)", "9 Nov 2026", "FRED: BAMLH0A0HYM2", True),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", False),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "EM contained; French-German 10y ~140bp, about double this year.", "Sovereign-yield shock is an IMF headline risk.",
     "SSGA Q3 EMD; NBC Oct 2026", "Oct 2026", "-", False),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "~+25bp on 10 Nov (2y 4.73%, +17bp; 10y 4.98%, briefly above 5%), from ~+29bp on 9 Nov. Oct CPI hot: headline +0.4% m/m (cons. +0.3%), core +0.3% (cons. +0.2%), third 0.3% core month; no y/y published. Futures ~84% for a 25bp hike on 9 Dec, ~15% for 50bp; Waller open to 50bp. Fed at 3.75-4.00%.",
     "Bear flattening as the front end prices hikes. A hiking Fed into an AI-credit wobble is the combination to watch.",
     "Avalon Capital Research close 10 Nov; Yahoo Finance live 10 Nov (CME FedWatch); BLS CPI 10 Nov", "10 Nov 2026", "FRED: T10Y2Y", False),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "+67bp on 6 Nov (+69bp on 4 Nov, +74bp on 3 Nov), positive since the early-2026 inversion ended.", "Recessions tend to start after the re-steepening.",
     "FRED T10Y3M", "6 Nov 2026", "FRED: T10Y3M", False),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "Oracle 5y CDS a record ~288bp, SoftBank ~424bp, CoreWeave above 1,000bp; Amazon, Alphabet, Meta and Nvidia CDS also at record wides (6 Nov, no newer CDS print). BofA (9 Nov): 10y hyperscaler bond spreads ~50bp wider this year vs ~20bp for high-grade non-AI industrials; Meta bonds below par.",
     "Credit priced AI risk before equities did; the equity bounce has not shown up in CDS. Watch CoreWeave bonds after Q3 results.",
     "Reuters 9 Nov (citing BofA); Reuters / S&P Global MI via TradingView; CNBC 6 Nov", "9 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", False),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "11 Nov relief rally on CoreWeave Q3: S&P 500 +1.31% to 7,619, Nasdaq +1.60%, chip index +5.7%, CoreWeave +24.7% to $60.77; Nvidia rebounded (Baird cut it to neutral). CoreWeave Q3: revenue $3.66bn, backlog ~$132.5bn, 2026 capex $37-39bn; net loss $709m, interest cost $846m. CEO: will not use the unsecured debt market at current yields; expects ~$9bn of customer prepayments in the next three months.",
     "Demand still strong; the pressure is funding cost, not orders, and the largest neocloud is now shut out of unsecured debt by price. A capex guidance cut would be the decisive trigger; next test Q4 guidance late Jan.",
     "TheStreet / Reuters via MarketScreener closes 11 Nov; 24/7 Wall St 11 Nov; CoreWeave 8-K 10 Nov", "11 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure. 9 Nov press report: ~$13.4bn of fixed-rate data-centre debt matures in 2027 and would reprice ~2.85pp higher (BNEF, approximate); TeraWulf and Crusoe builds delayed.",
     "First project-level cracks. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; FT via Disruption Banking 24 Sep; BusinessDay 9 Nov citing BloombergNEF", "9 Nov 2026", "narrative: ai_obs", False),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "Week to 6 Nov: S&P 500 -2.7%, tech -8.2%. Since then a whipsaw: 9 Nov up (Nasdaq-100 +3.4%), 10 Nov down (Nvidia -5.5%), 11 Nov up (Nasdaq +1.60%, chips +5.7% with every component up, CoreWeave +24.7%); Nasdaq still -1.05% over 5 days. Volume below its 20-day average on 11 Nov. USD/JPY 158.8; near-record margin debt (carried).",
     "Unwind is part-way through, not finished. Watch spread to credit and the yen carry trade.", "Reuters via MarketScreener 11 Nov; TheStreet 11 Nov; JournalArta 10 Nov", "11 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "11 Nov: tech +2.7% led all 11 sectors, NYSE breadth 1.48:1 up; bond market shut (Veterans Day), so no stock-bond read. 10 Nov: stocks and bonds fell together on hot CPI (S&P -0.38%, 10y +~10bp to 4.98%). Stocks moving as one block on AI news.",
     "Stocks and bonds falling together on several days running would flag broad deleveraging; one inflation day is not that yet.", "Reuters via MarketScreener 11 Nov; JournalArta 10 Nov; Avalon 10 Nov", "11 Nov 2026", "model: stock_bond", True),
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
     "ING auctioning ~$500m of 12 data-centre loans incl. a $25m Stargate New Mexico slice, bids due 19 Nov. HSBC SRT on >$1bn; Barclays seeking insurance on >$10bn; Deutsche ~$2bn SRT. Some insurers near capacity; broker Marsh (11 Nov) urged the Fed to ease up on banks that insure AI loans.",
     "Direct bank exposure to AI-adjacent industries is ~0.8% of assets (Chicago Fed): small, but rising and indirect via private credit. JPMorgan: $29bn of data-centre loans at end-Q3, 12% of its CRE book (8% three years ago).",
     "Bloomberg via Briefs 6 Nov; Bloomberg headline 11 Nov (Marsh); Reuters 9 Nov; Insurance Journal 30 Oct", "11 Nov 2026", "-", True),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Second source now: Reuters (9 Nov) reports banks and investors growing wary of AI debt after the selloff; some lenders reluctant even with strong guarantors. Funding still flows: CoreWeave raised ~$4.2bn of convertibles and a $2.6bn loan in Q3; Nebius took a $3.5bn Citi loan in Oct. Goldman sees ~$420bn of hyperscaler debt issuance in 2027.",
     "Wariness confirmed, but deals still close at a higher price. Move to RED on a pulled or failed syndication, or a weak ING auction (bids 19 Nov).",
     "Reuters 9 Nov; BusinessDay 9 Nov; CoreWeave 8-K 10 Nov", "9 Nov 2026", "-", False),
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
