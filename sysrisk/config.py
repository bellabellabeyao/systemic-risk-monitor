"""
Indicator registry and universe definitions.

Design principle
----------------
Systemic risk = Vulnerability (slow build-up + structural amplifiers) x Stress (realised shock).
Volatility, valuation and spread signals are included alongside the structural measures; where one would
double count another (VIX inside the St. Louis Fed index) it is shown but not scored.

  A  BUILD-UP      quantity-based, leading (credit gap, R-zone, NBFI leverage, credit sentiment)
  B  AMPLIFIERS    how a loss propagates (SRISK, dCoVaR, connectedness, absorption, Granger network)
  C  PLUMBING      funding / money-market stress (SOFR-IORB, reserves, RRP buffer, SRF, CP)
  D  OUTCOME       realised financial stress and its macro tail (STLFSI, NFCI, Growth-at-Risk)

owner:
  "systemic"    scored here
  "market_top"  owned by the market-top monitor; used here only as a model input / context
  "manual"      low-frequency supervisory data (CET1, DFAST, G-SIB score, OFR hedge-fund leverage);
                entered by hand in manual_overlay.csv, shown but not auto-scored
"""
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------- equity universe
# Sector baskets used for SRISK / MES / dCoVaR / Granger network. Yahoo tickers.
# Bloomberg equivalents: append " US Equity" (handled in data.BloombergProvider).
FIN_UNIVERSE = {
    "US G-SIB banks":   ["JPM", "BAC", "C", "WFC", "GS", "MS", "BNY", "STT"],
    "US regional banks": ["USB", "PNC", "TFC", "FITB", "KEY", "RF", "CFG", "MTB"],
    "Insurers":         ["MET", "PRU", "AIG", "LNC", "CRBG", "EQH"],
    "Alt managers":     ["BX", "KKR", "APO", "ARES", "OWL", "BN"],      # private-credit nexus
    "BDCs":             ["ARCC", "BXSL", "OBDC", "FSK", "MAIN", "HTGC"],  # direct-lending proxy
    "Brokers/exch":     ["SCHW", "IBKR", "HOOD", "ICE", "CME"],
}
MARKET_PROXY = "^GSPC"          # SRISK/MES market; swap for ACWI for a global system
SYSTEM_PROXY = "XLF"            # financial-system return for CoVaR

# Cross-asset panel for Diebold-Yilmaz (range-based vol needs High/Low -> ETFs)
DY_PANEL = {
    "US equity": "SPY", "Banks": "KBE", "Regionals": "KRE", "Alt mgrs": "PSP",
    "BDCs": "BIZD", "HY credit": "HYG", "IG credit": "LQD", "Treasuries": "IEF",
    "EM equity": "EEM", "USD": "UUP", "Oil": "USO", "Gold": "GLD",
}

# State variables used to condition dCoVaR
STATE_VARS = {
    "VIX": ("yahoo", "^VIX"),
    "Term spread": ("fred", "T10Y3M"),
    "Baa-10y spread": ("fred", "BAA10Y"),
    "3m T-bill chg": ("fred", "DTB3"),
}


@dataclass
class Indicator:
    id: str
    name: str
    pillar: str                       # A/B/C/D or "context"
    source: str                       # fred | yahoo | model | bbg | manual
    series: Optional[str]             # FRED id / ticker / model key
    direction: int = 1                # +1 higher = riskier, -1 lower = riskier
    owner: str = "systemic"
    abs_thresholds: Optional[tuple] = None   # (amber, red) absolute override, else percentile 60/80
    bbg: Optional[str] = None         # Bloomberg override ticker|field
    lag_days: int = 0                 # publication lag applied before scoring (no look-ahead)
    why: str = ""
    transmits: str = ""
    src: str = ""                     # literature + data source, shown on the dashboard
    scored: bool = True               # False = shown in its link but kept out of the index
    not_scored_why: str = ""
    ns_tag: str = ""                  # short reason shown on the row: double counts / trends up / lagging / global / unproven / structural break


