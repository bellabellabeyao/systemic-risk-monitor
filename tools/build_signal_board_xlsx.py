"""
Build the Systemic Risk Monitor workbook from the same evaluation as the website (sysrisk/unified.py).

One scale and one colour rule for every row, with a live formula chain:
  Detailed series score -> theme score (weighted average) -> stage condition (average of themes) -> overall.
Editing a judgement score (blue) on the Detailed sheet updates every theme, stage and colour.

Sheets: Summary Dashboard · Detailed Index Breakdown · Model Scores (with --results) · Sources & Codes

    python tools/build_signal_board_xlsx.py --out Systemic_Risk_Dashboard.xlsx [--results output/results.pkl]
"""
import argparse
import pickle
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sysrisk import signal_board as SB  # noqa: E402
from sysrisk import unified  # noqa: E402

NAVY, BLUE, WHITE, VIOLET = "1B1E3C", "1F3BFF", "FFFFFF", "5B3E96"
FILL = {"GREEN": ("C6EFCE", "006100"), "AMBER": ("FFEB9C", "7F6000"), "RED": ("FFC7CE", "9C0006")}
LENS_FILL = {"broad": ("E8ECF7", "1B1E3C"), "ai": ("EEE8F7", VIOLET)}
TIER = {"screened": "Model · passes test", "context": "Model · context", "judgement": "Judgement"}
F = "Arial"
thin = Side(style="thin", color="B7BEC9")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical="center")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
STAGE = {s[0]: s for s in SB.STAGES}
LENS = dict(SB.LENSES)
G, R_ = SB.BANDS
DET = "'Detailed Index Breakdown'"


def fill(c):
    return PatternFill("solid", start_color=c, end_color=c)


def font(size=10, bold=False, color="000000", italic=False):
    return Font(name=F, size=size, bold=bold, color=color, italic=italic)


def colour_formula(ref):
    return f'=IF({ref}="","",IF(ROUND({ref},0)>={R_},"RED",IF(ROUND({ref},0)>={G},"AMBER","GREEN")))'


def change_formula(sig, prev):
    rank = lambda ref: f'MATCH({ref},{{"GREEN","AMBER","RED"}},0)'
    return (f'=IF({sig}="","",IF({prev}="","new",IF({sig}={prev},"=",'
            f'IF({rank(sig)}>{rank(prev)},"▲ worse","▼ better"))))')


def title(ws, text, sub, ncol, c0=1):
    for r in (1, 2):
        for c in range(1, ncol + 1):
            ws.cell(r, c).fill = fill(NAVY)
    ws.cell(1, c0, text).font = Font(name="Times New Roman", size=18, bold=True, color=WHITE)
    ws.cell(2, c0, sub).font = font(10, color=WHITE)
    ws.row_dimensions[1].height = 30


def header(ws, row, cols, c0=1):
    for i, h in enumerate(cols):
        c = ws.cell(row, c0 + i, h)
        c.font = font(10, True, WHITE); c.fill = fill(BLUE); c.alignment = CENTER; c.border = BOX


def paint(cell, sig, size=10):
    if sig in FILL:
        bg, fg = FILL[sig]
        cell.fill = fill(bg); cell.font = font(size, True, fg)


def paint_change(cell, sig, prev, size=10):
    if prev not in SB.RANK:
        cell.font = font(size, True, VIOLET); return
    d = SB.RANK.get(sig, 0) - SB.RANK[prev]
    cell.font = font(size, d != 0, "9C0006" if d > 0 else "006100" if d < 0 else "5A6670")
    if d:
        cell.fill = fill("FDE9EA" if d > 0 else "E8F5EC")


def signal_cf(ws, rng):
    for k, (bg, fg) in FILL.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{k}"'], fill=fill(bg), font=font(10, True, fg)))


def merge_runs(ws, col, start, values, style_fn, label=lambda v: v):
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[i]:
            j += 1
        r0, r1 = start + i, start + j
        ws.cell(r0, col, label(values[i]))
        for r in range(r0, r1 + 1):
            style_fn(ws.cell(r, col))
        if r1 > r0:
            ws.merge_cells(start_row=r0, start_column=col, end_row=r1, end_column=col)
        i = j + 1


def stage_style(c):
    c.fill = fill(NAVY); c.font = font(10.5, True, WHITE); c.alignment = WRAP; c.border = BOX


def ind_style(c):
    c.fill = fill(BLUE); c.font = font(9.5, True, WHITE); c.alignment = WRAP; c.border = BOX


