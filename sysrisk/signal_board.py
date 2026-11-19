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
AS_OF = "19 Nov 2026 (US close)"
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
     "Hedge-fund leverage highest since 2013 (Fed FSR); private-credit defaults near a record (Fitch 6.2% in Oct, from 6.3%) and named by the Fed; Q3 tenders only ~40% met and non-traded BDC outflows $4.1bn; sub-scale BDCs consolidating; margin debt near record.", "AMBER"),
    ("valuation", "fragility", "broad", "Valuation stretch (credit pricing, equities, housing)",
     ["ebp_sentiment", "eq_val", "house_gap", "low_vol"],
     "Credit priced for perfection, equities near record valuations (CAPE ~40); the Fed calls house prices substantially above fundamentals; 30y mortgage back up to 7.28% (first rise in five weeks) and homebuilder sentiment at its lowest since 2012.", "RED"),
    ("em_imb", "fragility", "broad", "EM imbalances and reserve adequacy", [],
     "EM corporate spreads resilient; dollar at a 19-month high and Argentina's spread jumped, so weak sovereigns and energy importers are the soft spots.", "AMBER"),
    ("ai_fin", "fragility", "ai", "AI financing structure (off-balance-sheet, circular, debt-funded capex)", [],
     "The Fed's stability report puts AI debt above $1.1tn and off-balance-sheet leases and commitments above $3tn, and flags circular financing; Nvidia's own cloud and lease commitments rose to $102bn and it is now 'rigorously evaluating' further guarantees; Anthropic priced its IPO above range at $83 (reported ~$1.5tn valuation), with suppliers buying ~$26bn, and opened at $111.50 on 19 Nov.", ""),
    ("vol", "triggers", "broad", "Volatility shock (VIX, MOVE, FX vol)", ["vix", "move", "fx_vol"],
     "VIX 28.4 on 19 Nov (+16%), a new high for this selloff, after 24.5 on 18 Nov and ~19.3 on 13 Nov; MOVE peaked at 114 in Oct (no newer print).", "GREEN"),
    ("spread_chg", "triggers", "broad", "Credit spread widening", ["credit_widen", "em_stress"],
     "HY 347bp on 18 Nov, +24bp since 13 Nov and level with the 348bp peak of 5 Nov (+87bp from the Aug low); credit is following the equity selloff, but still below the ~400bp line (19 Nov print not yet out). French-German 10y ~147bp.", "AMBER"),
    ("stress", "triggers", "broad", "Realised stress (stress indices, bank equity, credit-line draws, lending)",
     ["stlfsi", "nfci", "bank_rel_dd", "ci_draw", "pc_mark", "sloos_ci", "cre_delinq"],
     "Stress indices still below normal; companies drawing credit lines fast; private-credit marks lagging HY; Oct loan survey: tighter standards for small firms, CRE and loans to non-banks.", "GREEN"),
    ("curve", "triggers", "broad", "Term spreads / yield curve", [],
     "2s10s ~+27bp on 18 Nov (2y 4.80%); 10y ~5.05-5.07% on 19 Nov. October minutes: almost all officials expect further hikes; a 9 Dec hike ~91-92% priced.", "AMBER"),
    ("ai_trig", "triggers", "ai", "AI repricing triggers (AI credit, demand signals, project stress)", [],
     "Mixed: Nvidia beat (revenue $115.8bn, Q4 guide ~$130bn) so the demand trigger did not fire, but CoreWeave fell 4.1% on 18 Nov and ~6% on 19 Nov (~76% below its peak) as debt worries persisted; neocloud credit is at distress levels (CoreWeave CDS >1,100bp, 2031 notes ~15.7% yield) and ETFs on AI CDS have been filed; Anthropic's IPO held up (opened +34%).", ""),
    ("crowded", "amplifiers", "broad", "Crowded trades and positioning", ["lf_ust_short"],
     "Unwind re-accelerated and broadened: S&P -2.0% on 19 Nov, a sixth straight fall, Dow -1,101 points (-2.2%), Nasdaq -2.2%, Russell -2.2%, losses across nearly every sector; VIX 28.4; gold down with stocks; yen near 160, raising the risk of Japanese intervention.", "AMBER"),
    ("corr", "amplifiers", "broad", "Correlation and common drivers", ["absorption", "stock_bond", "dy_total", "granger_dgc"],
     "Financials driven by a few common factors; after three joint stock-bond falls, bonds rallied as stocks fell on 16-19 Nov (flight to safety), so the joint-selloff signal has eased, but moves are small and gold now falls with stocks.", "GREEN"),
    ("sifi", "amplifiers", "broad", "Spillovers from large institutions", ["srisk_gdp", "dcovar_max", "dcovar_private", "dealer_lev"],
     "Capital shortfall in a crash still low; tail spillovers mid-range; FSB 2026 G-SIB list still not out (due in Nov).", "AMBER"),
    ("ai_amp", "amplifiers", "ai", "AI concentration and leverage on AI exposure", ["concentration"],
     "Top 10 stocks ~39% of the S&P 500; leverage sits on the same names, and 2x leveraged Anthropic ETFs launched on its first trading day.", ""),
    ("bank_cap", "threshold", "broad", "Bank capital and liquidity", [],
     "Large banks well capitalised and liquid (Fed FSR; Q3 CET1 10.0-13.9% at the big four), but unrealised securities losses grow with yields; IMF's weak-bank tail 22% of assets.", "GREEN"),
    ("mm_spreads", "threshold", "broad", "Short-term funding (CP, cross-currency basis)", ["cp_spread", "a2p2", "fin_cp"],
     "Bank and corporate short-term funding cheap; no dollar shortage, though the yen is at ~160 and the dollar at a 19-month high.", "GREEN"),
    ("repo", "threshold", "broad", "Repo, reserves and the reverse-repo cushion", ["reserves_gdp", "rrp_buffer", "sofr_iorb", "tgcr_iorb"],
     "Reverse-repo cushion gone; repo traded above the Fed floor around month-end, easing since (SOFR ~2bp below IORB on 9 Nov).", "AMBER"),
    ("cb_fac", "threshold", "broad", "Central bank backstops (repo facility, swap lines)", ["srf_usage", "swap_lines"],
     "Backstops ready and barely used.", "AMBER"),
    ("mkt_liq", "threshold", "broad", "Market liquidity and dollar funding", ["usd_6m"],
     "Dollar near a 19-month high; Treasury demand softer (weakest foreign share at a 10y auction since Oct 2023, two tails in a row) and front-end depth thinner per the Fed; 10y ~5.05-5.07% on 19 Nov, still above 5%.", "GREEN"),
    ("ai_abs", "threshold", "ai", "Absorption of AI credit losses (banks, insurers, credit supply)", [],
     "The Fed counts close to $1tn of AI-linked exposure at the largest banks; banks sell down and insure data-centre loans (ING auction, bids 19 Nov, result not yet reported); the unsecured AI high-yield window has shut, but secured and investment-grade deals still close and Anthropic's upsized IPO traded well above its price on day one; Apollo warns neocloud funding depends on Nvidia support.", ""),
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
     "Fitch US private-credit default rate 6.2% (trailing 12m, Oct), down from the record 6.3% in Sep; 6 defaults in Oct vs 8 in Sep; firms with EBITDA under $25m 10.7%; Proskauer index 2.41% (from 2.51%). Fed FSR (13 Nov): private-credit loan default rate at the upper end of its short history, elevated PIK use signals repayment strain, perpetual BDCs still limit redemptions and net flows negative; hedge-fund leverage highest since 2013. Non-traded BDCs: Q3 redemptions exceeded new capital by $4.1bn (Stanger, preliminary). Q3 tenders: NAV BDCs asked $13.8bn (11.5% of NAV), ~40% met (BCRED 49.9% paid, Apollo ADS 33.9%, Blue Owl OTIC 12.8%); Goldman Sachs Private Credit Corp met all (~2% asked). GSBD Q3 non-accruals 4.2% at fair value (2.9% Q2). Consolidation: Investcorp Credit BDC to merge into BCIC at 90% of NAV; BCIC Q3 non-accruals 6.0% at cost, NAV/share -9.4%; Ares to buy Apollo's MidCap Financial (~$2.6bn EV).",
     "One month's easing does not change the picture: defaults stay near the record and small borrowers are worst. Gates hold, so stress shows in defaults, non-accruals, gates, PIK and consolidation of sub-scale BDCs. The Fed now names it in its stability report. Watch Q4 tender announcements.",
     "Fed Financial Stability Report 13 Nov 2026; Fitch via Investment Executive 17 Nov; Proskauer 27 Oct; Stanger via AltsWire 12 Nov; GSBD Q3 results 6 Nov; SEC Schedule TO-I/A tracker; ICMB/BCIC release 11 Nov; Reuters via Fixed Income News Australia 16 Nov", "17 Nov 2026", "manual_overlay: bdc_nonaccrual", True),
    # valuation
    ("valuation", "Equity CAPE (Shiller)", "RED", "RED",
     "40.7 in Oct (monthly), 98.9th percentile since 1881; only 1999-2000 was higher. Daily estimate ~40.2 on 11 Nov (multpl, different method).",
     "Signals low 10-year returns; not a timing tool.",
     "Shiller data via thetrading.tools; multpl 11 Nov", "11 Nov 2026", "multpl / Shiller ie_data", False),
    ("valuation", "Real estate price-to-income", "AMBER", "AMBER",
     "Fed FSR (13 Nov, data to 28 Oct): house prices 'substantially above their historical relationship with fundamentals', price-to-rent stable at high levels, slight model-valuation declines in Sep. 30y mortgage 7.28% (19 Nov), up from 7.11% and the first rise in five weeks (7.40% Oct peak); 6.26% a year ago; 15y 6.66%. Case-Shiller +2.1-2.7% y/y; real prices falling. NAHB homebuilder index 25 in Nov, the lowest since Apr 2012.",
     "Affordability worse than July and the four-week relief has reversed with hike pricing. Watch rates back above 7.40%.",
     "Fed Financial Stability Report 13 Nov 2026; Freddie Mac PMMS 19 Nov (GlobeNewswire); S&P Cotality Case-Shiller; NAHB via Yahoo Finance 17 Nov", "19 Nov 2026", "FRED: MORTGAGE30US", True),
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
     "Fed FSR Box 2.2 (13 Nov): advanced-computing leases not yet commenced exceed $1tn, and other obligations (take-or-pay, residual value guarantees) exceed $2tn, both undiscounted; the Fed flags circular financing. Moody's: ~$970bn of hyperscaler lease commitments, ~$660bn not yet on balance sheet. Nvidia (Q3 FY27, 17 Nov): cloud service agreements plus data-centre lease commitments $102bn, from $74bn a quarter earlier; its July filing showed $36bn of off-balance-sheet agreements and backstops for AI cloud providers (via CNBC).",
     "Fixed commitments behave like debt in a downturn but are not counted as debt. The Fed's own tally is now above the earlier private estimates.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); Van Nieuwerburgh (2026) BPEA draft, citing Moody's; Nvidia CFO remarks via Constellation Research 17 Nov; CNBC via Superpower Daily 17 Nov", "17 Nov 2026", "narrative: ai_obs", False),
    ("ai_fin", "Circular and vendor financing", "RED", "",
     "Anthropic IPO: seven suppliers to buy $26bn of shares at the IPO price (Google ~$10bn, Nvidia $10bn, AMD ~$2.5bn), of up to $64.4bn raised; range $70-78, pricing Wed 18 Nov, trading Thu 19 Nov; books reported ~6x covered (CoinDesk, 13 Nov). Nvidia rents back unused neocloud GPUs and may backstop up to ~$125bn of a $500bn financing platform (Fortune). Nvidia's CEO resigned 12 Nov; its $10bn Anthropic pledge under scrutiny (Bloomberg); Nvidia has lost ~$735bn of market value since (AP, 16 Nov). Fed FSR (13 Nov) explicitly flags circular financing in the AI build-out. 17 Nov: Nvidia's non-marketable equity stakes $65.5bn (from $22.3bn at the start of the fiscal year), marketable stakes $44.2bn (from $12.9bn); interim CEO Kress says Nvidia is 'rigorously evaluating future investments, commitments, and guarantees'; the board does not intend to reinstate Huang. Apollo's Rowan: many neoclouds could lose access to capital if Nvidia withdraws support. 18 Nov: Anthropic priced at $83 a share, above the $70-78 range, with the offering upsized; reported valuation ~$1.5tn; Nasdaq trading (ANT) from 19 Nov (Fortune, citing Bloomberg and WSJ); ~$81bn raised. 19 Nov: opened at $111.50 (+34%), traded as high as ~$115 and back to ~$100 by midday (Forbes live blog); Forbes headline reports a close at ~$97, up more than 17%. Nvidia filing (via newsletter): maximum gross guarantees $118bn, incl. up to $105bn for phased buildings supporting OpenAI leases; $32bn of neocloud commitments conditional; no payments made so far.",
     "Supplier, investor and lender are the same party: one problem becomes two. RED while circularity grows and the main guarantor now signals more caution on new guarantees. Strong IPO demand eases funding fears for now but deepens the supplier-investor loop. A first day well above the offer price, on a -2% market day, shows equity demand for the loop is intact; the guarantees are now quantified at up to $118bn. Watch whether Anthropic holds above $83 and whether Nvidia trims neocloud support.",
     "Dataconomy 12 Nov (Anthropic S-1/A); Fortune 12 and 18 Nov; Nvidia 8-K 12 Nov; AP via BNN Bloomberg 16 Nov; Fed FSR 13 Nov; Nvidia Q3 FY27 release 17 Nov; Constellation Research and CoinDesk 17 Nov; CNBC via Superpower Daily and The Wall Street Republic 17 Nov; Forbes live blog 19 Nov; The Morning Brief (Substack) 19 Nov", "19 Nov 2026", "-", True),
    ("ai_fin", "Debt-funded capex", "RED", "",
     "Fed FSR (13 Nov): advanced-computing debt issuance above $680bn by Oct 2026, ~5x 2023's $130bn; ~31% of non-financial IG issuance (under 6% in 2023); public advanced-computing debt outstanding above $1.1tn. Big-4 Q3 capex ~$203bn; capex exceeded operating cash flow at Alphabet, Amazon and Meta. Hyperscaler bonds ~$296bn this year to 9 Nov; Barclays sees $300-320bn for 2026. CoreWeave debt $46.9bn at Q3 (from $35.1bn); Nebius plans ~$40bn of 2027 capex, up to 85% from prepayments and ABS. Nvidia long-term debt $32.4bn at Q3 FY27, from $7.5bn.",
     "Each step up in capex now needs external funding, at rising coupons; the Fed says the build-out could soon surpass the 1990s telecom cycle.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); company Q3 results; TokenPost 9 Nov; Barclays via The Next Web 15 Nov; TechCrunch 12 Nov; Nvidia Q3 FY27 release 17 Nov", "17 Nov 2026", "BBG: CAPEX / CF_CASH_FROM_OPER", False),
    # vol
    # spread_chg
    ("spread_chg", "US HY OAS (change)", "AMBER", "GREEN",
     "347bp (18 Nov), from 343bp on 17 Nov and 323bp on 13 Nov, so +24bp over the selloff and level with the 348bp peak of 5 Nov (the 52-week high); 260bp on 28 Aug. 19 Nov print (Dow -2.2%) not yet published. IG OAS 89bp, BBB 111bp, CCC ~1,316bp (13 Nov, newsletter gauges, not refreshed).",
     "Credit is widening with equities, at a measured pace; a break above the 5 Nov high is likely with the 19 Nov selloff. A gap above ~400bp would make it RED.",
     "ICE BofA via FRED BAMLH0A0HYM2 (Equibles FRED mirror, 18 Nov print); Nexus Research credit update 16 Nov (IG, BBB, CCC)", "18 Nov 2026", "FRED: BAMLH0A0HYM2", True),
    ("spread_chg", "CDX IG / iTraxx Crossover", "GREEN", "GREEN",
     "CDX IG 61bp; iTraxx Crossover 308bp (27 Oct), +21bp m/m. Pre-selloff.", "Watch Crossover fallen-angel risk.",
     "irates.today 27 Oct", "27 Oct 2026", "CDX IG CDSI GEN 5Y Corp", False),
    ("spread_chg", "Sovereign spreads", "AMBER", "AMBER",
     "French-German 10y 147bp on 12 Nov (OAT 4.76%, Bund 3.29%), from 142bp on 10 Nov; Oct range 127-175bp. EM mostly contained, but Argentina 939bp (6 Nov), +152bp in a week.",
     "Sovereign-yield shock is an IMF headline risk.",
     "ideal-investisseur.fr OAT-Bund tracker 12 Nov (aggregator); Rio Times 6 Nov", "12 Nov 2026", "-", False),
    # curve
    ("curve", "2s10s spread", "AMBER", "AMBER",
     "~+27bp on 18 Nov (2y 4.80% unch., 10y 5.07%, 30y 5.41%; newsletter), from +30bp on 17 Nov. 19 Nov: 10y eased again to ~5.05-5.07% (sources differ) as stocks fell 2%; 2y not refreshed. FOMC minutes (Oct 27-28, released 18 Nov): almost all participants saw further hikes as likely appropriate; two dissents for a hike (Cook, Hammack). Kalshi 91% for +25bp on 9 Dec (8% for more); CME ~69% for 50bp of hikes by end-Jan; Waller reportedly floated 50bp in Dec. St. Louis Fed's Musalem (reported) wants more hikes by spring 2027. October PPI 6.5% y/y; retail sales +0.2% m/m, import prices +1.1%. Fed at 3.75-4.00%.",
     "Bear flattening as the front end prices hikes. A hiking Fed into an AI-credit wobble is the combination to watch; the minutes confirm the hiking bias.",
     "The Wall Street Republic 17 Nov (citing US Treasury par yield curve); Fed FOMC minutes 18 Nov; US Market Report (note.com) 19 Nov (citing Kalshi, CME FedWatch); Motley Fool via Yahoo Finance 19 Nov", "19 Nov 2026", "FRED: T10Y2Y", True),
    ("curve", "3m10y (NY Fed model)", "AMBER", "AMBER",
     "+67bp on 6 Nov (+69bp on 4 Nov, +74bp on 3 Nov), positive since the early-2026 inversion ended.", "Recessions tend to start after the re-steepening.",
     "FRED T10Y3M", "6 Nov 2026", "FRED: T10Y3M", False),
    # ai_trig
    ("ai_trig", "AI credit repricing (single-name CDS)", "RED", "",
     "CoreWeave 5y CDS ~1,135bp (10 Nov), ~1,114bp in a later CNBC-cited print; its 9.75% 2031 notes yield 15.66% (17 Nov), from 14.75% on 13 Nov. Oracle 5y CDS ~305bp; SoftBank 466bp (6 Nov); Nvidia 139bp (12 Nov). Meta Hyperion 6.581% 2049 notes 91.17 (13 Nov) from 93.04 on 9 Nov. Goldman (second-hand, 16 Nov): AI-related junk spreads ~425bp vs ~265bp for comparable non-AI credits. 17 Nov: Eisman calls the neoclouds 'all in big trouble'; Oracle equity -3.4%. 18 Nov: CoreWeave shares -4.1% to $47.83 and Nvidia -2.9% as the beat failed to ease debt worries; Tuttle and Defiance have filed for ETFs built on CoreWeave and Oracle CDS (filings, not launched). 19 Nov: CoreWeave shares -6.1% (MarketBeat), ~76% below their record high (Crypto Briefing headline).",
     "AI credit trades ~160bp wider than non-AI peers and the weakest names are priced as distressed (CDS >1,000bp). Nvidia's beat has not narrowed the stress; the equity keeps falling. No new CDS print found since 10 Nov; watch CoreWeave and Oracle CDS.",
     "Nexus Research credit update 16 Nov; CNBC via Superpower Daily 17 Nov; Bloomberg Tax 12 Nov (ICE data); Walk-Squawk morning wire 16 Nov (citing Goldman); The Wall Street Republic 17 Nov; Motley Fool 18 Nov; The Morning Brief (Substack) 19 Nov, citing CNBC; MarketBeat and Crypto Briefing 19 Nov", "19 Nov 2026", "BBG: ORCL / CRWV CDS 5Y", True),
    ("ai_trig", "Demand, earnings and policy signals", "AMBER", "",
     "Nvidia Q3 FY27 (17 Nov): revenue $115.8bn (+103% y/y) vs ~$109bn expected; data centre $107.6bn; Q4 guide ~$130bn (+/-3%) vs ~$125bn, assuming no China data-centre compute; CFO sees ~75% FY28 growth (single source); shares -0.4% in the session and ~+1.7% after hours (CoinDesk), then -2.9% to $150.96 on 18 Nov; interim CEO Kress said China Hopper shipments were halted and no China revenue is projected. Same day: software sold off (Salesforce -9.5%, IGV -3.3%); Nvidia cut its Intel stake 25%. Policy still a headwind: new limits on remote access to US chips and midterm worries over data-centre construction (AP, 16 Nov). Microsoft is cutting neocloud vendors (Bloomberg, 13 Nov); Nebius cut 2026 revenue guidance by $200m. 19 Nov: AMD -7.7% on a media report alleging ties to a blacklisted Chinese server maker; Motley Fool says Nvidia's results 'failed to reverse sentiment' as the selloff spread beyond tech; Anthropic's IPO opened +34%.",
     "End demand confirmed by Nvidia's beat and guide, so the biggest near-term trigger did not fire; AMBER, not GREEN, because the largest buyer is consolidating vendors, policy has turned against the build-out and software (the AI-loser trade) is breaking. A hyperscaler capex guidance cut would be RED. Anthropic's strong debut says investor demand for AI equity is intact even as chip and software stocks fall.",
     "Nvidia Q3 FY27 release 17 Nov; Constellation Research 17 Nov; CoinDesk 17 Nov; The Wall Street Republic 17 Nov; Vista Partners market close 18 Nov; AP via BNN Bloomberg 16 Nov; Motley Fool 13 Nov (citing Bloomberg); TechCrunch 12 Nov; Motley Fool via Yahoo Finance 19 Nov; Forbes 19 Nov", "19 Nov 2026", "-", True),
    ("ai_trig", "Project and software-credit stress", "AMBER", "",
     "Oracle Project Jupiter force majeure (24 Sep); ~$18bn of loans on an Oracle-leased New Mexico site under pressure. Microsoft winding down an AI capacity deal with Oracle and won't expand its Nscale Texas deal (6 Nov); reportedly not renewing an Oracle cloud deal and using fewer neoclouds (13 Nov). Bloomberg (14 Nov): Applied Digital is asking tenants incl. Oracle and Meta, and Nvidia and AMD, for billions of dollars of guarantees to secure power before signing leases, and has capped leasing to junk-rated neoclouds such as CoreWeave (target ~70% investment-grade tenants). Nebius site delays (12 Nov). ~$13.4bn of fixed-rate data-centre debt matures in 2027 and would reprice ~2.85pp higher (BNEF, approximate).",
     "Developers now push risk back onto tenants and away from neoclouds. Watch more force majeure, lease deferrals, loan prices below 90.",
     "ROIC.ai 24 Sep; Bloomberg via ZeroHedge 6 Nov; Motley Fool 13 Nov (citing Bloomberg); The Next Web 15 Nov (citing Bloomberg 14 Nov); TechCrunch 12 Nov; BusinessDay 9 Nov citing BloombergNEF", "15 Nov 2026", "narrative: ai_obs", False),
    # crowded
    ("crowded", "Crowded positioning", "RED", "AMBER",
     "19 Nov: S&P 500 -2.0% to ~7,176, a sixth straight loss; Dow -1,101 points (-2.19%) to 49,097, nearing correction; Nasdaq -2.2% to ~23,880; Russell 2000 -2.2%; selling across nearly every sector (industrials -2.6%); VIX 28.44 (+16%); gold ~-2-3%; bitcoin ~$62k. Cause cited: inflation, rates and valuations outweighing earnings, Fed signalling more hikes. 18 Nov: S&P 500 -0.2% to 7,323.63, a fifth straight loss; Dow -1.1%, Nasdaq +0.4% (chip rally), Russell 2000 +0.5%; VIX 24.49 (-3.8%); gold -3.4%, crude -3.3%; bitcoin ~$62.4k. 17 Nov: S&P 500 -1.0% to 7,340.53, the lowest close since 29 Jul; Dow -1.6%, Nasdaq -0.7%; software -3.3% (IGV). VIX 25.46 (+11%), Fear & Greed 25 (extreme fear). 16 Nov: S&P -1.9%, Nasdaq -2.5%. Goldman (second-hand, 16 Nov): VIX put buying the heaviest of 2026. USD/JPY near 160 (159.73 on 12 Nov), raising intervention risk (Japan and the US intervened near 163 in late Jul-early Aug). Near-record margin debt ($1.48tn, Sep).",
     "Unwind in its sixth session and re-accelerating after a one-day pause; now broad, not just tech. Bonds still rallied slightly, so de-risking rather than forced liquidation so far. Watch spread to credit, margin calls and the yen carry trade.",
     "Motley Fool via Yahoo Finance 19 Nov; Vista Partners market close 18 Nov; The Wall Street Republic 17 Nov; Yahoo Finance live 17 Nov; AP via BNN Bloomberg 16 Nov; Walk-Squawk morning wire 16 Nov (citing Goldman); Lead-Lag Report 13 Nov; AP via ABC7 Aug 2026; FINRA", "19 Nov 2026", "-", True),
    # corr
    ("corr", "Cross-asset correlation", "AMBER", "GREEN",
     "19 Nov: S&P -2.0% while the 10y eased ~1-3bp to ~5.05-5.07% (sources differ), a fourth session of bonds rallying on an equity down day; gold fell ~2-3% with stocks. 18 Nov: S&P -0.2% while the 10y fell ~4bp to 5.07%, a third session of bonds rallying on an equity down day; gold fell 3.4% with stocks. 17 Nov: S&P -1.0% while the 10y fell 2bp to 5.10% and the 2y 3bp to 4.80% (flight to safety); 16 Nov: S&P -1.9% with the 10y down ~2bp. These end the run of three joint falls (10, 12, 13 Nov).",
     "AMBER on the stated rule: the stock-bond hedge is working, but the bond rally is small against a 2% equity fall, gold no longer hedges, and hike pricing (~91% for 9 Dec) keeps the link fragile. Return to RED if joint falls resume.",
     "Motley Fool via Yahoo Finance 19 Nov; Vista Partners market close 18 Nov; The Wall Street Republic 17 Nov (citing US Treasury, Newsquawk); Yahoo Finance live 17 Nov; AP via BNN Bloomberg 16 Nov", "19 Nov 2026", "model: stock_bond", True),
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
     "Leveraged ETFs more than doubled in assets over the past year; margin debt $1.48tn (Sep); retail sold a net $358m of single stocks on 5 Nov. 19 Nov: Defiance 2x daily Anthropic ETFs listed for its first trading day (press-release headline).",
     "Forced selling would hit the same names first; leverage is being added to the newest AI name on day one.", "TheStreet Sep 2026; Pomegra 5 Nov; FINRA; GlobeNewswire headline 19 Nov (Defiance)", "19 Nov 2026", "-", True),
    # bank_cap
    ("bank_cap", "CET1 and stress test", "GREEN", "GREEN",
     "Fed FSR (13 Nov): bank CET1 ratios remain high; fair value of AFS and HTM securities ~$330bn below book in Q2, with further pressure since late Oct as yields rose. Q3 standardized CET1: JPMorgan 13.9% (14.2% Q2), Citi 12.8%, Bank of America 10.9% (11.2%), Wells Fargo 10.0% (10.3%). All 32 banks passed DFAST 2026 (trough 11.2% vs 4.5% min). IMF Oct stress test: core banks hold under an AI + bond + energy shock.",
     "Comfortable, but unrealised losses grow with the 10y above 5%. Refresh with the FDIC aggregate (late Nov).",
     "Fed Financial Stability Report 13 Nov 2026; bank Q3 2026 results; Fed DFAST 2026; IMF GFSR Oct 2026", "13 Nov 2026", "manual_overlay: cet1_aggregate", False),
    ("bank_cap", "Liquidity (LCR / NSFR)", "GREEN", "GREEN",
     "Fed FSR (13 Nov): most domestic banks hold high levels of liquid assets; uninsured deposits well below the 2022 peaks and fewer banks rely heavily on them; funding risks moderate.",
     "Deposit stability better than 2023.",
     "Fed Financial Stability Report 13 Nov 2026", "13 Nov 2026", "-", False),
    # mm_spreads
    ("mm_spreads", "Cross-currency basis (EUR, JPY)", "GREEN", "GREEN",
     "Basis not refreshed (no public print). USD/JPY 159.31 on 18 Nov (159.94 on 12 Nov), close to 160 where Japan's Mimura warned moves are 'excessively rapid'; 163.9 high of 29 Jul; dollar index 103.80 on 18 Nov, a year-to-date high intraday.",
     "Basis widening + yen squeeze = stress trigger. A sharp yen rebound (e.g. after intervention) is the squeeze to watch.",
     "BBG (carried); Reuters via NST 12 Nov; US Market Report (note.com) 19 Nov", "18 Nov 2026", "BBG: .JYCCBS3M G Index", True),
    # repo
    # cb_fac
    # mkt_liq
    ("mkt_liq", "Treasury market depth", "AMBER", "GREEN",
     "Fed FSR (13 Nov, data to 28 Oct): Treasury price impact edged up; the 10y is close to its median since 2014, the 2y notably above it; equity market liquidity at the lower end of its range since 2019. Demand softer since: 10y auction (10 Nov) tailed 1.0bp, the most since Feb, foreign share 61.2% from 80.3% (lowest since Oct 2023); 30y (12 Nov) tailed 0.4bp, second tail in a row. 10y 5.10% on 17 Nov, easing on safe-haven demand. No reported dysfunction.",
     "AMBER on weak foreign demand at auctions and thinner front-end depth. Watch auction tails, dealer take-up and 10y above 5%.",
     "Fed Financial Stability Report 13 Nov 2026; TheStreet Pro 10 and 12 Nov (citing Treasury); The Wall Street Republic 17 Nov", "17 Nov 2026", "model: ust_liq", False),
    # ai_abs
    ("ai_abs", "Bank and insurer exposure", "AMBER", "",
     "Fed FSR (13 Nov): the largest US bank holding companies have close to $1tn of exposure to large tech firms, data-centre developers, advanced-computing SPEs, private-credit vehicles and utilities. ING auctioning ~$500m of 12 data-centre loans incl. a $25m Stargate New Mexico slice, bids due 19 Nov. HSBC SRT on >$1bn; Barclays seeking insurance on >$10bn; Deutsche ~$2bn SRT. Some insurers near capacity; Marsh (11 Nov) urged the Fed to ease up on banks that insure AI loans. JPMorgan: $29bn of data-centre loans at end-Q3.",
     "Direct AI-industry lending is ~0.8% of assets (Chicago Fed), but the Fed's broader count of AI-linked exposure is close to $1tn at the largest banks, much of it indirect via private credit and SPEs.",
     "Fed Financial Stability Report 13 Nov 2026 (Box 2.2); Bloomberg via Briefs 6 Nov; Bloomberg headline 11 Nov (Marsh); Insurance Journal 30 Oct", "13 Nov 2026", "-", False),
    ("ai_abs", "Credit supply to the AI build-out", "AMBER", "",
     "Wary but open, in safer form. Goldman (second-hand, 16 Nov): HY issuance for new AI infrastructure quiet for about a month; CoreWeave reportedly won't borrow unsecured at current yields and is preparing a ~$4bn investment-grade secured loan at ~7-7.5%. Applied Digital caps junk-rated neocloud tenants and seeks power guarantees (Bloomberg, 14 Nov). Nebius to fund up to 85% of ~$40bn 2027 capex with prepayments and ABS. Apollo's Rowan (CNBC, 17 Nov): many neoclouds could lose access to capital if Nvidia pulls its financing support; expects captive-finance-style lenders to emerge. Nvidia says it is 'rigorously evaluating' further commitments and guarantees. No pulled or failed syndication found to 19 Nov. 19 Nov: Anthropic's ~$81bn IPO opened 34% above its price; no result yet reported for ING's ~$500m data-centre loan auction (bids due 19 Nov).",
     "The unsecured high-yield window for AI has shut; secured and investment-grade deals still close. Equity markets still fund the top names. Move to RED on a pulled or failed syndication, or a weak ING auction result.",
     "Walk-Squawk morning wire 16 Nov (citing Goldman); CoreWeave Q3 call via Yahoo 12 Nov; The Next Web 15 Nov (citing Bloomberg); CNBC via Superpower Daily 17 Nov; Constellation Research 17 Nov; Forbes 19 Nov; Pebblous 11 Nov (ING auction terms)", "19 Nov 2026", "-", True),
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
