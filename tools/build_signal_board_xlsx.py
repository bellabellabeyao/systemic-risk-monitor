"""
Build the Systemic Risk Monitor workbook from the same data as the website.

Sheets
  Summary Dashboard          4-stage x 2-lens grid (formula roll-up) + headline indicators
  Detailed Index Breakdown   every underlying series with reading, what to watch, as-of date
  Model Scores               the model's stage scores and indicator scores (only with --results)
  Sources & Codes            source, data date and refresh code per series

    python tools/build_signal_board_xlsx.py --out Systemic_Risk_Dashboard.xlsx [--results output/results.pkl]
"""
import argparse
import pickle
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sysrisk import signal_board as SB  # noqa: E402

NAVY, BLUE, WHITE, VIOLET = "1B1E3C", "1F3BFF", "FFFFFF", "5B3E96"
FILL = {"GREEN": ("C6EFCE", "006100"), "AMBER": ("FFEB9C", "7F6000"), "RED": ("FFC7CE", "9C0006")}
LENS_FILL = {"broad": ("E8ECF7", "1B1E3C"), "ai": ("EEE8F7", VIOLET)}
F = "Arial"
thin = Side(style="thin", color="B7BEC9")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical="center")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
STAGE = {s[0]: s for s in SB.STAGES}
LENS = dict(SB.LENSES)


def fill(c):
    return PatternFill("solid", start_color=c, end_color=c)


def font(size=10, bold=False, color="000000", italic=False):
    return Font(name=F, size=size, bold=bold, color=color, italic=italic)


def title(ws, text, sub, ncol):
    for r in (1, 2):
        for c in range(1, ncol + 1):
            ws.cell(r, c).fill = fill(NAVY)
    ws["A1"] = text
    ws["A1"].font = Font(name="Times New Roman", size=18, bold=True, color=WHITE)
    ws["A2"] = sub
    ws["A2"].font = font(10, color=WHITE)
    ws.row_dimensions[1].height = 30


def header(ws, row, cols):
    for i, h in enumerate(cols, 1):
        c = ws.cell(row, i, h)
        c.font = font(10, True, WHITE); c.fill = fill(BLUE); c.alignment = CENTER; c.border = BOX


def paint(cell, sig, size=10):
    if sig in FILL:
        bg, fg = FILL[sig]
        cell.fill = fill(bg); cell.font = font(size, True, fg)


def paint_change(cell, sig, prev, size=10):
    if prev not in SB.RANK:
        cell.font = font(size, True, VIOLET); return
    d = SB.RANK[sig] - SB.RANK[prev]
    cell.font = font(size, d != 0, "9C0006" if d > 0 else "006100" if d < 0 else "5A6670")
    if d:
        cell.fill = fill("FDE9EA" if d > 0 else "E8F5EC")


def change_formula(sig, prev):
    rank = lambda ref: f'MATCH({ref},{{"GREEN","AMBER","RED"}},0)'
    return (f'=IF({sig}="","",IF({prev}="","new",IF({sig}={prev},"=",'
            f'IF({rank(sig)}>{rank(prev)},"▲ worse","▼ better"))))')


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


def legend(ws, row, ncol, c0=1):
    ws.cell(row, c0, "Legend:  GREEN = benign / low stress     AMBER = elevated / watch     RED = stretched / acute risk"
            f"     ▲ worse / ▼ better = change vs {SB.PREV_ASOF}     new = not tracked at {SB.PREV_ASOF}").font = font(9.5, True)
    ws.cell(row + 1, c0, "Roll-up rule: average of indicator signals (GREEN 0, AMBER 1, RED 2); RED if 1.5 or more, AMBER if 0.75 or more."
            " Signals are judgement and do not feed the model score.").font = font(9, color="5A6670")
    ws.cell(row + 3, c0, "Sources: " + SB.SOURCES).font = font(8.5, italic=True, color="5A6670")
    ws.merge_cells(start_row=row + 3, start_column=c0, end_row=row + 3, end_column=ncol)
    ws.cell(row + 3, c0).alignment = WRAP
    ws.row_dimensions[row + 3].height = 36