REGISTRY = [
    # ======== A. FUEL - is there an excess that could unwind? (slow, leading)
    Indicator("ebp_sentiment", "Credit risk pricing", "A", "model", "BAA10Y", direction=-1,
              why="When investors accept very little extra yield for credit risk, issuance gets loose and the "
                  "repricing later is sharp. Tight spreads today predict wider spreads and weaker growth about two "
                  "years out (Lopez-Salido, Stein & Zakrajsek 2017).",
              transmits="Underpriced credit -> weak deals get funded -> defaults and mark-downs when growth slows."),
    Indicator("nbfi_leverage", "Leverage outside banks", "A", "fred", "NFCILEVERAGE",
              why="Leverage in funds, dealers and households that bank capital rules do not cap. Measured by the "
                  "Chicago Fed's leverage sub-index; above zero means more leverage than average.",
              transmits="Leveraged holders face margin calls in a sell-off and become forced sellers."),
    Indicator("credit_gap", "Credit boom gauge (credit-to-GDP gap)", "A", "model", "QUSPAM770A",
              abs_thresholds=(2.0, 10.0), lag_days=120,
              why="How far private credit/GDP sits above its long-run trend. The best single early-warning "
                  "indicator of banking crises; Basel's countercyclical buffer switches on at +2pp.",
              transmits="Credit booms finance marginal borrowers whose losses land on lenders' balance sheets."),
    Indicator("rzone", "Boom in both credit and asset prices", "A", "model", "rzone",
              abs_thresholds=(0.6, 0.8), lag_days=120,
              why="Crises are most likely when fast credit growth and fast asset-price growth happen together; "
                  "then the 3-year crisis probability is about 40% (Greenwood et al. 2022). 1.0 = both at record pace.",
              transmits="Credit-financed asset buyers are hit twice when prices turn."),
    Indicator("corp_debt", "Corporate debt / GDP", "A", "model", "BCNSDODNS", lag_days=120,
              why="Corporate leverage is where AI capex and private credit financing show up first.",
              transmits="A refinancing wall turns into defaults, which land on banks, BDCs and insurers."),
    Indicator("low_vol", "Volatility too low for too long", "A", "model", "lowvol",
              why="Long spells of unusually low volatility encourage risk-taking and leverage that later unwinds; "
                  "volatility below its trend is one of the better crisis predictors in 200 years of data "
                  "(Danielsson, Valenzuela & Zer 2018). The market-top monitor reads VIX as a price; here it is "
                  "read as a build-up signal.",
              transmits="Low measured risk -> VaR-based limits allow more leverage -> forced deleveraging when vol returns."),
    Indicator("hh_dsr", "Household debt service burden", "A", "fred", "TDSP", lag_days=90,
              why="Share of income households spend servicing debt. Debt service ratios predict crises over a "
                  "1-2 year horizon better than credit gaps (Drehmann & Juselius 2014).",
              transmits="High debt service -> spending cuts and defaults when rates or incomes move."),
    Indicator("house_gap", "House prices vs trend", "A", "model", "QUSR628BIS", lag_days=90,
              why="Real house prices above their long-run trend. Credit-fuelled property booms end in the costliest "
                  "crises (Borio & Lowe 2002; Jordà, Schularick & Taylor 2015).",
              transmits="Falling collateral values -> mortgage and CRE losses -> bank capital."),
    Indicator("eq_val", "Equity market value / GDP", "A", "model", "eq_val", lag_days=75,
              why="Equity valuation stretch. Equity bubbles without leverage tend to end in recessions rather than "
                  "banking crises (Jordà, Schularick & Taylor 2015), so it is context for the size of a wealth shock.",
              transmits="Wealth effect on spending; margin and collateral calls on leveraged holders."),
    Indicator("margin", "Margin credit / equity market value", "A", "model", "margin", lag_days=75,
              why="Borrowing against securities at broker-dealers relative to the size of the equity market.",
              transmits="Price falls trigger margin calls -> forced selling into a falling market."),
    Indicator("hh_debt", "Household debt / GDP", "A", "fred", "HDTGPDUSQ163N", lag_days=120,
              why="The 2008 fuel. Low and falling household leverage means mortgages are unlikely to start the fire.",
              transmits="Mortgage and consumer losses hit banks and securitised credit."),

    # ======== B. FAULT LINES - if a loss happens, does it spread? (market-implied)
    Indicator("srisk_gdp", "Capital shortfall in a crash (SRISK)", "B", "model", "srisk",
              why="How much capital US financials would need to raise after a 40% equity crash, as % of GDP "
                  "(Brownlees & Engle). The government ends up owning this number in a crisis.",
              transmits="Undercapitalised lenders cut credit or need bailouts."),
    Indicator("dcovar_max", "Worst single-sector spillover (dCoVaR)", "B", "model", "dcovar",
              why="Extra loss in the financial system's worst 5% of weeks when the most dangerous sector is in "
                  "distress (Adrian & Brunnermeier).",
              transmits="One sector's distress drags the rest of the system's tail."),
    Indicator("dcovar_private", "Private-credit spillover (alt managers + BDCs)", "B", "model", "dcovar_pc",
              why="The listed window into private credit, which is invisible to bank-based measures like SRISK.",
              transmits="Private-credit losses -> bank fund-finance lines and insurers' private assets."),
    Indicator("dealer_lev", "Broker-dealer leverage", "B", "model", "dealer_lev", lag_days=75,
              why="Dealers' assets per dollar of equity. Dealer leverage is procyclical and drives risk premia and "
                  "market liquidity (Adrian & Shin 2010; Adrian, Etula & Muir 2014); dealers are the market makers "
                  "everyone else relies on in a sell-off.",
              transmits="Levered dealers shrink balance sheets in stress -> market liquidity evaporates."),
    Indicator("stock_bond", "Stocks and bonds falling together", "B", "model", "sb_corr",
              why="3-month correlation of S&P 500 and Treasury returns. When it turns positive, the hedge that most "
                  "balanced and risk-parity portfolios rely on stops working (Campbell, Pflueger & Viceira 2020).",
              transmits="Diversified portfolios lose on both legs -> deleveraging across asset classes."),
    Indicator("fire_sale", "Fire-sale exposure (common asset holdings)", "B", "bbg", None, bbg="needs holdings data",
              why="Losses from forced sales of assets that many institutions hold; empirically the largest "
                  "amplification channel (Greenwood, Landier & Thesmar 2015; Duarte & Eisenbach 2021). Needs "
                  "regulatory or 13F holdings data; not in the free feed.",
              transmits="One seller's price impact marks down everyone holding the same asset."),
    Indicator("absorption", "Markets moving as one (absorption ratio)", "B", "model", "ar",
              why="Share of financial-stock risk explained by a handful of common drivers. High = everything is "
                  "the same trade, so diversification fails when it is needed (Kritzman et al.).",
              transmits="A shock anywhere hits every holder at once."),
    Indicator("dy_total", "Cross-asset spillover (Diebold-Yilmaz)", "B", "model", "dy",
              why="Share of each asset's volatility that comes from shocks to other assets.",
              transmits="High spillover = a shock in one market travels to all of them."),
    Indicator("granger_dgc", "Lead-lag links between financial sectors", "B", "model", "dgc",
              why="Share of sector pairs where one sector's returns predict another's (Billio et al.); "
                  "rises before crises as banks, insurers and funds become entangled.",
              transmits="Denser links = more channels for distress to travel."),

    # ======== C. SHOCK ABSORBERS - can the system absorb it? (funding liquidity)
    Indicator("rrp_buffer", "Spare cash at the Fed (ON RRP)", "C", "fred", "RRPONTSYD", direction=-1,
              why="Money funds' idle cash parked at the Fed. It cushions repo markets: when it is near zero, "
                  "every further drain hits bank reserves directly.",
              transmits="No cushion -> quarter-end repo spikes -> dealers pull back from Treasury and basis trades."),
    Indicator("reserves_gdp", "Bank reserves", "C", "fred", "WRESBAL", direction=-1,
              why="Banks' liquidity at the Fed. Below roughly $2.8-3tn the 2019 repo squeeze showed reserves stop "
                  "being 'ample'.",
              transmits="Scarce reserves -> banks hoard liquidity -> funding rates jump."),
    Indicator("sofr_iorb", "Repo rate vs Fed floor (SOFR - IORB)", "C", "model", "sofr_iorb",
              abs_thresholds=(0.0, 10.0),
              why="Overnight repo trading above the rate the Fed pays on reserves means cash is getting scarce. "
                  "This is the earliest sign the plumbing is tightening.",
              transmits="Higher funding costs force leveraged Treasury and basis trades to shrink."),
    Indicator("srf_usage", "Emergency repo use (Standing Repo Facility)", "C", "fred", "RPONTSYD",
              abs_thresholds=(1.0, 25.0),
              why="Banks borrowing from the Fed's backstop repo window. Sustained use means private repo is not clearing.",
              transmits="Funding stress at dealers spreads to every leveraged holder that relies on them."),
    Indicator("cp_spread", "Bank short-term funding premium (CP - T-bill)", "C", "model", "cp_spread",
              why="What financial firms pay over Treasury bills to borrow for 3 months. It replaces the "
                  "discontinued TED spread.",
              transmits="Wholesale funding runs: the 2007-08 channel."),
    Indicator("usd_6m", "Dollar strength (global dollar funding)", "C", "model", "usd6m",
              why="A stronger dollar tightens funding for every non-US borrower and bank with dollar debt; the dollar "
                  "is the single best gauge of global financial conditions (Bruno & Shin 2015; Avdjiev, Du, Koch & Shin 2019).",
              transmits="Dollar up -> foreign borrowers' balance sheets weaken -> global banks cut dollar lending."),
    Indicator("fiscal", "Fiscal room for a backstop (federal debt / GDP)", "C", "fred", "GFDEGDQ188S", lag_days=90,
              why="Post-crisis recoveries are deeper when governments have fiscal room to respond (Romer & Romer 2018; "
                  "Jordà, Schularick & Taylor 2016).",
              transmits="Less fiscal space -> weaker backstop -> sovereign and bank risk feed each other."),
    Indicator("bank_capital", "Bank capital ratios (CET1)", "C", "manual", None, bbg="manual: Fed / FDIC",
              why="Better-capitalised banking systems recover faster from crises, though capital does not predict "
                  "them (Jordà, Richter, Schularick & Taylor 2021). FRED's bank equity series ended in 2020."),
    Indicator("xccy_basis", "Offshore dollar funding (xccy basis)", "C", "bbg", None, direction=-1,
              bbg="Bloomberg only",
              why="Premium non-US banks pay to borrow dollars.", transmits="Global dollar squeeze."),

    # ======== D. IGNITION - is the system being tested right now? (realised stress)
    Indicator("stlfsi", "Financial stress index (St. Louis Fed)", "D", "fred", "STLFSI4",
              abs_thresholds=(0.0, 1.5),
              why="18 market series combined; zero is normal, above zero is stress.", transmits="--"),
    Indicator("nfci", "Financial conditions (Chicago Fed NFCI)", "D", "fred", "NFCI", abs_thresholds=(0.0, 0.5),
              why="105 series on risk, credit and leverage; negative means looser than average.", transmits="--"),
    Indicator("bank_rel_dd", "Regional banks vs the market", "D", "model", "kre_rel",
              why="How far regional bank stocks have lagged the S&P 500 from their 1-year high. It caught the "
                  "2023 deposit run first.", transmits="Deposit flight -> forced asset sales -> credit tightening."),

    Indicator("sloos_ci", "Banks tightening lending standards (SLOOS)", "D", "fred", "DRTSCILM", lag_days=30,
              why="Net share of US banks tightening C&I loan standards. Credit-supply tightening predicts slower "
                  "lending and output (Lown & Morgan 2006; Bassett, Chosak, Driscoll & Zakrajsek 2014).",
              transmits="Tighter standards -> refinancing gets harder -> defaults rise among weaker borrowers."),
    Indicator("cre_delinq", "Commercial real estate loan delinquencies", "D", "fred", "DRCRELEXFACBS", lag_days=75,
              why="Realised losses in the loan book most concentrated at regional banks.",
              transmits="CRE losses -> regional bank capital -> deposit confidence."),
    Indicator("pc_mark", "Market's mark on private credit (BDCs vs HY bonds)", "D", "model", "pc_mark",
              why="How far listed BDCs (direct lenders) have fallen behind high-yield bonds from their 1-year high. "
                  "Listed prices reprice daily while private loan marks lag; a widening gap signals the market doubts "
                  "reported marks. Practitioner proxy, not a published measure.",
              transmits="Private credit stress -> fund-finance lines at banks, insurers' private assets, redemptions."),
    Indicator("credit_widen", "Credit spreads widening (13-week change)", "D", "model", "credit_widen",
              why="A sudden widening of corporate spreads is the market pricing in losses; credit-spread shocks lead "
                  "declines in activity (Gilchrist & Zakrajsek 2012). The level is read in Build-up; here it is the change.",
              transmits="Wider spreads -> refinancing costs jump -> issuance stops for weaker borrowers."),
    Indicator("vix", "Equity volatility (VIX)", "D", "fred", "VIXCLS",
              why="The market's price of equity crash insurance.", transmits="Higher VIX -> VaR limits bind -> deleveraging."),
    Indicator("move", "Treasury volatility (MOVE)", "D", "yahoo", "^MOVE",
              why="Volatility in the collateral market everything else is funded against.",
              transmits="Higher Treasury vol -> bigger repo haircuts and margin -> less leverage capacity."),
    Indicator("fx_vol", "Dollar volatility", "D", "model", "fx_vol",
              why="1-month realised volatility of the dollar index.", transmits="FX hedging costs and carry-trade unwinds."),
    Indicator("em_stress", "Emerging-market dollar bonds vs Treasuries", "D", "model", "em_stress",
              why="How far EM sovereign dollar bonds (EMB) have lagged Treasuries from their 1-year high; capital-flow "
                  "reversals hit EM first (Forbes & Warnock 2012).",
              transmits="EM outflows -> dollar funding stress -> global risk-off."),
    # ======== consequence (shown, not scored)
    Indicator("gar_5", "Growth-at-Risk: bad-case GDP growth next year", "macro", "model", "gar", direction=-1,
              why="5th-percentile forecast of US GDP growth over the next 4 quarters, conditional on financial "
                  "conditions (Adrian, Boyarchenko & Giannone)."),

    Indicator("rec_prob", "Recession probability from the yield curve (12 months)", "macro", "model", "rec_prob",
              why="Probability of a US recession within 12 months from the 10y-3m Treasury spread (Estrella & Mishkin "
                  "1998; Estrella & Trubin 2006), using the NY Fed's published probit coefficients."),
    # ======== not in free data (listed so the gaps are visible)
    Indicator("gsib", "G-SIB systemic footprint (BCBS score)", "context", "manual", None, owner="manual"),
    Indicator("hf_basis", "Hedge-fund Treasury basis-trade leverage (OFR Hedge Fund Monitor)", "context", "manual", None, owner="manual"),
    Indicator("private_credit", "Private credit AUM, BDC non-accruals, NAV-loan leverage", "context", "manual", None, owner="manual"),
    Indicator("positioning", "Crowded positioning (CFTC futures, fund flows)", "context", "manual", None, owner="manual"),
    Indicator("unrealised", "Bank unrealised securities losses and uninsured deposits (FDIC QBP)", "context", "manual", None, owner="manual"),
]