def lens_cell(c, lens):
    bg, fg = LENS_FILL[lens]
    c.value = LENS[lens]; c.fill = fill(bg); c.font = font(9.5, True, fg); c.alignment = CENTER; c.border = BOX


def stage_label(k):
    s = STAGE[k]
    return f"{s[1]} {s[2]}\n{s[3]}"


def method_note(ws, row, ncol, c0):
    W = SB.WEIGHTS
    lines = [
        ("Legend:  GREEN < 40 ≤ AMBER < 65 ≤ RED, on one 0-100 scale for every series, theme and stage.   "
         f"▲ worse / ▼ better = vs the {SB.PREV_ASOF} board.   Blue scores = judgement inputs you can edit.", True),
        (f"Series score: model series = percentile of its own history (real time); judgement series = GREEN {SB.JUDGEMENT_SCORE['GREEN']}, "
         f"AMBER {SB.JUDGEMENT_SCORE['AMBER']}, RED {SB.JUDGEMENT_SCORE['RED']}. Theme = weighted average (series passing the evidence test "
         f"{W['screened']}, other model series {W['context']}, judgement {W['judgement']}). Stage condition = average of its themes.", False),
        ("Condition describes how stretched each stage is today using everything tracked. Early warning is the tested model "
         "(only series that pass the out-of-sample test); adding untested series to it made its drawdown forecasts worse, "
         "so the two numbers are kept separate.", False),
    ]
    for k, (txt, b) in enumerate(lines):
        c = ws.cell(row + k, c0, txt); c.font = font(9, b, "000000" if b else "5A6670")
        ws.merge_cells(start_row=row + k, start_column=c0, end_row=row + k, end_column=ncol); c.alignment = WRAP
        ws.row_dimensions[row + k].height = 26
    c = ws.cell(row + 4, c0, "Sources: " + SB.SOURCES); c.font = font(8.5, italic=True, color="5A6670")
    ws.merge_cells(start_row=row + 4, start_column=c0, end_row=row + 4, end_column=ncol); c.alignment = WRAP
    ws.row_dimensions[row + 4].height = 36


# --------------------------------------------------------------------------- Detailed (inputs of the chain)
def build_detail(wb, U):
    ws = wb.create_sheet("Detailed Index Breakdown")
    cols = ["key", "Stage", "Theme", "Lens", "Underlying series", "Type", "Weight", "Score (0-100)", "Signal",
            "3m change", "Latest reading", "Note / what to watch", "As of"]
    title(ws, "Systemic Risk Monitoring Dashboard — Detailed Index Breakdown",
          f"Every series on one 0-100 scale · readings as of {SB.AS_OF} · grey italic = carried from an earlier update", len(cols), 2)
    first = 4
    header(ws, first - 1, cols)
    rows = [(t, r) for t in U["themes"] for r in t["rows"]]
    for i, (t, d) in enumerate(rows):
        r = first + i
        vals = {1: t["key"], 5: d["metric"], 6: TIER[d["tier"]], 7: d["weight"], 8: round(d["score"], 1),
                9: colour_formula(f"H{r}"), 10: d["d13"], 11: d["reading"], 12: d["note"], 13: d["asof"]}
        for c, v in vals.items():
            cell = ws.cell(r, c, v); cell.font = font(9.5); cell.border = BOX
            cell.alignment = CENTER if c in (6, 7, 8, 9, 10, 13) else WRAP
        ws.cell(r, 8).number_format = "0"
        if d["kind"] == "judgement":
            ws.cell(r, 8).font = font(9.5, True, "0000FF")          # editable input
        lens_cell(ws.cell(r, 4), t["lens"])
        paint(ws.cell(r, 9), d["signal"], 9.5)
        if not d["refreshed"]:
            ws.cell(r, 5).font = font(9.5, italic=True, color="808080")
        ws.row_dimensions[r].height = 40
    last = first + len(rows) - 1
    merge_runs(ws, 2, first, [t["stage"] for t, _ in rows], stage_style, stage_label)
    merge_runs(ws, 3, first, [t["key"] for t, _ in rows], ind_style, lambda k: next(x["theme"] for x in U["themes"] if x["key"] == k))
    signal_cf(ws, f"I{first}:I{last}")
    method_note(ws, last + 2, len(cols), 2)
    for col, w in zip("ABCDEFGHIJKLM", [8, 18, 26, 12, 30, 16, 8, 10, 9, 9, 62, 50, 16]):
        ws.column_dimensions[col].width = w
    ws.column_dimensions["A"].hidden = True
    ws.freeze_panes = f"F{first}"
    return first, last