def build_summary(wb, model=None):
    """Columns A-B hold hidden stage/lens keys that the grid formulas count on; C onwards is what readers see."""
    ws = wb.active
    ws.title = "Summary Dashboard"
    rows = SB.SUMMARY
    first = 14
    last = first + len(rows) - 1
    rng = lambda col: f"${col}${first}:${col}${last}"
    title(ws, "Systemic Risk Monitoring Dashboard Summary",
          f"Fragility → Triggers → Amplifiers → Systemic threshold, for the broad system and the AI channel · readings as of {SB.AS_OF}", 9)

    # ---- stage grid (C = row label, D-G = stages)
    ws.cell(4, 3, "Stage grid").font = font(12, True)
    ws.cell(4, 4, "Signal = roll-up of the indicators below (formula)" + ("; model score from the evidence-screened index" if model else "")).font = font(9, color="5A6670")
    P = SB.payload()
    for j, s in enumerate(SB.STAGES):
        c = ws.cell(5, 4 + j, f"{s[1]} {s[2].upper()}"); c.font = font(10.5, True, WHITE); c.fill = fill(BLUE if j == 0 else NAVY); c.alignment = CENTER; c.border = BOX
        q = ws.cell(6, 4 + j, s[3]); q.font = font(9, True, "1F3BFF", italic=True); q.alignment = CENTER; q.border = BOX
    for i, (lk, ln) in enumerate(SB.LENSES):
        r = 7 + i
        lens_cell(ws.cell(r, 3), lk)
        for j, s in enumerate(SB.STAGES):
            cnt = lambda extra="": f'COUNTIFS({rng("A")},"{s[0]}",{rng("B")},"{lk}"{extra})'
            n, red, amb = cnt(), cnt(f',{rng("F")},"RED"'), cnt(f',{rng("F")},"AMBER"')
            m = f"(2*{red}+{amb})/{n}"
            c = ws.cell(r, 4 + j, f'=IF({n}=0,"",IF({m}>=1.5,"RED",IF({m}>=0.75,"AMBER","GREEN")))')
            c.alignment = CENTER; c.border = BOX
            paint(c, P["grid"][f"{s[0]}|{lk}"]["now"], 11)
        ws.row_dimensions[r].height = 26
    signal_cf(ws, "D7:G8")
    if model:
        lab = ws.cell(9, 3, "Model score"); lab.font = font(9.5, True); lab.alignment = CENTER; lab.border = BOX
        for j, s in enumerate(SB.STAGES):
            m = model.get(s[4])
            c = ws.cell(9, 4 + j, None if m is None else f"{m['score']:.0f} / 100 · {m['level']}")
            c.font = font(10, True); c.alignment = CENTER; c.border = BOX
        ws.cell(10, 3, "Model score: 0 = calmest week on record, 100 = most dangerous. Detail in the Model Scores sheet.").font = font(8.5, color="5A6670")

    # ---- headline table
    cols = ["stage", "lens", "Stage", "Lens", "Indicator", "Signal", f"Signal {SB.PREV_ASOF}", "Change", "Latest reading / comment"]
    header(ws, first - 1, cols)
    st_order = [s[0] for s in SB.STAGES]
    order = sorted(rows, key=lambda r: (st_order.index(r[1]), r[2] != "broad"))
    for i, (key, stage, lens, ind, sig, prev, com) in enumerate(order):
        r = first + i
        ws.cell(r, 1, stage); ws.cell(r, 2, lens)
        ws.cell(r, 5, ind); ws.cell(r, 6, sig); ws.cell(r, 7, prev or None)
        ws.cell(r, 8, change_formula(f"F{r}", f"G{r}")); ws.cell(r, 9, com)
        for c in range(5, 10):
            cell = ws.cell(r, c); cell.font = font(10); cell.border = BOX
            cell.alignment = CENTER if c in (6, 7, 8) else WRAP
        lens_cell(ws.cell(r, 4), lens)
        paint(ws.cell(r, 6), sig); paint(ws.cell(r, 7), prev); paint_change(ws.cell(r, 8), sig, prev)
        ws.row_dimensions[r].height = 32
    merge_runs(ws, 3, first, [r[1] for r in order], stage_style, stage_label)
    signal_cf(ws, f"F{first}:G{last}")
    legend(ws, last + 2, 9, c0=3)
    for col, w in zip("ABCDEFGHI", [8, 8, 24, 13, 50, 10, 13, 10, 105]):
        ws.column_dimensions[col].width = w
    ws.column_dimensions["A"].hidden = True
    ws.column_dimensions["B"].hidden = True
    ws.freeze_panes = f"F{first}"