_SRC = {'ebp_sentiment': "López-Salido, Stein & Zakrajšek (2017, QJE); Gilchrist & Zakrajšek (2012, AER). Data: FRED BAA10Y (Moody's).", 'nbfi_leverage': 'Brave & Butters (2011); Chicago Fed NFCI leverage sub-index. Data: FRED NFCILEVERAGE.',
    'credit_gap': 'Borio & Drehmann (2009); Drehmann, Borio & Tsatsaronis (2011); Basel III CCyB guide. Data: BIS via FRED QUSPAM770A.',
    'rzone': 'Greenwood, Hanson, Shleifer & Sørensen (2022, JF). Data: BIS credit (QUSPAM770A), S&P 500, Case-Shiller (CSUSHPINSA).',
    'corp_debt': 'Mian, Sufi & Verner (2017, QJE) on debt build-ups. Data: Fed Financial Accounts via FRED BCNSDODNS / GDP.',
    'hh_debt': 'Mian, Sufi & Verner (2017, QJE); Jordà, Schularick & Taylor (2013). Data: FRED HDTGPDUSQ163N.',
    'low_vol': 'Danielsson, Valenzuela & Zer (2018, RFS); Brunnermeier & Sannikov (2014). Data: S&P 500 realised vol vs its 5-year average (Yahoo).',
    'hh_dsr': 'Drehmann & Juselius (2014, IJF). Data: Fed via FRED TDSP.',
    'srisk_gdp': 'Brownlees & Engle (2017, RFS); Acharya, Engle & Richardson (2012). Data: Yahoo prices and balance sheets.',
    'dcovar_max': 'Adrian & Brunnermeier (2016, AER). Data: Yahoo weekly returns; FRED BAA10Y, T10Y3M; VIX.',
    'dcovar_private': 'Adrian & Brunnermeier (2016) applied to listed alt managers and BDCs. Data: Yahoo.',
    'dealer_lev': 'Adrian & Shin (2010, JFI); Adrian, Etula & Muir (2014, JF). Data: Fed Financial Accounts via FRED BOGZ1FL664090005Q / BOGZ1FL665080003Q.',
    'fire_sale': 'Greenwood, Landier & Thesmar (2015, JFE); Duarte & Eisenbach (2021, JF); Cont & Schaanning (2017).',
    'absorption': 'Kritzman, Li, Page & Rigobon (2011, JPM). Data: Yahoo daily returns of 40+ US financials.',
    'dy_total': 'Diebold & Yilmaz (2012, IJF; 2014, JoE). Data: Yahoo high/low range volatility of 12 ETFs.',
    'granger_dgc': 'Billio, Getmansky, Lo & Pelizzon (2012, JFE). Data: Yahoo monthly sector returns.',
    'rrp_buffer': 'Afonso, Cipriani, Copeland et al. (2022, NY Fed); Copeland, Duffie & Yang (2021) on reserves. Data: FRED RRPONTSYD.',
    'reserves_gdp': 'Copeland, Duffie & Yang (2021, NY Fed SR 974) on the Sept-2019 repo spike; Lopez-Salido & Vissing-Jorgensen (2023). Data: FRED WRESBAL.',
    'sofr_iorb': 'Afonso, Giannone, La Spada & Williams (2022, NY Fed SR 1019) on the reserve demand curve. Data: FRED SOFR, IORB/IOER.',
    'srf_usage': 'Fed Standing Repo Facility. Data: FRED RPONTSYD (2021 onward).',
    'cp_spread': 'Gorton & Metrick (2012, JFE) on wholesale runs; replaces the discontinued TED spread. Data: FRED DCPF3M − DTB3.',
    'usd_6m': 'Bruno & Shin (2015, JME); Avdjiev, Du, Koch & Shin (2019, AER:I); Miranda-Agrippino & Rey (2020). Data: FRED DTWEXBGS.',
    'xccy_basis': 'Du, Tepper & Verdelhan (2018, JF). Bloomberg only.',
    'stlfsi': 'Kliesen & Smith (2010); St. Louis Fed FSI v4. Data: FRED STLFSI4.',
    'nfci': 'Brave & Butters (2011); Chicago Fed. Data: FRED NFCI.',
    'bank_rel_dd': 'Jiang, Matvos, Piskorski & Seru (2024, JFE) on 2023 bank fragility. Data: Yahoo KRE / SPY.',
    'sloos_ci': 'Lown & Morgan (2006, JMCB); Bassett, Chosak, Driscoll & Zakrajšek (2014, JME). Data: Fed SLOOS via FRED DRTSCILM.',
    'cre_delinq': 'Fed call-report delinquency rates. Data: FRED DRCRELEXFACBS.',
    'pc_mark': 'Practitioner proxy (listed BDCs vs high yield); see Fed FSR (2024-25) on private credit opacity. Data: Yahoo BIZD / HYG.',
    'gar_5': 'Adrian, Boyarchenko & Giannone (2019, AER). Data: FRED GDPC1, NFCI.'}
