"""
Streamlit front-end:  streamlit run app.py

Thin by design: sidebar sets parameters -> sysrisk.pipeline.run (cached) -> sysrisk.report.render
-> the same HTML dashboard you can also generate offline and share. Data fetching, maths and UI
live in separate modules (data.py / models.py / report.py).
"""
import io
import zipfile
from dataclasses import replace

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from sysrisk.config import FIN_UNIVERSE
from sysrisk.pipeline import Params, get_provider, run
from sysrisk.report import render

st.set_page_config(page_title="Systemic Risk Monitor", layout="wide")

with st.sidebar:
    st.header("Data")
    source = st.radio("Source", ["free", "bbg", "demo"], index=0,
                      format_func={"free": "Yahoo + FRED", "bbg": "Bloomberg + FRED",
                                   "demo": "Synthetic demo"}.get)
    start = st.date_input("History start", pd.Timestamp("2003-01-01"))
    sectors = st.multiselect("Financial sectors", list(FIN_UNIVERSE), default=list(FIN_UNIVERSE))
    st.header("Model parameters")
    q = st.select_slider("CoVaR quantile", [0.01, 0.025, 0.05, 0.10], value=0.05)
    k = st.slider("SRISK prudential capital k", 0.03, 0.12, 0.08, 0.005)
    crash = st.slider("SRISK market crash", 0.2, 0.6, 0.40, 0.05)
    dyw = st.slider("DY window (days)", 100, 500, 200, 25)
    dyh = st.slider("DY horizon (days)", 5, 20, 10)
    go = st.button("Run", type="primary")


@st.cache_data(show_spinner="Fetching data and estimating models (1-3 min)...", ttl=6 * 3600)
def compute(source, start, sectors, q, k, crash, dyw, dyh):
    p = replace(Params(), start=str(start), sectors=list(sectors), covar_q=q, srisk_k=k, srisk_crash=crash,
                dy_window=dyw, dy_horizon=dyh)
    return run(get_provider(source), p, log=lambda *_: None)


if go or "R" not in st.session_state:
    st.session_state.R = compute(source, start, tuple(sectors), q, k, crash, dyw, dyh)
R = st.session_state.R

components.html(render(R), height=4200, scrolling=True)

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    for name in ["panel", "scores", "signals", "pillars", "dcovar", "srisk_sector", "srisk_firm", "gar", "credit_gap"]:
        z.writestr(f"{name}.csv", R[name].to_csv())
    z.writestr("systemic_risk_index.csv", pd.concat([R["index"], R["regime"].rename("level")], axis=1).to_csv())
st.download_button("Download all metrics (CSV zip)", buf.getvalue(), "systemic_risk_metrics.zip", "application/zip")
st.download_button("Download dashboard (HTML)", render(R), "systemic_risk_monitor.html", "text/html")
