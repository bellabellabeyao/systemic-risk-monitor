"""
Bloomberg pull for the Systemic Risk Monitor.

Run on the machine where the Bloomberg Terminal is logged in (for you: Windows inside Parallels):
    py -m pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi
    py -m pip install pandas
    py bbg_pull.py
(On a Mac use python3 instead of py. To connect to a Terminal elsewhere: py bbg_pull.py <host> <port>)

It does three things and writes everything into bbg_data.zip next to this file:
  1. Checks the Bloomberg connection.
  2. Searches Bloomberg for the right tickers and fields (we do not guess them).
  3. Pulls history for every candidate and reports which ones worked.
Send bbg_data.zip back to Claude. Nothing is uploaded anywhere by this script.
"""
import datetime as dt
import os
import sys
import zipfile

try:
    import blpapi
except ImportError:
    sys.exit("blpapi is not installed. Run:\n  python3 -m pip install --index-url="
             "https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi")
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "bbg_data")
os.makedirs(OUT, exist_ok=True)
LOG = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg)
    LOG.append(msg)


# ------------------------------------------------------------------ connection
def connect():
    # optional: python bbg_pull.py <host> <port>  (e.g. the Parallels Windows VM's IP if run from the Mac side)
    targets = [(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 8194)] if len(sys.argv) > 1 else \
        [("localhost", 8194), ("127.0.0.1", 8194)]
    for host, port in targets:
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        s = blpapi.Session(opts)
        if s.start():
            log(f"Connected to Bloomberg at {host}:{port}")
            return s
    sys.exit(f"Could not connect to Bloomberg at {targets}. Make sure the Bloomberg Terminal is open and logged in. "
             "If Bloomberg runs in the Parallels Windows VM, run this script inside Windows instead.")


def service(s, name):
    if not s.openService(name):
        raise RuntimeError(f"cannot open {name}")
    return s.getService(name)


def collect(s, timeout_ms=60000):
    msgs = []
    while True:
        ev = s.nextEvent(timeout_ms)
        for m in ev:
            msgs.append(m)
        if ev.eventType() == blpapi.Event.RESPONSE:
            return msgs
        if ev.eventType() == blpapi.Event.TIMEOUT:
            log("   (timed out waiting for Bloomberg)")
            return msgs


# ------------------------------------------------------------------ discovery
def instrument_search(s, query, n=15):
    svc = service(s, "//blp/instruments")
    req = svc.createRequest("instrumentListRequest")
    req.set("query", query)
    req.set("maxResults", n)
    s.sendRequest(req)
    rows = []
    for m in collect(s, 20000):
        if m.hasElement("results"):
            res = m.getElement("results")
            for i in range(res.numValues()):
                r = res.getValueAsElement(i)
                rows.append({"query": query, "security": r.getElementAsString("security"),
                             "description": r.getElementAsString("description")})
    return rows


def field_search(s, spec):
    svc = service(s, "//blp/apiflds")
    req = svc.createRequest("FieldSearchRequest")
    req.set("searchSpec", spec)
    s.sendRequest(req)
    rows = []
    for m in collect(s, 20000):
        if m.hasElement("fieldData"):
            fd = m.getElement("fieldData")
            for i in range(fd.numValues()):
                f = fd.getValueAsElement(i)
                if f.hasElement("fieldInfo"):
                    info = f.getElement("fieldInfo")
                    rows.append({"search": spec, "mnemonic": info.getElementAsString("mnemonic"),
                                 "description": info.getElementAsString("description")})
    return rows


# ------------------------------------------------------------------ history
def bdh(s, tickers, fields, start="20020101", per="DAILY", tag=""):
    svc = service(s, "//blp/refdata")
    req = svc.createRequest("HistoricalDataRequest")
    for t in tickers:
        req.getElement("securities").appendValue(t)
    for f in fields:
        req.getElement("fields").appendValue(f)
    req.set("startDate", start)
    req.set("endDate", dt.date.today().strftime("%Y%m%d"))
    req.set("periodicitySelection", per)
    s.sendRequest(req)
    rows, status = [], {}
    for m in collect(s, 120000):
        if not m.hasElement("securityData"):
            continue
        sd = m.getElement("securityData")
        sec = sd.getElementAsString("security")
        if sd.hasElement("securityError"):
            status[sec] = "invalid ticker"
            continue
        bad = []
        if sd.hasElement("fieldExceptions"):
            fe = sd.getElement("fieldExceptions")
            for i in range(fe.numValues()):
                bad.append(fe.getValueAsElement(i).getElementAsString("fieldId"))
        fd = sd.getElement("fieldData")
        for i in range(fd.numValues()):
            r = fd.getValueAsElement(i)
            d = r.getElementAsDatetime("date")
            for f in fields:
                if r.hasElement(f):
                    try:
                        rows.append({"date": pd.Timestamp(d.year, d.month, d.day), "ticker": sec, "field": f,
                                     "value": r.getElementAsFloat(f)})
                    except Exception:
                        pass
        n = sum(1 for x in rows if x["ticker"] == sec)
        status[sec] = f"{n} points" + (f"; bad fields: {bad}" if bad else "")
    for t in tickers:
        status.setdefault(t, "no data returned")
    df = pd.DataFrame(rows)
    if tag and not df.empty:
        df.to_csv(os.path.join(OUT, f"{tag}.csv"), index=False)
    for t, st in status.items():
        log(f"   {tag:14s} {t:32s} {st}")
    return df


