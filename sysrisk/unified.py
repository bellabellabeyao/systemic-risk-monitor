"""
One evaluation for every row on the page and in the Excel.

Every series gets a 0-100 score (higher = riskier) and a colour from the same bands:
  - model series: expanding-window percentile vs its own history (sysrisk.pipeline.score), real time;
  - judgement series (no usable time series): analyst traffic light mapped to the middle of its band.

Theme score  = weighted mean of its series. Weights: model series that pass the evidence screen this month 1.0,
               other model series 0.5 (context), judgement series 0.5.
Stage score  = mean of its theme scores, per lens (broad system, AI channel).
Colour       = GREEN below 40, AMBER 40-65, RED 65 and above (the index's own Moderate / High cut-offs).

Two aggregates, two jobs:
  Condition (this module): how stretched each stage is today, using everything we track. Descriptive.
  Early warning (sysrisk.pipeline): the evidence-screened index. The only number tested out of sample.
Out of sample, adding the context series to the early-warning index makes its drawdown forecasts worse
(negative quantile R2), which is why condition and early warning are kept as separate numbers.
"""
from __future__ import annotations

import pandas as pd

from . import signal_board as SB
from .config import PILLARS, REGISTRY

REG = {i.id: i for i in REGISTRY}


def _model_rows(R, story, ids):
    if R is None:
        return []
    S = R["scores"].loc[:story.asof]
    mask = R.get("screen_mask")
    out = []
    for i in ids:
        if i not in S or S[i].dropna().empty:
            continue
        s = S[i].dropna()
        screened = bool(mask is not None and i in mask and mask[i].loc[:story.asof].iloc[-1])
        tier = "screened" if screened else "context"
        sc = float(s.iloc[-1])
        out.append({"id": i, "metric": REG[i].name, "kind": "model", "tier": tier, "weight": SB.WEIGHTS[tier],
                    "score": round(sc, 1), "signal": SB.colour(sc),
                    "d13": None if len(s) < 14 else round(float(s.iloc[-1] - s.iloc[-14]), 1),
                    "reading": story.reading(i), "asof": "weekly model, " + s.index[-1].strftime("%d %b %Y"),
                    "note": REG[i].not_scored_why if tier == "context" else "Passes the evidence screen this month.",
                    "source": REG[i].src or REG[i].source, "code": f"model: {i}", "refreshed": True})
    return out


def _judgement_rows(key):
    out = []
    for (k, metric, sig, prev, reading, note, source, asof, code, refreshed) in SB.DETAIL:
        if k != key:
            continue
        sc = SB.JUDGEMENT_SCORE[sig]
        out.append({"metric": metric, "kind": "judgement", "tier": "judgement", "weight": SB.WEIGHTS["judgement"],
                    "score": sc, "signal": sig, "prev": prev, "d13": None, "reading": reading, "asof": asof,
                    "note": note, "source": source, "code": code, "refreshed": refreshed})
    return out


def evaluate(R=None, story=None) -> dict:
    """Theme, stage and grid scores. Works without model results (judgement series only)."""
    if R is not None and story is None:
        from .report import Story, apply_screen_flags
        apply_screen_flags(R)
        story = Story(R)
    themes = []
    for key, stage, lens, name, ids, comment, prev in SB.THEMES:
        rows = _model_rows(R, story, ids) + _judgement_rows(key)
        w = sum(r["weight"] for r in rows)
        score = None if not w else sum(r["score"] * r["weight"] for r in rows) / w
        themes.append({"key": key, "stage": stage, "lens": lens, "theme": name, "comment": comment,
                       "score": None if score is None else round(score, 1), "signal": SB.colour(score), "prev": prev,
                       "n": {t: sum(r["tier"] == t for r in rows) for t in SB.WEIGHTS}, "rows": rows})
    grid = {}
    for sk, *_ in SB.STAGES:
        for lk, _ in SB.LENSES:
            ts = [t for t in themes if t["stage"] == sk and t["lens"] == lk and t["score"] is not None]
            sc = None if not ts else sum(t["score"] for t in ts) / len(ts)
            grid[f"{sk}|{lk}"] = {"score": None if sc is None else round(sc, 1), "signal": SB.colour(sc),
                                  "themes": len(ts), "series": sum(len(t["rows"]) for t in ts)}
    lens_index = {}
    for lk, _ in SB.LENSES:
        v = [grid[f"{sk}|{lk}"]["score"] for sk, *_ in SB.STAGES if grid[f"{sk}|{lk}"]["score"] is not None]
        lens_index[lk] = None if not v else round(sum(v) / len(v), 1)
    ew = {}
    if R is not None:
        for sk, n, nm, q, link in SB.STAGES:
            P = R["pillars"][link].loc[:story.asof].dropna()
            kept = [i for i in R["screen"]["latest"] if PILLARS.get(REG[i].pillar) == link]
            ew[sk] = {"score": round(float(P.iloc[-1]), 1), "n": len(kept), "series": [REG[i].name for i in kept]}
    return {"asof": SB.AS_OF, "prev_asof": SB.PREV_ASOF, "sources": SB.SOURCES, "bands": SB.BANDS,
            "weights": SB.WEIGHTS, "judgement_score": SB.JUDGEMENT_SCORE,
            "stages": [dict(zip(["key", "n", "name", "q", "model_link"], s)) for s in SB.STAGES],
            "lenses": [dict(zip(["key", "name"], l)) for l in SB.LENSES],
            "themes": themes, "grid": grid, "condition": lens_index, "early_warning": ew,
            "model_asof": None if story is None else story.asof.strftime("%d %b %Y")}


def headline_text(U, level):
    """Title and one summary sentence from the condition scores (all tracked series)."""
    g = lambda st, l="broad": U["grid"][f"{st}|{l}"]["score"] or 0
    f, t, a, th = g("fragility"), g("triggers"), g("amplifiers"), g("threshold")
    parts = [
        "fragility is high" if f >= 65 else "fragility is building" if f >= 40 else "fragility is low",
        "the system is being tested" if t >= 65 else "early stress is showing" if t >= 40 else "nothing is testing the system yet",
        "losses would spread quickly" if a >= 65 else "spillover channels are elevated" if a >= 40 else "spillover channels are quiet",
        "buffers are thin" if th >= 65 else "some buffers are thinning" if th >= 40 else "buffers are intact",
    ]
    title = f"Systemic risk is {level.lower()}: " + ", ".join(parts[:-1]) + " and " + parts[-1]
    ai, br = U["condition"].get("ai"), U["condition"].get("broad")
    if ai is not None and br is not None and ai >= br + 5:
        title += "; the AI channel is the hot spot"
    sent = (f"Across everything we track, the broad system scores {br:.0f} and the AI channel {ai:.0f} out of 100 "
            f"(condition score; judgement readings as of {SB.AS_OF}). ")
    return title, sent
