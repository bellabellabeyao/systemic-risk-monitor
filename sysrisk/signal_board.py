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
AS_OF = "12 Nov 2026 (US close)"
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
     "Hedge-fund leverage at records; Q3 private-credit tenders only ~40% met; Fitch private-credit default rate a record 6.3%; BDC non-accruals rising and sub-scale BDCs consolidating; margin debt near record.", "AMBER"),
    ("valuation", "fragility", "broad", "Valuation stretch (credit pricing, equities, housing)",
     ["ebp_sentiment", "eq_val", "house_gap", "low_vol"],
     "Credit priced for perfection, equities near record valuations (CAPE ~40); 30y mortgage 7.11%, a fourth weekly fall.", "RED"),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", [],
     "EM corporate spreads resilient; dollar at a 19-month high and Argentina's spread jumped, so weak sovereigns and energy importers are the soft spots.", "AMBER"),
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", [],
     "Capex exceeds operating cash flow at three of four hyperscalers; hyperscaler bond issuance ~$296bn this year; suppliers to buy $26bn of Anthropic's IPO and Nvidia backstops neocloud debt, now with its CEO gone; leases keep much off balance sheet.", ""),
    ("vol", "triggers", "broad", "Volatility shock (VIX, MOVE, FX vol)", ["vix", "move", "fx_vol"],
     "VIX 18.7 on 12 Nov (+7%) after Nvidia's CEO resigned, ending four daily falls; well below the 28.2 spike; MOVE peaked at 114 in Oct.", "GREEN"),
    ("spread_chg", "triggers", "broad", "Credit spread widening", ["credit_widen", "em_stress"],
     "HY 330bp on 11 Nov (348bp peak on 5 Nov, +70bp from Aug low), CCC ~1,317bp on 6 Nov; easing, and well below the ~400bp line that would confirm credit following equities. French-German 10y ~147bp.", "AMBER"),
    ("stress", "triggers", "broad", "Realised stress (stress indices, bank equity, credit-line draws, lending)",
     ["stlfsi", "nfci", "bank_rel_dd", "ci_draw", "pc_mark", "sloos_ci", "cre_delinq"],
     "Stress indices still below normal; companies drawing credit lines fast; private-credit marks lagging HY; Oct loan survey: tighter standards for small firms, CRE and loans to non-banks.", "GREEN"),
    ("curve", "triggers", "broad", "Term spreads / yield curve", [],
     "Yields up again on 12 Nov: 2y 4.88%, 10y ~5.10%, 2s10s ~+22bp; weak 10y and 30y auctions; ~90% odds of a December hike, Daly sees more tightening.", "AMBER"),
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", [],
     "Fired in equities on 5 Nov; 11 Nov relief rally faded on 12 Nov when Nvidia's CEO resigned (Nvidia -4.3%, -14% at the open) and Nebius cut its 2026 revenue outlook (-17%). Credit eased: Nvidia CDS 139bp, CoreWeave bonds firmer, but AI CDS remain near records.", ""),
    ("crowded", "amplifiers", "broad", "Crowded trades and positioning", ["lf_ust_short"],
     "AI trade unwound last week (tech -8%); whipsaw since: up, down, up, and down again on 12 Nov (S&P -0.35%, small caps -1.7%, 377 of 500 stocks down); yen ~160, raising the risk of Japanese intervention.", "AMBER"),
    ("corr", "amplifiers", "broad", "Correlation and common drivers", ["absorption", "stock_bond", "dy_total", "granger_dgc"],
     "Financials driven by a few common factors; stocks moving as one block on AI news; stocks and bonds fell together on 10 and 12 Nov, two of the last three bond sessions.", "GREEN"),
    ("sifi", "amplifiers", "broad", "Spillovers from large institutions", ["srisk_gdp", "dcovar_max", "dcovar_private", "dealer_lev"],
     "Capital shortfall in a crash still low; tail spillovers mid-range; FSB 2026 G-SIB list not yet out.", "AMBER"),
    ("ai_amp", "amplifiers", "ai", "AI concentration and leverage on AI exposure", ["concentration"],
     "Top 10 stocks ~39% of the S&P 500; leverage sits on the same names.", ""),
    ("bank_cap", "threshold", "broad", "Bank capital and liquidity", [],
     "Large banks well capitalised (Q3 CET1 10.0-13.9% at the big four, three of four down q/q); IMF's weak-bank tail grew to 22% of assets.", "GREEN"),
    ("mm_spreads", "threshold", "broad", "Short-term funding (CP, cross-currency basis)", ["cp_spread", "a2p2", "fin_cp"],
     "Bank and corporate short-term funding cheap; no dollar shortage, though the yen is at ~160 and the dollar at a 19-month high.", "GREEN"),
    ("repo", "threshold", "broad", "Repo, reserves and the reverse-repo cushion", ["reserves_gdp", "rrp_buffer", "sofr_iorb", "tgcr_iorb"],
     "Reverse-repo cushion gone; repo traded above the Fed floor around month-end, easing since (SOFR ~2bp below IORB on 9 Nov).", "AMBER"),
    ("cb_fac", "threshold", "broad", "Central bank backstops (repo facility, swap lines)", ["srf_usage", "swap_lines"],
     "Backstops ready and barely used.", "AMBER"),
    ("mkt_liq", "threshold", "broad", "Market liquidity and dollar funding", ["usd_6m"],
     "Dollar at a 19-month high (DXY ~103); Treasury demand softer: the 10y auction tailed most since Feb with the lowest foreign share since Oct 2023, and the 30y tailed too.", "GREEN"),
    ("ai_abs", "threshold", "ai", "Absorption of AI credit losses (banks, insurers, credit supply)", [],
     "Banks hedging and selling down data-centre loans (ING auction, bids 19 Nov); insurers of AI loans lobbying for capital relief; lenders wary but deals still close, shifting to secured, investment-grade and prepayment-funded structures; JPMorgan holds $29bn of data-centre loans.", ""),
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
     "Fitch US private-credit default rate a record 6.3% (trailing 12m, Q3; 6.0% Q2), 91 defaulters; Proskauer index 2.41% (from 2.51%). Q3 tenders: NAV BDCs asked $13.8bn (11.5% of NAV), ~40% met, $8.2bn unmet (BCRED 49.9% paid, Apollo ADS 33.9%, Blue Owl OTIC 12.8%). Goldman Sachs BDC Q3 non-accruals 4.2% at fair value (2.9% Q2), NAV/share -3%. 11 Nov: Investcorp Credit BDC agreed to merge into BCIC at 90% of NAV after trading ~78% below it; 12 Nov Bloomberg: shrinking BDCs keep private credit on the sidelines as rates rise.",
     "Gates hold, so stress shows in defaults, non-accruals, gates and consolidation of sub-scale BDCs. Watch Q4 tender announcements and remaining Q3 BDC non-accruals.",
     "Fitch via MonitorDaily 30 Oct; Proskauer 27 Oct; GSBD Q3 results 6 Nov; SEC Schedule TO-I/A tracker; ICMB/BCIC release 11 Nov; Bloomberg headline 12 Nov", "12 Nov 2026", "manual_overlay: bdc_nonaccrual", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct (monthly), 98.9th percentile since 1881; only 1999-2000 was higher. Daily estimate ~40.2 on 11 Nov (multpl, different method).",
     "Signals low 10-year returns; not a timing tool.",
     "Shiller data via thetrading.tools; multpl 11 Nov", "11 Nov 2026", "multpl / Shiller ie_data", True),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "30y mortgage 7.11% (12 Nov), a fourth weekly fall, from 7.18% on 5 Nov and a 7.40% Oct peak; ~6.2% a year ago. Daily rates jumped after the hot CPI, so next week's survey may turn up. Case-Shiller +2.1-2.7% y/y; real prices falling.",
     "Affordability worse than July. Next PMMS 19 Nov.",
     "Freddie Mac PMMS via GlobeNewswire 12 Nov; CNBC 11 Nov; S&P Cotality Case-Shiller", "12 Nov 2026", "FRED: MORTGAGE30US", True),
    # em_imb
    ("em_imb", "EM external positions", "AMBER", "AMBER",
     "EMBI GD spread 187bp end-Q3 (no newer aggregate print); ICE BofA EM corporate spread 180bp (9 Nov). Weak spots widening: Argentina's EMBI spread 939bp on 6 Nov, from 787bp on 30 Oct. Dollar at a 19-month high (DXY ~103, 12 Nov).",
     "Risk is a dollar + US rates shock hitting energy importers; the dollar leg is now moving.",
     "SSGA Q3 2026; FRED BAMLEMCBPIOAS; Rio Times 6 Nov; Reuters via Trading & Investment News 12 Nov", "12 Nov 2026", "-", True),
    ("em_imb", "Reserve adequacy / external debt", "AMBER", "AMBER",
     "Uneven across EMs; weaker sovereigns face higher rollover costs (carried).", "Short-dated external debt is the weak spot.",
     "World Bank GEP (carried)", "Jun 2026", "-", False),
    # ai_fin
    ("ai_fin", "Off-balance-sheet obligations", "RED", "",
     "Moody's: ~$970bn of hyperscaler lease commitments, ~$660bn not yet on balance sheet; a WSJ tally incl. chip purchase commitments is ~$2.4tn.",
     "Fixed commitments behave like debt in a downturn but are not counted as debt.",
     "Van Nieuwerburgh (2026) BPEA draft, citing Moody's and WSJ", "Sep 2026", "narrative: ai_obs", False),
    ("ai_fin", "Circular and vendor financing", "RED", "",
     "Anthropic IPO (amended S-1, 10 Nov): seven suppliers to buy $26bn of shares at the IPO price (Google ~$10bn, Nvidia $10bn, AMD ~$2.5bn), of up to $64.4bn raised; pricing 18 Nov. Nvidia rents back unused neocloud GPUs and may backstop up to ~$125bn of a $500bn financing platform (Fortune). 12 Nov: Nvidia's CEO resigned; Bloomberg says its $10bn Anthropic pledge is under scrutiny.",
     "Supplier, investor and lender are the same party: one problem becomes two. Moved to RED: circularity is growing and the main guarantor's standing is now in question. Watch Nvidia Q3 (17 Nov) and Anthropic pricing.",
     "Dataconomy 12 Nov (Anthropic S-1/A); Fortune 12 Nov; Bloomberg headline 12 Nov; Nvidia 8-K 12 Nov", "12 Nov 2026", "-", True),
    ("ai_fin", "Debt-funded capex", "RED", "",
     "Big-4 Q3 capex ~$203bn; capex exceeded operating cash flow at Alphabet, Amazon and Meta. Hyperscaler bonds ~$296bn this year to 9 Nov, above the ~$250bn full-year forecast (incl. Microsoft $25bn on 29 Oct, Oracle $10bn notes at 7-8.65% on 2 Nov); Alphabet opened HKD and SGD deals on 11 Nov. CoreWeave debt $46.9bn at Q3 (from $35.1bn), 2026 capex $37-39bn; Nebius plans ~$40bn of 2027 capex, up to 85% from customer prepayments and ABS.",
     "Each step up in capex now needs external funding, at rising coupons; issuers are reaching for new markets and structures.",
     "Company Q3 results; TokenPost 9 Nov; Bloomberg via Yahoo 11 Nov; TechCrunch 12 Nov; Seoul Economic Daily 11 Nov", "12 Nov 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", True),
    # vol
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "330bp (11 Nov), from 334bp on 9 Nov and a 348bp peak on 5 Nov (the 52-week high); 260bp on 28 Aug. CCC 1,317bp on 6 Nov (no newer CCC print found). No 12 Nov print yet.",
     "Speed matters: a gap above ~400bp would confirm credit is following equities.",
     "FRED BAMLH0A0HYM2 via Equibles; BAMLH0A3HYC (ICE BofA)", "11 Nov 2026", "FRED: BAMLH0A0HYM2", True),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", False),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "French-German 10y 147bp on 12 Nov (OAT 4.76%, Bund 3.29%), from 142bp on 10 Nov; Oct range 127-175bp. EM mostly contained, but Argentina 939bp (6 Nov), +152bp in a week.",
     "Sovereign-yield shock is an IMF headline risk.",
     "ideal-investisseur.fr OAT-Bund tracker 12 Nov (aggregator); Rio Times 6 Nov", "12 Nov 2026", "-", True),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "~+22bp on 12 Nov (2y 4.88%, +14bp; 10y ~5.10%, +10bp, some sources 5.13%), from ~+25bp on 10 Nov. 10y auction (10 Nov) tailed 1bp, the most since Feb, foreign share 61% (lowest since Oct 2023); 30y (12 Nov) also tailed. FedWatch ~90% for a 25bp hike on 9 Dec, ~10% for 50bp; Daly: 'further tightening will be needed'. Fed at 3.75-4.00%.",
     "Bear flattening as the front end prices hikes. A hiking Fed into an AI-credit wobble is the combination to watch.",
     "TheStreet Pro 10 and 12 Nov; Yahoo Finance 12 Nov; TradingKey via Trading & Investment News 12 Nov (FedWatch)", "12 Nov 2026", "FRED: T10Y2Y", True),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "+67bp on 6 Nov (+69bp on 4 Nov, +74bp on 3 Nov), positive since the early-2026 inversion ended.", "Recessions tend to start after the re-steepening.",
     "FRED T10Y3M", "6 Nov 2026", "FRED: T10Y3M", False),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "Records in Oct-early Nov: Oracle 5y CDS ~295-300bp (19 Oct), ~288bp on 6 Nov; SoftBank ~424bp; CoreWeave above 1,000bp; Amazon, Alphabet, Meta, Nvidia at record wides (6 Nov). Easing since CoreWeave's results: Nvidia 5y CDS 139bp on 12 Nov (-2bp, even after its CEO quit); CoreWeave 9.75% 2031 notes 82.25c (12 Nov), its 2032 unsecured yield ~14% (11 Nov) from >16% on 6 Nov.",
     "Credit priced AI risk before equities did and is now calmer than equities, but levels are still near records and CoreWeave bonds trade well below par. Watch Oracle and CoreWeave CDS after Nvidia's Q3 (17 Nov).",
     "Bloomberg Tax 12 Nov (ICE data); Stocktwits/Yahoo 12 Nov (Bloomberg data); CNBC via PrimeXBT 19 Oct; CNBC 6 Nov; Reuters 9 Nov (BofA)", "12 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", True),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "12 Nov: Nvidia CEO Jensen Huang resigned with immediate effect; CFO Colette Kress is interim CEO (8-K). Nvidia -4.3% to $166.19 (-14% at the open), ~31% below its 6 Oct record; AMD +5.9%, Broadcom +5.5%. Nebius cut 2026 revenue guidance by $200m to $3bn on third-party site delays, part of its Microsoft contract slips to Q2 2027 (-17%); CoreWeave -7% after +25% on 11 Nov. CoreWeave Q3: revenue $3.66bn, backlog ~$132.5bn, net loss $709m.",
     "Demand still strong; the hits are funding cost, delivery delays and now leadership at the bellwether. A capex guidance cut would be the decisive trigger; next tests Nvidia Q3 on 17 Nov and Anthropic's IPO on 18-19 Nov.",
     "Nvidia 8-K 12 Nov (SEC); Yahoo Finance and TheStreet Pro closes 12 Nov; TechCrunch 12 Nov (Nebius); CoreWeave 8-K 10 Nov", "12 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure. Microsoft is winding down an AI capacity rental deal with Oracle and won't expand its Nscale Texas deal (Bloomberg, 6 Nov). Nebius site delays (12 Nov). ~$13.4bn of fixed-rate data-centre debt matures in 2027 and would reprice ~2.85pp higher (BNEF, approximate); TeraWulf and Crusoe builds delayed.",
     "Cracks spreading from one project to delays and non-renewals. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; Bloomberg via ZeroHedge 6 Nov; TechCrunch 12 Nov; BusinessDay 9 Nov citing BloombergNEF", "12 Nov 2026", "narrative: ai_obs", True),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "Week to 6 Nov: S&P 500 -2.7%, tech -8.2%. Whipsaw since: 9 Nov up, 10 Nov down, 11 Nov up (Nasdaq +1.6%, chips +5.7%), 12 Nov down (S&P -0.35% to 7,592, Nasdaq -0.39%, Russell 2000 -1.66%; 124 stocks up, 377 down; Nvidia -4.3%). USD/JPY ~160, raising intervention risk (Japan spent ¥15.4tn in Jul-Aug near 164). Near-record margin debt ($1.48tn, Sep).",
     "Unwind is part-way through, not finished. Watch spread to credit and the yen carry trade.",
     "Yahoo Finance and TheStreet Pro 12 Nov; Bloomberg headline 12 Nov (yen); FINRA", "12 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "12 Nov: stocks and bonds fell together again (S&P -0.35%, 2y +14bp, 10y +10-13bp), with the dollar up and gold -3%; the same happened on 10 Nov, so two of the last three bond sessions. Stocks still moving as one block on AI news; 9 of 11 sectors down on 12 Nov.",
     "Stocks and bonds falling together on several days running would flag broad deleveraging; two inflation-driven days are close to that. Move to RED if it persists into a third.",
     "Yahoo Finance 12 Nov; TheStreet Pro 12 Nov; JournalArta 10 Nov", "12 Nov 2026", "model: stock_bond", True),
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
     "Q3 standardized CET1: JPMorgan 13.9% (14.2% Q2), Citi 12.8% (flat), Bank of America 10.9% (11.2%), Wells Fargo 10.0% (10.3%, lower AOCI from higher rates). All 32 banks passed DFAST 2026 (trough 11.2% vs 4.5% min). IMF Oct stress test: core banks hold under AI + bond + energy shock.",
     "Comfortable, but three of four slipped as yields rose. Refresh with the FDIC aggregate (late Nov).",
     "Bank Q3 2026 results; Fed DFAST 2026; IMF GFSR Oct 2026", "Q3 2026", "manual_overlay: cet1_aggregate", True),
    ("bank_cap", "Liquidity (LCR / NSFR)", "GREEN", "GREEN",
     "Comfortably above requirements (carried).", "Deposit stability better than 2023.", "Bank 10-Qs (carried)", "Jun 2026", "-", False),
    # mm_spreads
    ("mm_spreads", "Cross-currency basis (EUR, JPY)", "GREEN", "GREEN",
     "Basis not refreshed (no public print). USD/JPY ~160 on 12 Nov, up from ~158 and close to the 163.9 high of 29 Jul; dollar index ~103, a 19-month high.",
     "Basis widening + yen squeeze = stress trigger. A sharp yen rebound (e.g. after intervention) is the squeeze to watch.",
     "BBG (carried); Reuters and Bloomberg headline via Trading & Investment News 12 Nov", "12 Nov 2026", "BBG: .JYCCBS3M G Index", True),
    # repo
    # cb_fac
    # mkt_liq
    ("mkt_liq", "Treasury market depth", "AMBER", "GREEN",
     "Depth itself not refreshed (Bloomberg). Demand softer: 10y auction (10 Nov, $42bn) tailed 1.0bp, the most since Feb, bid-to-cover 2.46, foreign share 61.2% from 80.3% (lowest since Oct 2023, largest drop since 2016); 30y (12 Nov) tailed 0.4bp, second tail in a row, bid-to-cover 2.36. 10y ~5.10%. No reported dysfunction.",
     "Moved to AMBER on weak foreign demand at auctions. Watch auction tails, dealer take-up and 10y above 5%.",
     "TheStreet Pro 10 and 12 Nov (citing Treasury); BBG (depth, carried)", "12 Nov 2026", "model: ust_liq", True),
    # ai_abs
    ("ai_abs", "Bank and insurer exposure", "AMBER", "",
     "ING auctioning ~$500m of 12 data-centre loans incl. a $25m Stargate New Mexico slice, bids due 19 Nov. HSBC SRT on >$1bn; Barclays seeking insurance on >$10bn; Deutsche ~$2bn SRT. Some insurers near capacity; broker Marsh (11 Nov) urged the Fed to ease up on banks that insure AI loans.",
     "Direct bank exposure to AI-adjacent industries is ~0.8% of assets (Chicago Fed): small, but rising and indirect via private credit. JPMorgan: $29bn of data-centre loans at end-Q3, 12% of its CRE book (8% three years ago).",
     "Bloomberg via Briefs 6 Nov; Bloomberg headline 11 Nov (Marsh); Reuters 9 Nov; Insurance Journal 30 Oct", "11 Nov 2026", "-", False),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Reuters (9 Nov): banks and investors wary of AI debt after the selloff. Deals still close, in safer form: CoreWeave preparing a ~$4bn investment-grade loan at ~7-7.5% and expects ~$9bn of customer prepayments; Nebius to fund up to 85% of ~$40bn 2027 capex with prepayments and ABS; Alphabet HKD/SGD bonds (11 Nov). No pulled or failed syndication found to 12 Nov.",
     "Wariness confirmed, but deals still close at a higher price and with more security. Move to RED on a pulled or failed syndication, or a weak ING auction (bids 19 Nov).",
     "Reuters 9 Nov; CoreWeave Q3 call via Yahoo 12 Nov; TechCrunch 12 Nov; Bloomberg via Yahoo 11 Nov", "12 Nov 2026", "-", True),
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