_SRC.update({'house_gap': "Borio & Lowe (2002, BIS WP 114); Jordà, Schularick & Taylor (2015, JIE 'Leveraged bubbles'). One-sided HP gap, λ = 400,000. Data: BIS via FRED QUSR628BIS.", 'eq_val': 'Shiller (2000); Jordà, Schularick & Taylor (2015). Data: Fed Financial Accounts via FRED NCBEILQ027S / GDP.', 'margin': 'Adrian & Shin (2010). Data: Fed Financial Accounts via FRED BOGZ1FL663067003Q (dealer margin loans) / NCBEILQ027S.', 'stock_bond': 'Campbell, Pflueger & Viceira (2020, JPE). Data: Yahoo SPY and IEF daily returns, 63-day correlation.', 'fiscal': 'Romer & Romer (2018, Economica); Jordà, Schularick & Taylor (2016, Econ Policy). Data: FRED GFDEGDQ188S.', 'bank_capital': "Jordà, Richter, Schularick & Taylor (2021, RFS 'Bank capital redux').", 'credit_widen': 'Gilchrist & Zakrajšek (2012, AER). Data: FRED BAA10Y, 13-week change.', 'vix': 'Whaley (2000); Bekaert & Hoerova (2014). Data: FRED VIXCLS. Already a component of the St. Louis Fed index.', 'move': 'Data: ICE BofA MOVE index via Yahoo ^MOVE. Already a component of the St. Louis Fed index.', 'fx_vol': 'Menkhoff, Sarno, Schmeling & Schrimpf (2012, JF) on FX volatility risk. Data: Yahoo DX-Y.NYB, 21-day realised.', 'em_stress': 'Forbes & Warnock (2012, JIE). Data: Yahoo EMB / IEF.', 'rec_prob': "Estrella & Mishkin (1998, REStat); Estrella & Trubin (2006, NY Fed CIEF). Probit P = Φ(−0.5333 − 0.6330 × spread) on the monthly 10y−3m spread. Uses FRED T10Y3M, not the NY Fed's bond-equivalent 3m yield, so readings differ slightly from the NY Fed's (approximate)."})
for _i in REGISTRY:
    _i.src = _SRC.get(_i.id, _i.src)