def build_detail(wb):
    ws = wb.create_sheet("Detailed Index Breakdown")
    cols = ["Stage", "Indicator", "Lens", "Underlying index / metric", "Signal", f"Signal {SB.PREV_ASOF}", "Change",
            "Latest reading / comment", "Note / what to watch", "As of"]
    title(ws, "Systemic Risk Monitoring Dashboard — Detailed Index Breakdown",
          f"Each indicator expanded into its underlying trackable series · readings as of {SB.AS_OF} · "
          "grey italic metric = carried from an earlier update, needs a fresh print", len(cols))
    first = 4
    header(ws, first - 1, cols)
    by_key = {r[0]: r for r in SB.SUMMARY}
    st_order = [s[0] for s in SB.STAGES]
    rows = sorted(SB.DETAIL, key=lambda d: (st_order.index(by_key[d[0]][1]), by_key[d[0]][2] != "broad",
                                            [r[0] for r in SB.SUMMARY].index(d[0])))
    last = first + len(rows) - 1
    for i, (key, m, sig, prev, rd, note, src, asof, code, ref) in enumerate(rows):
        r = first + i
        _, stage, lens, ind, *_ = by_key[key]
        vals = {4: m, 5: sig, 6: prev or None, 7: change_formula(f"E{r}", f"F{r}"), 8: rd, 9: note, 10: asof}
        for c, v in vals.items():
            cell = ws.cell(r, c, v); cell.font = font(9.5); cell.border = BOX
            cell.alignment = CENTER if c in (5, 6, 7, 10) else WRAP
        lens_cell(ws.cell(r, 3), lens)
        paint(ws.cell(r, 5), sig, 9.5); paint(ws.cell(r, 6), prev, 9.5); paint_change(ws.cell(r, 7), sig, prev, 9.5)
        if not ref:
            ws.cell(r, 4).font = font(9.5, italic=True, color="808080")
        ws.row_dimensions[r].height = 42
    merge_runs(ws, 1, first, [by_key[d[0]][1] for d in rows], stage_style, stage_label)
    merge_runs(ws, 2, first, [d[0] for d in rows], ind_style, lambda k: by_key[k][3])
    signal_cf(ws, f"E{first}:F{last}")
    legend(ws, last + 2, len(cols))
    for col, w in zip("ABCDEFGHIJ", [20, 26, 12, 28, 9, 12, 9, 72, 58, 12]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = f"E{first}"


def build_model(wb, R):
    from sysrisk.report import Story, apply_screen_flags
    apply_screen_flags(R)
    st = Story(R)
    ws = wb.create_sheet("Model Scores")
    cols = ["Stage", "Indicator", "Reading", "Risk score (0-100)", "Change over 3 months", "In the score?"]
    title(ws, "Model scores by stage", f"Evidence-screened model · data to {st.asof:%d %b %Y} · 0 = calmest week on record, 100 = most dangerous", len(cols))
    header(ws, 3, cols)
    r = 4
    for s in SB.STAGES:
        L = st.link(s[4])
        top = ws.cell(r, 1, f"{s[1]} {s[2]}: {L['score']:.0f} ({L['level']}), {L['d13']:+.0f} over 3 months · {L['head']}")
        top.font = font(10, True, WHITE); top.fill = fill(NAVY); top.alignment = WRAP
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(cols)); ws.row_dimensions[r].height = 30
        r += 1
        for row in L["rows"]:
            vals = [s[2], row["name"], "not available in free data" if row.get("missing") else row.get("reading"),
                    None if row.get("missing") or row.get("score") is None else round(row["score"]),
                    None if row.get("missing") or row.get("d13") is None else round(row["d13"]),
                    "gap" if row.get("missing") else ("yes" if row.get("scored") else "context")]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(r, c, v); cell.font = font(9.5); cell.border = BOX; cell.alignment = WRAP
            r += 1
    for col, w in zip("ABCDEF", [20, 46, 60, 14, 14, 12]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C4"
    return {s[4]: (lambda L: {"score": L["score"], "level": L["level"]})(st.link(s[4])) for s in SB.STAGES}


def build_sources(wb):
    ws = wb.create_sheet("Sources & Codes")
    cols = ["Stage", "Lens", "Underlying index / metric", "Source used for this reading", "Data as of",
            "Code for refresh (FRED / Bloomberg / overlay)", "Refreshed this update?"]
    title(ws, "Sources, data dates and refresh codes", "Bloomberg codes need a Terminal session; all others refresh automatically", len(cols))
    header(ws, 3, cols)
    by_key = {r[0]: r for r in SB.SUMMARY}
    for i, d in enumerate(SB.DETAIL):
        row = 4 + i
        k = by_key[d[0]]
        vals = [STAGE[k[1]][2], LENS[k[2]], d[1], d[6], d[7], d[8], "Yes" if d[9] else "No - carried"]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row, c, v)
            cell.font = font(9.5, color="9C0006" if (c == 7 and not d[9]) else "000000"); cell.border = BOX; cell.alignment = WRAP
    for col, w in zip("ABCDEFG", [18, 13, 32, 50, 14, 40, 16]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "D4"


def print_setup(ws):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


def build(out, results=None):
    wb = Workbook()
    model = None
    if results and Path(results).exists():
        with open(results, "rb") as f:
            R = pickle.load(f)
        tmp = Workbook()
        model = build_model(tmp, R)          # compute scores first so the summary grid can show them
        build_summary(wb, model); build_detail(wb); build_model(wb, R)
    else:
        build_summary(wb); build_detail(wb)
    build_sources(wb)
    for ws in wb.worksheets:
        print_setup(ws)
    wb.save(out)
    print("wrote", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Systemic_Risk_Dashboard.xlsx")
    ap.add_argument("--results", default=None, help="output/results.pkl from the pipeline, adds model scores")
    a = ap.parse_args()
    build(a.out, a.results)