# ------------------------------------------------------------------ what we need
FINANCIALS = ["JPM", "BAC", "C", "WFC", "GS", "MS", "BNY", "STT", "USB", "PNC", "TFC", "FITB", "KEY", "RF", "CFG", "MTB",
              "MET", "PRU", "AIG", "LNC", "CRBG", "EQH", "BX", "KKR", "APO", "ARES", "OWL", "BN", "ARCC", "BXSL",
              "OBDC", "FSK", "MAIN", "HTGC", "SCHW", "IBKR", "HOOD", "ICE", "CME"]
# primary dealers' listed parents (He, Kelly & Manela 2017 use the NY Fed primary dealer list)
DEALERS = ["JPM US", "BAC US", "C US", "GS US", "MS US", "WFC US", "JEF US", "BCS US", "DB US", "UBS US", "HSBC US",
           "BNPQY US", "MUFG US", "MFG US", "NMR US", "RY US", "TD US", "BMO US", "BNS US", "CM US", "SCGLY US"]
BDCS = ["ARCC US", "BXSL US", "OBDC US", "FSK US", "MAIN US", "HTGC US", "GBDC US", "PSEC US", "TSLX US", "OCSL US"]
BANKS_CET1 = ["JPM US", "BAC US", "C US", "WFC US", "GS US", "MS US", "BNY US", "STT US", "USB US", "PNC US", "TFC US"]

SEARCHES = [  # instrument searches: we pick the right ticker from the results
    "USDJPY basis swap", "JPY cross currency basis", "EUR USD basis swap", "EUR cross currency basis",
    "Bloomberg US Government liquidity index", "Bloomberg Japan Government liquidity index",
    "US corporate high yield OAS", "US corporate investment grade OAS", "Bloomberg US Corporate liquidity",
    "BDC index", "CFTC leveraged funds",
]
FIELD_SEARCHES = ["common equity tier 1 ratio", "CET1", "price to book", "net asset value per share",
                  "total liabilities", "liquidity score"]
CANDIDATES = {  # tried directly; the report says which exist
    "spreads": (["LF98OAS Index", "LUACOAS Index", "LF98TRUU Index", "LUACTRUU Index"], ["PX_LAST"]),
    "xccy": (["JYBSS1 Curncy", "JYBS1 Curncy", "JYBSC1 Curncy", "JYBSSC1 Curncy", "EUBSV1 Curncy", "EUBS1 Curncy",
              "EUBSC1 Curncy", "EUBSVC Curncy", "JYBSVC Curncy"], ["PX_LAST"]),
}


def main():
    s = connect()
    log("\n1) Searching for tickers")
    found = []
    for q in SEARCHES:
        try:
            found += instrument_search(s, q)
        except Exception as e:
            log(f"   search '{q}' failed: {e}")
    pd.DataFrame(found).to_csv(os.path.join(OUT, "ticker_search.csv"), index=False)
    log(f"   {len(found)} results saved")
    fs = []
    for q in FIELD_SEARCHES:
        try:
            fs += field_search(s, q)
        except Exception as e:
            log(f"   field search '{q}' failed: {e}")
    pd.DataFrame(fs).to_csv(os.path.join(OUT, "field_search.csv"), index=False)
    log(f"   {len(fs)} field results saved")

    log("\n2) Pulling history")
    for tag, (tick, flds) in CANDIDATES.items():
        bdh(s, tick, flds, tag=tag)
    # top search hits for basis and liquidity, pulled so we can check them
    hits = [r["security"] for r in found if any(w in r["query"] for w in ["basis", "liquidity"])][:30]
    hits = [h if " " in h else h for h in hits]
    if hits:
        bdh(s, sorted(set(hits)), ["PX_LAST"], tag="search_hits")
    bdh(s, [f"{t} US Equity" for t in FINANCIALS], ["BS_TOT_LIAB2", "CUR_MKT_CAP"], start="20020101",
        per="QUARTERLY", tag="srisk_fund")
    bdh(s, [f"{t} Equity" for t in DEALERS], ["CUR_MKT_CAP", "BS_TOT_LIAB2", "TOT_COMMON_EQY"], start="19990101",
        per="QUARTERLY", tag="dealers")
    bdh(s, [f"{t} Equity" for t in BDCS], ["PX_TO_BOOK_RATIO", "PX_LAST", "BOOK_VAL_PER_SH"], start="20050101",
        per="MONTHLY", tag="bdc_nav")
    cet1_fields = sorted({r["mnemonic"] for r in fs if "tier 1" in r["description"].lower()
                          and "common" in r["description"].lower()})[:4] or ["BS_TIER1_COM_EQUITY_RATIO"]
    log(f"   CET1 fields tried: {cet1_fields}")
    bdh(s, [f"{t} Equity" for t in BANKS_CET1], cet1_fields, start="20050101", per="QUARTERLY", tag="cet1")

    with open(os.path.join(OUT, "run_log.txt"), "w") as f:
        f.write("\n".join(LOG))
    zpath = os.path.join(HERE, "bbg_data.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(OUT):
            z.write(os.path.join(OUT, fn), fn)
    log(f"\nDone. Send this file back to Claude:\n  {zpath}")
    s.stop()


if __name__ == "__main__":
    main()
