"""Second Bloomberg pass: SOFR-era cross-currency basis and bond liquidity indices. Writes bbg_data2.zip."""
import os, sys, zipfile
sys.argv = sys.argv[:1]
import bbg_pull as B   # reuse connection, search and history helpers

B.OUT = os.path.join(B.HERE, "bbg_data2")
os.makedirs(B.OUT, exist_ok=True)
YK = {"<index>": " Index", "<crncy>": " Curncy", "<cmdty>": " Comdty", "<govt>": " Govt", "<corp>": " Corp",
      "<equity>": " Equity", "<mtge>": " Mtge", "<muni>": " Muni", "<pfd>": " Pfd"}


def fix(sec):
    for k, v in YK.items():
        if sec.lower().endswith(k):
            return sec[: -len(k)] + v
    return sec


def main():
    s = B.connect()
    queries = ["USDJPY SOFR TONA cross currency basis 1 year", "JPY USD xccy basis 1Y SOFR",
               "USD JPY OIS basis swap 1Y", "EUR USD ESTR SOFR cross currency basis 1 year",
               "EUR USD xccy basis 1Y SOFR", "Government Securities Liquidity Index",
               "Bloomberg US Government Securities Liquidity", "Bloomberg Japan Government Securities Liquidity",
               "Bloomberg UK Government Securities Liquidity", "Bloomberg German Government Securities Liquidity",
               "corporate bond liquidity index US investment grade", "GVLQ"]
    rows = []
    for q in queries:
        try:
            rows += B.instrument_search(s, q, n=20)
        except Exception as e:
            B.log(f"   search '{q}' failed: {e}")
    import pandas as pd
    df = pd.DataFrame(rows)
    if not df.empty:
        df["ticker"] = df["security"].map(fix)
        df.to_csv(os.path.join(B.OUT, "search2.csv"), index=False)
    B.log(f"{len(df)} search results")
    cands = sorted(set(df["ticker"])) if not df.empty else []
    cands += [".JYCCBS3M G Index", ".JYCCBS1M G Index", "S0092P1 Curncy", "S0092PC Curncy", "S0092P2 Curncy",
              "XEURBI Index", "GVLQUSD Index", "GVLQJPY Index", "GVLQGBP Index", "GVLQEUR Index",
              "JYBSS1 Curncy", "JYXOQQ1 Curncy", "JYBSSO1 Curncy", "EUXOQQ1 Curncy", "EUBSSO1 Curncy"]
    cands = [c for c in dict.fromkeys(cands) if not c.endswith(" Equity")][:80]
    B.bdh(s, cands, ["PX_LAST"], start="20050101", tag="xccy_liq")
    with open(os.path.join(B.OUT, "run_log2.txt"), "w") as f:
        f.write("\n".join(B.LOG))
    zpath = os.path.join(B.HERE, "bbg_data2.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(B.OUT):
            z.write(os.path.join(B.OUT, fn), fn)
    B.log(f"Done: {zpath}")
    s.stop()


if __name__ == "__main__":
    main()