# --------------------------------------------------------------------------- Summary
def build_summary(wb, U, det_rng):
    ws = wb.active
    ws.title = "Summary Dashboard"
    d0, d1 = det_rng
    K, W, S = (f"{DET}!${c}${d0}:${c}${d1}" for c in "AGH")
    title(ws, "Systemic Risk Monitoring Dashboard Summary",
          f"Fragility → Triggers → Amplifiers → Systemic threshold · broad system and AI channel · readings as of {SB.AS_OF}", 10, 3)
    themes = U["themes"]
    first = 15
    last = first + len(themes) - 1
    rng = lambda c: f"${c}${first}:${c}${last}"

    # ---- stage grid: C label, D-G stages, H overall
    ws.cell(4, 3, "Stage grid (0-100, one colour rule)").font = font(12, True)
    for j, s in enumerate(SB.STAGES):
        c = ws.cell(5, 4 + j, f"{s[1]} {s[2].upper()}"); c.font = font(10.5, True, WHITE); c.fill = fill(BLUE if j == 0 else NAVY); c.alignment = CENTER; c.border = BOX
        q = ws.cell(6, 4 + j, s[3]); q.font = font(9, True, BLUE, italic=True); q.alignment = CENTER; q.border = BOX
    c = ws.cell(5, 8, "OVERALL"); c.font = font(10.5, True, WHITE); c.fill = fill(NAVY); c.alignment = CENTER; c.border = BOX
    ws.cell(6, 8).border = BOX
    r = 7
    for lk, ln in SB.LENSES:
        lens_cell(ws.cell(r, 3), lk); ws.cell(r, 3).value = f"Condition: {ln}"
        lens_cell(ws.cell(r + 1, 3), lk); ws.cell(r + 1, 3).value = "signal"
        for j, s in enumerate(SB.STAGES):
            col = chr(ord("D") + j)
            c = ws.cell(r, 4 + j, f'=IFERROR(AVERAGEIFS({rng("E")},{rng("A")},"{s[0]}",{rng("B")},"{lk}"),"")')
            c.number_format = "0"; c.font = font(12, True); c.alignment = CENTER; c.border = BOX
            sg = ws.cell(r + 1, 4 + j, colour_formula(f"{col}{r}")); sg.alignment = CENTER; sg.border = BOX
            paint(sg, U["grid"][f"{s[0]}|{lk}"]["signal"], 10)
        c = ws.cell(r, 8, f"=AVERAGE(D{r}:G{r})"); c.number_format = "0"; c.font = font(12, True); c.alignment = CENTER; c.border = BOX
        sg = ws.cell(r + 1, 8, colour_formula(f"H{r}")); sg.alignment = CENTER; sg.border = BOX
        cond = U["condition"][lk]; paint(sg, SB.colour(cond), 10)
        signal_cf(ws, f"D{r + 1}:H{r + 1}")
        r += 2
    lab = ws.cell(r, 3, "Early warning (tested model)"); lab.font = font(9.5, True); lab.alignment = CENTER; lab.border = BOX
    for j, s in enumerate(SB.STAGES):
        e = U["early_warning"].get(s[0])
        c = ws.cell(r, 4 + j, None if not e else f"{e['score']:.0f} · {e['n']} series pass" + (" (thin)" if e["n"] < 2 else ""))
        c.font = font(9.5, True); c.alignment = CENTER; c.border = BOX
    ws.cell(r, 8).border = BOX
    if U.get("index") is not None:
        ws.cell(r, 8, f"{U['index']:.0f} · {U['index_level']}").font = font(9.5, True); ws.cell(r, 8).alignment = CENTER
    if not U["early_warning"]:
        ws.cell(r, 4, "model results not available in this build").font = font(9, italic=True, color="5A6670")

    # ---- theme table (A-B hidden keys)
    cols = ["stage", "lens", "Stage", "Lens", "Score (0-100)", "Signal", f"Signal {SB.PREV_ASOF}", "Change", "Theme", "Comment"]
    header(ws, first - 1, cols)
    for i, t in enumerate(themes):
        r = first + i
        ws.cell(r, 1, t["stage"]); ws.cell(r, 2, t["lens"])
        ws.cell(r, 5, f'=IFERROR(SUMPRODUCT(({K}=$K{r})*{W}*{S})/SUMIFS({W},{K},$K{r}),"")')
        ws.cell(r, 6, colour_formula(f"E{r}")); ws.cell(r, 7, t["prev"] or None)
        ws.cell(r, 8, change_formula(f"F{r}", f"G{r}")); ws.cell(r, 9, t["theme"]); ws.cell(r, 10, t["comment"]); ws.cell(r, 11, t["key"])
        for c in range(5, 11):
            cell = ws.cell(r, c); cell.font = font(10); cell.border = BOX
            cell.alignment = CENTER if c in (5, 6, 7, 8) else WRAP
        ws.cell(r, 5).number_format = "0"; ws.cell(r, 9).font = font(10, True)
        lens_cell(ws.cell(r, 4), t["lens"])
        paint(ws.cell(r, 6), t["signal"]); paint(ws.cell(r, 7), t["prev"]); paint_change(ws.cell(r, 8), t["signal"], t["prev"])
        ws.row_dimensions[r].height = 32
    merge_runs(ws, 3, first, [t["stage"] for t in themes], stage_style, stage_label)
    signal_cf(ws, f"F{first}:G{last}")
    method_note(ws, last + 2, 10, 3)
    for col, w in zip("ABCDEFGHIJK", [8, 8, 26, 15, 15, 15, 15, 15, 46, 90, 8]):
        ws.column_dimensions[col].width = w
    for col in "ABK":
        ws.column_dimensions[col].hidden = True
    ws.freeze_panes = f"E{first}"