# Pre-specified inclusion rule (set BEFORE looking at the out-of-sample test, Oct 2026): an indicator is scored
# only if (a) published work shows it predicts crises / financial tail events and (b) it has no known structural
# break inside our sample. Everything else is shown in its link as "monitored".
_NOT_SCORED = {
    "dealer_lev": "Structural break: dealer leverage fell from the 30s to about 16x after post-2008 regulation, so "
                  "history says 'safe' for reasons unrelated to risk.",
    "usd_6m": "Global channel; the index targets US financial outcomes. Shown for cross-border context.",
    "sloos_ci": "Lags the cycle: banks tighten after stress appears. Confirms rather than predicts.",
    "cre_delinq": "Lags the cycle: delinquencies confirm losses already under way.",
    "pc_mark": "Practitioner proxy with history only from 2013; not a published measure.",
    "eq_val": "Trends up over decades (non-stationary), and equity bubbles without leverage rarely cause banking crises.",
    "margin": "No published evidence that margin credit predicts crises on its own.",
    "stock_bond": "A regime indicator for diversification, not a published crisis predictor.",
    "fiscal": "Trends up over decades (non-stationary): its percentile is near 100 regardless of risk.",
    "vix": "Already inside the St. Louis Fed stress index; scoring it again would double count.",
    "move": "Already inside the St. Louis Fed stress index; scoring it again would double count.",
    "fx_vol": "Partly inside the St. Louis Fed stress index; no separate crisis-prediction evidence.",
    "em_stress": "Global channel; the index targets US financial outcomes.",
}
_NS_TAG = {"dealer_lev": "structural break", "usd_6m": "global", "sloos_ci": "lags", "cre_delinq": "lags",
           "pc_mark": "short history", "eq_val": "trends up", "margin": "no evidence", "stock_bond": "no evidence",
           "fiscal": "trends up", "vix": "double counts", "move": "double counts", "fx_vol": "double counts",
           "em_stress": "global"}
