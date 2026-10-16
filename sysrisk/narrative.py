"""
Narrative watch: qualitative reads for risks with no usable public time series.
NOT scored. Updated by hand; every fact carries its date and source. Edit AS_OF when you refresh.
signal: "calm" | "watch" | "warning"
"""
AS_OF = "16 Oct 2026"

NARRATIVE = [
    {
        "id": "ai_obs", "title": "AI off-balance-sheet obligations", "short": "AI off-balance-sheet financing", "link": "Build-up", "signal": "warning",
        "head": "AI capex is moving off balance sheet into SPVs and leases, and the first project has stumbled.",
        "facts": [
            ("Hidden size", "Moody's puts hyperscaler lease commitments at about $970bn, of which about $660bn is not yet on "
             "balance sheet. A Wall Street Journal tally puts off-balance-sheet obligations for four hyperscalers at about "
             "$2.4tn, including chip purchase commitments.", "Van Nieuwerburgh, BPEA draft, Sep 2026"),
            ("The template", "Meta's Hyperion JV issued $27bn of A+ bonds at about 90% of asset value with debt service cover "
             "of 1.12x. A near-copy (Sopaipilla) issued $12.3bn in Jul 2026.", "Van Nieuwerburgh, BPEA draft, Sep 2026"),
            ("First crack", "Oracle sent a force majeure notice on Project Jupiter (24 Sep 2026). Its ~$18bn construction loan "
             "is hard to syndicate and was quoted at 89-91 cents.", "ROIC.ai news, 24 Sep 2026"),
            ("Banks warehousing", "Banks are reported to be trying to sell down several large data-center loans and to use "
             "risk transfers. Second-hand report of Bloomberg and FT stories; treat as indicative.",
             "Naked Capitalism, 12 Oct 2026, citing Bloomberg (8 Oct) and FT"),
        ],
        "transmits": "Single-tenant assets, GPUs that age in 3-6 years financed with 20-year debt, and leverage that sits "
                     "with private credit, banks and insurers rather than the hyperscalers. A capex pause would hit all of "
                     "these at once.",
        "watch": "More force majeure or lease deferrals; data-center loan prices below 90; Oracle and other AI-linked CDS; "
                 "bank risk-transfer deals on data-center loans.",
        "sources": [("Van Nieuwerburgh (2026), Financing the AI Buildout, BPEA draft",
                     "https://www.brookings.edu/wp-content/uploads/2026/09/4c_Van-Nieuwerburgh.pdf"),
                    ("Oracle invokes force majeure on Project Jupiter (ROIC.ai)",
                     "https://www.roic.ai/news/oracle-invokes-force-majeure-on-project-jupiter-as-ai-data-center-financing-stumbles-09-24-2026"),
                    ("Banks struggle to digest the mounting debt driving the AI boom (Naked Capitalism)",
                     "https://www.nakedcapitalism.com/2026/10/banks-struggle-to-digest-the-mounting-debt-driving-the-ai-boom.html")],
    },
    {
        "id": "pc_stress", "title": "Private credit: defaults, PIK and redemptions", "short": "private credit", "link": "Trigger", "signal": "warning",
        "head": "Private credit defaults are at a record and retail money is trying to leave; gates are holding so far.",
        "facts": [
            ("Defaults", "Fitch's private credit default rate was about 6.1% (12-month) in July, a record and more than "
             "double the high-yield bond rate of about 2.7%.", "Fitch via Crypto Briefing, Aug 2026; Bloomberg Law, May 2026"),
            ("Non-accruals", "BDC non-accruals rose to 2.01% of debt at cost in Q1 2026 from 1.45%. Octus's adjusted "
             "measure is 3.24%.", "Octus, 16 Jun 2026"),
            ("PIK", "32 borrowers ($1.3bn of loans) switched cash interest to PIK in Q1 2026 alone.", "Octus, 16 Jun 2026"),
            ("Redemptions", "Two Blue Owl funds received $5.4bn of withdrawal requests in Q1 and $4.7bn in Q2 and kept "
             "their caps. Cliffwater's flagship fund saw requests for 17% of shares in Q2.",
             "DealStreetAsia, 2 Jul 2026; Octus, 16 Jun 2026"),
        ],
        "transmits": "Gated funds cannot sell, so stress shows up slowly through marks, PIK and gates rather than prices. "
                     "The risk is a forced-seller spiral if gates break, and bank exposure through NAV and subscription lines.",
        "watch": "Q3 tender results (late Oct-Nov); non-accruals above 3% reported; BDC discount to NAV (Trigger section).",
        "sources": [("Octus BDC Weekly Roundup, 16 Jun 2026", "https://octus.com/resources/articles/octus-bdc-weekly-roundup-061626/"),
                    ("Blue Owl keeps withdrawal cap (DealStreetAsia)", "https://www.dealstreetasia.com/stories/blue-owl-withdrawal-limits-487740"),
                    ("US private credit defaults hit record 6% in April: Fitch (Bloomberg Law)",
                     "https://news.bloomberglaw.com/bankruptcy-law/us-private-credit-defaults-hit-new-record-of-6-in-april-fitch"),
                    ("Fitch US default rates, July 2026 (Crypto Briefing)", "https://cryptobriefing.com/fitch-us-corporate-default-rates-july-2026/")],
    },
    {
        "id": "bank_ul", "title": "Bank unrealised securities losses", "short": "bank unrealised losses", "link": "Shock absorbers", "signal": "watch",
        "head": "Unrealised losses are rising again, but bank profits are strong and deposits are growing.",
        "facts": [
            ("Size", "US banks held $325bn of unrealised securities losses at end-Q1 2026, up $19bn on the quarter and the "
             "second rise in a row ($215bn held-to-maturity).", "FDIC Q1 2026 QBP, via Bitcoin.com News"),
            ("Q2 2026", "The FDIC still flags 'elevated unrealized losses' for supervisory attention. Net income was $90bn "
             "and deposits grew for an eighth straight quarter.", "FDIC Q2 2026 QBP, via Crane Data"),
        ],
        "transmits": "Losses only bite if banks must sell, which is what happened at SVB: a deposit run forces sales and "
                     "turns paper losses into capital losses.",
        "watch": "Deposit outflows at regional banks; the regional bank stock row (Trigger); long-end yields.",
        "sources": [("FDIC: US banks $325bn unrealised losses, Q1 2026 (Bitcoin.com News)",
                     "https://news.bitcoin.com/fdic-us-banks-325-billion-unrealized-losses-q1-2026/"),
                    ("FDIC Q2 2026 Quarterly Banking Profile (Crane Data)", "https://cranedata.com/archives/all-articles/11492/")],
    },
    {
        "id": "flows", "title": "Fund flows and money funds", "short": "fund flows", "link": "Trigger", "signal": "calm",
        "head": "No sign of a rush for the exit in public funds: bond funds are taking money in.",
        "facts": [
            ("Bonds", "Global bond funds took in $7.8bn in the week to 14 Oct, a fourth straight week of inflows; corporate "
             "bond funds +$1.0bn.", "LSEG Lipper via Reuters, 16 Oct 2026"),
            ("Money funds", "Money market funds lost $46.7bn after taking in $154bn the week before, which looks like "
             "normal tax- and quarter-related swings.", "LSEG Lipper via Reuters, 16 Oct 2026"),
            ("One soft spot", "Technology sector equity funds lost $4.75bn in the same week.", "LSEG Lipper via Reuters, 16 Oct 2026"),
        ],
        "transmits": "Open-ended bond funds promise daily cash on less liquid assets. Large outflows force selling into "
                     "thin markets (Goldstein, Jiang & Ng 2017).",
        "watch": "High-yield and loan fund outflows for several weeks running; prime money fund outflows.",
        "sources": [("Global equity funds draw inflows for fourth week (Reuters)",
                     "https://www.933thedrive.com/2026/10/16/global-equity-funds-draw-inflows-for-fourth-week-as-treasury-yields-ease/")],
    },
]

NOT_COVERED = ("Not covered yet: cross-border dollar credit (BIS, quarterly) and IG corporate bond liquidity. "
               "Neither has a recent public read we can trust.")