def build_model(wb, R):
    from sysrisk.report import Story
    st = Story(R)
    ws = wb.create_sheet("Model Scores")
    cols = ["Stage", "Series", "Reading", "Score (0-100)", "Change over 3 months", "In the early-warning model?"]
    title(ws, "Model series by stage", f"Data to {st.asof:%d %b %Y} · 0 = calmest week on record, 100 = most dangerous", len(cols))
    header(ws, 3, cols)
    r = 4
    for s in SB.STAGES:
        L = st.link(s[4])
        top = ws.cell(r, 1, f"{s[1]} {s[2]}: early-warning score {L['score']:.0f} ({L['level']}) · {L['head']}")
        top.font = font(10, True, WHITE); top.fill = fill(NAVY); top.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(cols)); ws.row_dimensions[r].height = 30
        r += 1
        for row in L["rows"]:
            vals = [s[2], row["name"], "not available in free data" if row.get("missing") else row.get("reading"),
                    None if row.get("missing") or row.get("score") is None else round(row["score"]),
                    None if row.get("missing") or row.get("d13") is None else round(row["d13"]),
                    "gap" if row.get("missing") else ("yes" if row.get("scored") else "no (context)")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(r, c, v); cell.font = font(9.5); cell.border = BOX; cell.alignment = WRAP
            r += 1
    for col, w in zip("ABCDEF", [20, 46, 60, 14, 14, 18]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C4"


def build_sources(wb, U):
    ws = wb.create_sheet("Sources & Codes")
    cols = ["Stage", "Lens", "Theme", "Underlying series", "Type", "Source", "Data as of", "Refresh code", "Refreshed this update?"]
    title(ws, "Sources, data dates and refresh codes", "Model series refresh daily via GitHub Actions; judgement series via the daily analyst task; Bloomberg codes need a Terminal session", len(cols))
    header(ws, 3, cols)
    row = 4
    for t in U["themes"]:
        for d in t["rows"]:
            vals = [STAGE[t["stage"]][2], LENS[t["lens"]], t["theme"], d["metric"], TIER[d["tier"]], d["source"], d["asof"], d["code"],
                    "Yes" if d["refreshed"] else "No - carried"]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row, c, v)
                cell.font = font(9.5, color="9C0006" if (c == 9 and not d["refreshed"]) else "000000"); cell.border = BOX; cell.alignment = WRAP
            row += 1
    for col, w in zip("ABCDEFGHI", [16, 12, 30, 30, 16, 50, 18, 30, 14]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "E4"


def print_setup(ws):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


def build(out, results=None):
    R = None
    if results and Path(results).exists():
        with open(results, "rb") as f:
            R = pickle.load(f)
    U = unified.evaluate(R)
    if R is not None:
        x = R["index"].dropna()
        from sysrisk.report import level_of
        U["index"], U["index_level"] = float(x.iloc[-1]), level_of(float(x.iloc[-1]))
    wb = Workbook()
    det = build_detail(wb, U)
    build_summary(wb, U, det)
    if R is not None:
        build_model(wb, R)
    build_sources(wb, U)
    for ws in wb.worksheets:
        print_setup(ws)
    wb.active = 0
    wb.save(out)
    print("wrote", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Systemic_Risk_Dashboard.xlsx")
    ap.add_argument("--results", default=None, help="output/results.pkl from the pipeline, adds model series")
    a = ap.parse_args()
    build(a.out, a.results)