for _i in REGISTRY:
    if _i.id in _NOT_SCORED:
        _i.scored, _i.not_scored_why, _i.ns_tag = False, _NOT_SCORED[_i.id], _NS_TAG.get(_i.id, "")

# FRED series pulled in a single pass
FRED_SERIES = sorted({i.series for i in REGISTRY if i.source in ("fred",) and i.series} |
                     {"QUSPAM770A", "BAMLH0A0HYM2", "BCNSDODNS", "GDP", "GDPC1", "SOFR", "IORB",
                      "DCPF3M", "DTB3", "T10Y3M", "NFCI", "IOER", "CSUSHPINSA", "BAA10Y",
                      "TDSP", "DRTSCILM", "DRCRELEXFACBS", "DTWEXBGS", "INDPRO", "QUSR628BIS", "NCBEILQ027S",
                      "BOGZ1FL663067003Q", "VIXCLS",
                      "BOGZ1FL664090005Q", "BOGZ1FL665080003Q"})

# The story: a systemic event needs FUEL (an excess to unwind), FAULT LINES (a way for losses to spread),
# weak SHOCK ABSORBERS (no liquidity to absorb forced selling) and IGNITION (a shock actually happening).
PILLARS = {
    "A": "Build-up",
    "B": "Contagion",
    "C": "Shock absorbers",
    "D": "Trigger",
}
PILLAR_Q = {
    "A": "Are excesses building that could unwind?",
    "B": "If something breaks, would the loss spread to the rest of the system?",
    "C": "Does the system have the liquidity to absorb forced selling?",
    "D": "Is the system being tested right now?",
}
