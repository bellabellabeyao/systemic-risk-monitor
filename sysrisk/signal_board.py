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
AS_OF = "16 Nov 2026 (US close)"
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
     "Hedge-fund leverage highest since 2013 (Fed FSR); private-credit defaults at a record (Fitch 6.3%) and named by the Fed; Q3 tenders only ~40% met and non-traded BDC outflows $4.1bn; sub-scale BDCs consolidating; margin debt near record.", "AMBER"),
    ("valuation", "fragility", "broad", "Valuation stretch (credit pricing, equities, housing)",
     ["ebp_sentiment", "eq_val", "house_gap", "low_vol"],
     "Credit priced for perfection, equities near record valuations (CAPE ~40); the Fed calls house prices substantially above fundamentals; 30y mortgage 7.11%.", "RED"),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", [],
     "EM corporate spreads resilient; dollar at a 19-month high and Argentina's spread jumped, so weak sovereigns and energy importers are the soft spots.", "AMBER"),
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", [],
     "The Fed's stability report puts AI debt above $1.1tn and off-balance-sheet leases and commitments above $3tn, and flags circular financing; suppliers to buy $26bn of Anthropic's IPO (pricing 18 Nov); Nvidia backstops neocloud debt while leaderless.", ""),
    ("vol", "triggers", "broad", "Volatility shock (VIX, MOVE, FX vol)", ["vix", "move", "fx_vol"],
     "VIX ~19.3 on 13 Nov; no 16 Nov close found after the S&P fell 1.9%; put buying the heaviest of the year (Goldman, second-hand); MOVE peaked at 114 in Oct.", "GREEN"),
    ("spread_chg", "triggers", "broad", "Credit spread widening", ["credit_widen", "em_stress"],
     "HY 320bp on 12 Nov (348bp peak on 5 Nov, +60bp from Aug low), IG 89bp, CCC ~1,317bp on 6 Nov; easing for a fifth session and well below the ~400bp line that would confirm credit following equities. French-German 10y ~147bp.", "AMBER"),
    ("stress", "triggers", "broad", "Realised stress (stress indices, bank equity, credit-line draws, lending)",
     ["stlfsi", "nfci", "bank_rel_dd", "ci_draw", "pc_mark", "sloos_ci", "cre_delinq"],
     "Stress indices still below normal; companies drawing credit lines fast; private-credit marks lagging HY; Oct loan survey: tighter standards for small firms, CRE and loans to non-banks.", "GREEN"),
    ("curve", "triggers", "broad", "Term spreads / yield curve", [],
     "10y ~5.13-5.15% on 16 Nov, 2s10s ~+27bp (13 Nov); October PPI 6.5% y/y; a December hike priced and Fed speakers still hawkish; FOMC minutes 18 Nov.", "AMBER"),
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", [],
     "Still firing: Nvidia -4.1% on 16 Nov before its first results without its CEO, CoreWeave -6%; new US limits on remote chip access and midterm politics turn policy against the build-out; Microsoft is cutting neocloud vendors; AI junk spreads ~160bp over non-AI peers.", ""),
    ("crowded", "amplifiers", "broad", "Crowded trades and positioning", ["lf_ust_short"],
     "AI unwind spreading to the broad index: S&P -1.9% and Nasdaq -2.5% on 16 Nov, a third straight fall; heaviest put buying of 2026; bitcoin ~$65k; yen near 160, raising the risk of Japanese intervention.", "AMBER"),
    ("corr", "amplifiers", "broad", "Correlation and common drivers", ["absorption", "stock_bond", "dy_total", "granger_dgc"],
     "Financials driven by a few common factors; stocks and bonds fell together for three sessions, then on 16 Nov bonds edged up as stocks fell, so the joint-selloff signal has eased for now.", "GREEN"),
    ("sifi", "amplifiers", "broad", "Spillovers from large institutions", ["srisk_gdp", "dcovar_max", "dcovar_private", "dealer_lev"],
     "Capital shortfall in a crash still low; tail spillovers mid-range; FSB 2026 G-SIB list still not out (due in Nov).", "AMBER"),
    ("ai_amp", "amplifiers", "ai", "AI concentration and leverage on AI exposure", ["concentration"],
     "Top 10 stocks ~39% of the S&P 500; leverage sits on the same names.", ""),
    ("bank_cap", "threshold", "broad", "Bank capital and liquidity", [],
     "Large banks well capitalised and liquid (Fed FSR; Q3 CET1 10.0-13.9% at the big four), but unrealised securities losses grow with yields; IMF's weak-bank tail 22% of assets.", "GREEN"),
    ("mm_spreads", "threshold", "broad", "Short-term funding (CP, cross-currency basis)", ["cp_spread", "a2p2", "fin_cp"],
     "Bank and corporate short-term funding cheap; no dollar shortage, though the yen is at ~160 and the dollar at a 19-month high.", "GREEN"),
    ("repo", "threshold", "broad", "Repo, reserves and the reverse-repo cushion", ["reserves_gdp", "rrp_buffer", "sofr_iorb", "tgcr_iorb"],
     "Reverse-repo cushion gone; repo traded above the Fed floor around month-end, easing since (SOFR ~2bp below IORB on 9 Nov).", "AMBER"),
    ("cb_fac", "threshold", "broad", "Central bank backstops (repo facility, swap lines)", ["srf_usage", "swap_lines"],
     "Backstops ready and barely used.", "AMBER"),
    ("mkt_liq", "threshold", "broad", "Market liquidity and dollar funding", ["usd_6m"],
     "Dollar near a 19-month high; Treasury demand softer (weakest foreign share at a 10y auction since Oct 2023, two tails in a row) and front-end depth thinner per the Fed; 10y above 5%.", "GREEN"),
    ("ai_abs", "threshold", "ai", "Absorption of AI credit losses (banks, insurers, credit supply)", [],
     "The Fed counts close to $1tn of AI-linked exposure at the largest banks; banks sell down and insure data-centre loans (ING auction, bids 19 Nov); the unsecured AI high-yield window has shut, but secured and investment-grade deals still close.", ""),
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
     "Fitch US private-credit default rate a record 6.3% (trailing 12m, Q3; 6.0% Q2), 91 defaulters; Proskauer index 2.41% (from 2.51%). Fed FSR (13 Nov): private-credit loan default rate at the upper end of its short history, elevated PIK use signals repayment strain, perpetual BDCs still limit redemptions and net flows negative; hedge-fund leverage highest since 2013. Non-traded BDCs: Q3 redemptions exceeded new capital by $4.1bn (Stanger, preliminary). Q3 tenders: NAV BDCs asked $13.8bn (11.5% of NAV), ~40% met (BCRED 49.9% paid, Apollo ADS 33.9%, Blue Owl OTIC 12.8%); Goldman Sachs Private Credit Corp met all (~2% asked). GSBD Q3 non-accruals 4.2% at fair value (2.9% Q2). Consolidation: Investcorp Credit BDC to merge into BCIC at 90% of NAV; BCIC Q3 non-accruals 6.0% at cost, NAV/share -9.4%; Ares to buy Apollo's MidCap Financial (~$2.6bn EV).",
     "Gates hold, so stress shows in defaults, non-accruals, gates, PIK and consolidation of sub-scale BDCs. The Fed now names it in its stability report. Watch Q4 tender announcements.",
     "Fed Financial Stability Report 13 Nov 2026; Fitch via MonitorDaily 30 Oct; Proskauer 27 Oct; Stanger via AltsWire 12 Nov; GSBD Q3 results 6 Nov; SEC Schedule TO-I/A tracker; ICMB/BCIC release 11 Nov; Reuters via Fixed Income News Australia 16 Nov", "16 Nov 2026", "manual_overlay: bdc_nonaccrual", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct (monthly), 98.9th percentile since 1881; only 1999-2000 was higher. Daily estimate ~40.2 on 11 Nov (multpl, different method).",
     "Signals low 10-year returns; not a timing tool.",
     "Shiller data via thetrading.tools; multpl 11 Nov", "11 Nov 2026", "multpl / Shiller ie_data", False),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "Fed FSR (13 Nov, data to 28 Oct): house prices 'substantially above their historical relationship with fundamentals', price-to-rent stable at high levels, slight model-valuation declines in Sep. 30y mortgage 7.11% (12 Nov), a fourth weekly fall, from a 7.40% Oct peak; ~6.2% a year ago. Case-Shiller +2.1-2.7% y/y; real prices falling.",
     "Affordability worse than July. Next PMMS 19 Nov; daily rates rose after the hot CPI and PPI.",
     "Fed Financial Stability Report 13 Nov 2026; Freddie Mac PMMS 12 Nov; S&P Cotality Case-Shiller", "13 Nov 2026", "FRED: MORTGAGE30US", True),
    # em_imb
    ("em_imb", "EM external positions", "AMBER", "AMBER",
     "EMBI GD spread 187bp end-Q3 (no newer aggregate print); ICE BofA EM corporate spread 180bp (9 Nov). Weak spots widening: Argentina's EMBI spread 939bp on 6 Nov, from 787bp on 30 Oct. Dollar at a 19-month high (DXY ~103, 12 Nov).",
     "Risk is a dollar + US rates shock hitting energy importers; the dollar leg is now moving.",
     "SSGA Q3 2026; FRED BAMLEMCBPIOAS; Rio Times 6 Nov; Reuters via Trading & Investment News 12 Nov", "12 Nov 2026", "-", False),
    ("em_imb", "Reserve adequacy / external debt", "AMBER", "AMBER",
     "Uneven across EMs; weaker sovereigns face higher rollover costs (carried).", "Short-dated external debt is the weak spot.",
     "World Bank GEP (carried)", "Jun 2026", "-", False),
    # ai_fin
    ("ai_fin", "Off-balance-sheet obligations", "RED", "",
     "Fed FSR Box 2.2 (13 Nov): advanced-computing leases not yet commenced exceed $1tn, and other obligations (take-or-pay, residual value guarantees) exceed $2tn, both undiscounted; the Fed flags circular financing. Moody's: ~$970bn of hyperscaler lease commitments, ~$660bn not yet on balance sheet.",
     "Fixed commitments behave like debt in a downturn but are not counted as debt. The Fed's own tally is now above the earlier private estimates.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); Van Nieuwerburgh (2026) BPEA draft, citing Moody's", "13 Nov 2026", "narrative: ai_obs", True),
    ("ai_fin", "Circular and vendor financing", "RED", "",
     "Anthropic IPO: seven suppliers to buy $26bn of shares at the IPO price (Google ~$10bn, Nvidia $10bn, AMD ~$2.5bn), of up to $64.4bn raised; range $70-78, pricing Wed 18 Nov, trading Thu 19 Nov; books reported ~6x covered (CoinDesk, 13 Nov). Nvidia rents back unused neocloud GPUs and may backstop up to ~$125bn of a $500bn financing platform (Fortune). Nvidia's CEO resigned 12 Nov; its $10bn Anthropic pledge under scrutiny (Bloomberg); Nvidia has lost ~$735bn of market value since (AP, 16 Nov). Fed FSR (13 Nov) explicitly flags circular financing in the AI build-out.",
     "Supplier, investor and lender are the same party: one problem becomes two. RED while circularity grows and the main guarantor's standing is in question. Watch Nvidia Q3 (17 Nov) and Anthropic pricing (18 Nov).",
     "Dataconomy 12 Nov (Anthropic S-1/A); Fortune 12 Nov; Nvidia 8-K 12 Nov; CoinDesk via CappNotes 13 Nov; AP via BNN Bloomberg 16 Nov; Motley Fool 16 Nov; Fed FSR 13 Nov", "16 Nov 2026", "-", True),
    ("ai_fin", "Debt-funded capex", "RED", "",
     "Fed FSR (13 Nov): advanced-computing debt issuance above $680bn by Oct 2026, ~5x 2023's $130bn; ~31% of non-financial IG issuance (under 6% in 2023); public advanced-computing debt outstanding above $1.1tn. Big-4 Q3 capex ~$203bn; capex exceeded operating cash flow at Alphabet, Amazon and Meta. Hyperscaler bonds ~$296bn this year to 9 Nov; Barclays sees $300-320bn for 2026. CoreWeave debt $46.9bn at Q3 (from $35.1bn); Nebius plans ~$40bn of 2027 capex, up to 85% from prepayments and ABS.",
     "Each step up in capex now needs external funding, at rising coupons; the Fed says the build-out could soon surpass the 1990s telecom cycle.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); company Q3 results; TokenPost 9 Nov; Barclays via The Next Web 15 Nov; TechCrunch 12 Nov", "13 Nov 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", True),
    # vol
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "320bp (12 Nov), from 330bp on 11 Nov and a 348bp peak on 5 Nov (the 52-week high); 260bp on 28 Aug. IG OAS 89bp. CCC 1,317bp on 6 Nov (no newer CCC print found). HYG/JNK flat on 13 Nov.",
     "Speed matters: a gap above ~400bp would confirm credit is following equities.",
     "ICE BofA via CappNotes 13 Nov (FRED BAMLH0A0HYM2, 12 Nov print); BAMLH0A3HYC", "12 Nov 2026", "FRED: BAMLH0A0HYM2", False),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", False),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "French-German 10y 147bp on 12 Nov (OAT 4.76%, Bund 3.29%), from 142bp on 10 Nov; Oct range 127-175bp. EM mostly contained, but Argentina 939bp (6 Nov), +152bp in a week.",
     "Sovereign-yield shock is an IMF headline risk.",
     "ideal-investisseur.fr OAT-Bund tracker 12 Nov (aggregator); Rio Times 6 Nov", "12 Nov 2026", "-", False),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "~+27bp on 13 Nov (2y 4.88%, 10y 5.15%, 30y 5.47%). 16 Nov: 10y 5.13% (AP; another report has 5.15%), 2y not found. October PPI 6.5% y/y after CPI +0.4% m/m. December hike priced (Kalshi 91.5% on 13 Nov); Goldman says ~40bp of extra tightening through Q3 2027 was priced last week (second-hand); Schmid and Daly (16 Nov) say inflation needs more work. Fed at 3.75-4.00%.",
     "Bear flattening as the front end prices hikes. A hiking Fed into an AI-credit wobble is the combination to watch; FOMC minutes 18 Nov.",
     "CappNotes closing look 13 Nov; AP via BNN Bloomberg 16 Nov; Walk-Squawk morning wire 16 Nov (citing Goldman); 24/7 Wall St 16 Nov (citing CNBC)", "16 Nov 2026", "FRED: T10Y2Y", True),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "+67bp on 6 Nov (+69bp on 4 Nov, +74bp on 3 Nov), positive since the early-2026 inversion ended.", "Recessions tend to start after the re-steepening.",
     "FRED T10Y3M", "6 Nov 2026", "FRED: T10Y3M", False),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "Records in Oct-early Nov: Oracle 5y CDS ~288-300bp; SoftBank ~424bp; CoreWeave above 1,000bp; Amazon, Alphabet, Meta, Nvidia at record wides (6 Nov). Eased after CoreWeave's results: Nvidia 5y CDS 139bp on 12 Nov; CoreWeave 9.75% 2031 notes 82.25c (12 Nov). Goldman (via Walk-Squawk, 16 Nov, second-hand): AI-related junk spreads ~425bp vs ~265bp for comparable non-AI credits; HY issuance for new AI infrastructure quiet for about a month; CoreWeave reportedly won't borrow unsecured at current yields. No CDS print for 16 Nov found.",
     "AI credit trades ~160bp wider than non-AI peers and the unsecured market is effectively shut to the weakest names. Watch Oracle and CoreWeave CDS after Nvidia's Q3 (17 Nov).",
     "Bloomberg Tax 12 Nov (ICE data); Stocktwits/Yahoo 12 Nov; CNBC 6 Nov; Walk-Squawk morning wire 16 Nov (citing Goldman)", "16 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", True),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "16 Nov: Nvidia -4.1% to $156.14 (market cap ~$3.9tn) a day before Q3 results, its first without Jensen Huang; AMD -5.6%, Broadcom -3.9%, CoreWeave -6.1%, Intel -7.0%, Dell -7.0%, GE Vernova -4.9%. Policy: the administration issued new rules restricting remote access to advanced US chips and servers (AP); Democratic midterm gains raised worries about limits on new data-centre construction (AP); Fed Governor Bowman warned of a large correction if AI does not pan out (headline). 13 Nov: Bloomberg reported Microsoft is cutting neocloud vendors and not renewing an Oracle cloud deal (Microsoft was 36% of CoreWeave's Q2 revenue). Nebius cut 2026 revenue guidance by $200m on site delays.",
     "End demand still strong, but the largest buyer is consolidating vendors and policy has now turned against the build-out (chip access, data-centre politics). A hyperscaler capex guidance cut would be the decisive trigger (RED); next tests Nvidia Q3 on 17 Nov and Anthropic's IPO on 18-19 Nov.",
     "AP via BNN Bloomberg 16 Nov; Motley Fool 16 Nov (two reports); Motley Fool 13 Nov (citing Bloomberg); Nvidia 8-K 12 Nov; TechCrunch 12 Nov", "16 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure. Microsoft winding down an AI capacity deal with Oracle and won't expand its Nscale Texas deal (6 Nov); reportedly not renewing an Oracle cloud deal and using fewer neoclouds (13 Nov). Bloomberg (14 Nov): Applied Digital is asking tenants incl. Oracle and Meta, and Nvidia and AMD, for billions of dollars of guarantees to secure power before signing leases, and has capped leasing to junk-rated neoclouds such as CoreWeave (target ~70% investment-grade tenants). Nebius site delays (12 Nov). ~$13.4bn of fixed-rate data-centre debt matures in 2027 and would reprice ~2.85pp higher (BNEF, approximate).",
     "Developers now push risk back onto tenants and away from neoclouds. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; Bloomberg via ZeroHedge 6 Nov; Motley Fool 13 Nov (citing Bloomberg); The Next Web 15 Nov (citing Bloomberg 14 Nov); TechCrunch 12 Nov; BusinessDay 9 Nov citing BloombergNEF", "15 Nov 2026", "narrative: ai_obs", True),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "16 Nov: S&P 500 -1.9% to 7,416.59 (third straight loss), Nasdaq -2.5% to 24,509.76, Dow -1.4%; QQQ -2.7%; losses broadened beyond tech. Week to 13 Nov had been S&P +2.5% despite tech -2% on 13 Nov. Goldman (second-hand): VIX put buying over the past 10 sessions the heaviest of 2026; one-month realised S&P vol ~22. Bitcoin ~$65k, lowest since Aug. USD/JPY near 160, raising intervention risk (Japan spent ¥15.4tn in Jul-Aug near 164). Near-record margin debt ($1.48tn, Sep).",
     "Unwind resumed and is spreading from AI names to the broad index. Watch spread to credit and the yen carry trade.",
     "AP via BNN Bloomberg 16 Nov; Motley Fool 16 Nov; Walk-Squawk morning wire 16 Nov (citing Goldman); CappNotes 13 Nov; FINRA", "16 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "16 Nov: stocks fell broadly (S&P -1.9%, Dow -1.4%) while the 10y eased to 5.13% from 5.15% (AP; another report has 5.15%), so bonds edged up on an equity down day, ending the run of three sessions (10, 12, 13 Nov) in which stocks and bonds fell together. Gold -0.9%, Brent -3.5%.",
     "Back to AMBER on the stated rule (bonds rallied on an equity down day), but only just: a 2bp move, sources disagree, and hike pricing keeps the stock-bond link fragile. Return to RED if joint falls resume.",
     "AP via BNN Bloomberg 16 Nov; Motley Fool 16 Nov; CappNotes closing look 13 Nov", "16 Nov 2026", "model: stock_bond", True),
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
     "Fed FSR (13 Nov): bank CET1 ratios remain high; fair value of AFS and HTM securities ~$330bn below book in Q2, with further pressure since late Oct as yields rose. Q3 standardized CET1: JPMorgan 13.9% (14.2% Q2), Citi 12.8%, Bank of America 10.9% (11.2%), Wells Fargo 10.0% (10.3%). All 32 banks passed DFAST 2026 (trough 11.2% vs 4.5% min). IMF Oct stress test: core banks hold under an AI + bond + energy shock.",
     "Comfortable, but unrealised losses grow with the 10y above 5%. Refresh with the FDIC aggregate (late Nov).",
     "Fed Financial Stability Report 13 Nov 2026; bank Q3 2026 results; Fed DFAST 2026; IMF GFSR Oct 2026", "13 Nov 2026", "manual_overlay: cet1_aggregate", True),
    ("bank_cap", "Liquidity (LCR / NSFR)", "GREEN", "GREEN",
     "Fed FSR (13 Nov): most domestic banks hold high levels of liquid assets; uninsured deposits well below the 2022 peaks and fewer banks rely heavily on them; funding risks moderate.",
     "Deposit stability better than 2023.",
     "Fed Financial Stability Report 13 Nov 2026", "13 Nov 2026", "-", True),
    # mm_spreads
    ("mm_spreads", "Cross-currency basis (EUR, JPY)", "GREEN", "GREEN",
     "Basis not refreshed (no public print). USD/JPY ~160 on 12 Nov, up from ~158 and close to the 163.9 high of 29 Jul; dollar index ~103, a 19-month high.",
     "Basis widening + yen squeeze = stress trigger. A sharp yen rebound (e.g. after intervention) is the squeeze to watch.",
     "BBG (carried); Reuters and Bloomberg headline via Trading & Investment News 12 Nov", "12 Nov 2026", "BBG: .JYCCBS3M G Index", False),
    # repo
    # cb_fac
    # mkt_liq
    ("mkt_liq", "Treasury market depth", "AMBER", "GREEN",
     "Fed FSR (13 Nov, data to 28 Oct): Treasury price impact edged up; the 10y is close to its median since 2014, the 2y notably above it; equity market liquidity at the lower end of its range since 2019. Demand softer since: 10y auction (10 Nov) tailed 1.0bp, the most since Feb, foreign share 61.2% from 80.3% (lowest since Oct 2023); 30y (12 Nov) tailed 0.4bp, second tail in a row. 10y 5.13-5.15% on 16 Nov. No reported dysfunction.",
     "AMBER on weak foreign demand at auctions and thinner front-end depth. Watch auction tails, dealer take-up and 10y above 5%.",
     "Fed Financial Stability Report 13 Nov 2026; TheStreet Pro 10 and 12 Nov (citing Treasury); AP via BNN Bloomberg 16 Nov", "16 Nov 2026", "model: ust_liq", True),
    # ai_abs
    ("ai_abs", "Bank and insurer exposure", "AMBER", "",
     "Fed FSR (13 Nov): the largest US bank holding companies have close to $1tn of exposure to large tech firms, data-centre developers, advanced-computing SPEs, private-credit vehicles and utilities. ING auctioning ~$500m of 12 data-centre loans incl. a $25m Stargate New Mexico slice, bids due 19 Nov. HSBC SRT on >$1bn; Barclays seeking insurance on >$10bn; Deutsche ~$2bn SRT. Some insurers near capacity; Marsh (11 Nov) urged the Fed to ease up on banks that insure AI loans. JPMorgan: $29bn of data-centre loans at end-Q3.",
     "Direct AI-industry lending is ~0.8% of assets (Chicago Fed), but the Fed's broader count of AI-linked exposure is close to $1tn at the largest banks, much of it indirect via private credit and SPEs.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); Bloomberg via Briefs 6 Nov; Bloomberg headline 11 Nov (Marsh); Insurance Journal 30 Oct", "13 Nov 2026", "-", True),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Wary but open, in safer form. Goldman (second-hand, 16 Nov): HY issuance for new AI infrastructure quiet for about a month; CoreWeave reportedly won't borrow unsecured at current yields and is preparing a ~$4bn investment-grade secured loan at ~7-7.5%. Applied Digital caps junk-rated neocloud tenants and seeks power guarantees (Bloomberg, 14 Nov). Nebius to fund up to 85% of ~$40bn 2027 capex with prepayments and ABS. No pulled or failed syndication found to 16 Nov.",
     "The unsecured high-yield window for AI has shut; secured and investment-grade deals still close. Move to RED on a pulled or failed syndication, or a weak ING auction (bids 19 Nov).",
     "Walk-Squawk morning wire 16 Nov (citing Goldman); CoreWeave Q3 call via Yahoo 12 Nov; The Next Web 15 Nov (citing Bloomberg); Reuters 9 Nov; TechCrunch 12 Nov", "16 Nov 2026", "-", True),
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
