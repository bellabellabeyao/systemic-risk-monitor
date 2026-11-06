"""
Build the Systemic Risk Monitoring Dashboard workbook (Summary + Detailed Index Breakdown + Sources)
from sysrisk/signal_board.py, the same data the website section uses.

    python tools/build_signal_board_xlsx.py --out Systemic_Risk_Dashboard.xlsx
"""
import argparse
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sysrisk import signal_board as SB  # noqa: E402

NAVY, BLUE, WHITE = "1B1E3C", "1F3BFF", "FFFFFF"
FILL = {"GREEN": ("C6EFCE", "006100"), "AMBER": ("FFEB9C", "7F6000"), "RED": ("FFC7CE", "9C0006")}
F = "Arial"
thin = Side(style="thin", color="B7BEC9")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical="center")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def fill(c):
    return PatternFill("solid", start_color=c, end_color=c)


def title(ws, text, sub, ncol):
    for r in (1, 2):
        for c in range(1, ncol + 1):
            ws.cell(r, c).fill = fill(NAVY)
    ws["A1"] = text
    ws["A1"].font = Font(name="Times New Roman", size=18, bold=True, color=WHITE)
    ws["A2"] = sub
    ws["A2"].font = Font(name=F, size=10, color=WHITE)
    ws.row_dimensions[1].height = 30


def header(ws, row, cols):
    for i, h in enumerate(cols, 1):
        c = ws.cell(row, i, h)
        c.font = Font(name=F, bold=True, color=WHITE, size=10)
        c.fill = fill(BLUE)
        c.alignment = CENTER
        c.border = BOX


def change_formula(sig, prev):
    """Direction vs the prior reading, computed in-sheet so it updates if a signal is edited."""
    rank = lambda ref: f'MATCH({ref},{{"GREEN","AMBER","RED"}},0)'
    return (f'=IF(OR({sig}="",{prev}=""),"",IF({sig}={prev},"=",'
            f'IF({rank(sig)}>{rank(prev)},"▲ worse","▼ better")))')


RANK = {"GREEN": 0, "AMBER": 1, "RED": 2}


def paint(cell, sig, prev=None):
    """Static colours (shown in every viewer, incl. previews that ignore conditional formatting)."""
    if sig in FILL:
        bg, fg = FILL[sig]
        cell.fill = fill(bg)
        cell.font = Font(name=F, bold=True, color=fg, size=cell.font.size or 10)


def paint_change(cell, sig, prev):
    d = RANK.get(sig, 0) - RANK.get(prev, 0)
    col = "9C0006" if d > 0 else "006100" if d < 0 else "5A6670"
    cell.font = Font(name=F, bold=d != 0, color=col, size=cell.font.size or 10)
    if d > 0:
        cell.fill = fill("FDE9EA")
    elif d < 0:
        cell.fill = fill("E8F5EC")


def signal_cf(ws, rng):
    for k, (bg, fg) in FILL.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{k}"'],
                                                      fill=fill(bg), font=Font(name=F, bold=True, color=fg)))


def change_cf(ws, rng):
    first = rng.split(":")[0]
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'LEFT({first},1)="▲"'], font=Font(name=F, bold=True, color="9C0006")))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'LEFT({first},1)="▼"'], font=Font(name=F, bold=True, color="006100")))


def merge_runs(ws, col, start, values, style_fn):
    """Merge consecutive equal values in a column (risk group / indicator blocks)."""
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[i]:
            j += 1
        r0, r1 = start + i, start + j
        ws.cell(r0, col, values[i])
        for r in range(r0, r1 + 1):
            style_fn(ws.cell(r, col))
        if r1 > r0:
            ws.merge_cells(start_row=r0, start_column=col, end_row=r1, end_column=col)
        i = j + 1


def group_style(c):
    c.fill = fill(NAVY); c.font = Font(name=F, bold=True, color=WHITE, size=10.5); c.alignment = WRAP; c.border = BOX


def ind_style(c):
    c.fill = fill(BLUE); c.font = Font(name=F, bold=True, color=WHITE, size=9.5); c.alignment = WRAP; c.border = BOX


def legend(ws, row, ncol):
    ws.cell(row, 1, "Legend:  GREEN = benign / low stress     AMBER = elevated / watch     RED = stretched / acute risk"
            "     ▲ worse / ▼ better = change vs " + SB.PREV_ASOF).font = Font(name=F, bold=True, size=9.5)
    ws.cell(row + 2, 1, "Sources: " + SB.SOURCES).font = Font(name=F, italic=True, size=8.5, color="5A6670")
    ws.merge_cells(start_row=row + 2, start_column=1, end_row=row + 2, end_column=ncol)
    ws.cell(row + 2, 1).alignment = WRAP
    ws.row_dimensions[row + 2].height = 36


def build_summary(wb):
    ws = wb.active
    ws.title = "Summary Dashboard"
    cols = ["Risk group", "Indicator", "Signal", f"Signal {SB.PREV_ASOF}", "Change", "Latest reading / comment"]
    title(ws, "Systemic Risk Monitoring Dashboard Summary", f"readings as of {SB.AS_OF}  ·  prior readings {SB.PREV_ASOF}", len(cols))

    # scoreboard (formulas over the table below)
    n = len(SB.SUMMARY)
    top, first = 4, 10
    last = first + n - 1
    ws.cell(top, 2, "Signal count").font = Font(name=F, bold=True, size=10)
    ws.cell(top, 3, "Now").font = Font(name=F, bold=True, size=10)
    ws.cell(top, 4, SB.PREV_ASOF).font = Font(name=F, bold=True, size=10)
    for k, s in enumerate(["RED", "AMBER", "GREEN"]):
        r = top + 1 + k
        ws.cell(r, 2, s).font = Font(name=F, size=10)
        ws.cell(r, 3, f'=COUNTIF($C${first}:$C${last},B{r})').font = Font(name=F, size=10)
        ws.cell(r, 4, f'=COUNTIF($D${first}:$D${last},B{r})').font = Font(name=F, size=10)
        for c in (2, 3, 4):
            ws.cell(r, c).border = BOX
            ws.cell(r, c).alignment = CENTER
        paint(ws.cell(r, 2), s)
    signal_cf(ws, f"B{top+1}:B{top+3}")
    ws.cell(top + 1, 6, f'=COUNTIF($E${first}:$E${last},"▲*")&" indicators worse, "&COUNTIF($E${first}:$E${last},"▼*")&" better since {SB.PREV_ASOF}"').font = Font(name=F, bold=True, size=10.5)

    header(ws, first - 1, cols)
    for i, (g, ind, sig, prev, com) in enumerate(SB.SUMMARY):
        r = first + i
        ws.cell(r, 2, ind); ws.cell(r, 3, sig); ws.cell(r, 4, prev)
        ws.cell(r, 5, change_formula(f"C{r}", f"D{r}")); ws.cell(r, 6, com)
        for c in range(2, 7):
            cell = ws.cell(r, c)
            cell.font = Font(name=F, size=10); cell.border = BOX
            cell.alignment = CENTER if c in (3, 4, 5) else WRAP
        paint(ws.cell(r, 3), sig); paint(ws.cell(r, 4), prev); paint_change(ws.cell(r, 5), sig, prev)
        ws.row_dimensions[r].height = 30
    merge_runs(ws, 1, first, [r[0] for r in SB.SUMMARY], group_style)
    signal_cf(ws, f"C{first}:D{last}")
    change_cf(ws, f"E{first}:E{last}")
    legend(ws, last + 2, len(cols))
    for col, w in zip("ABCDEF", [30, 62, 10, 13, 11, 120]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = f"C{first}"
    ws.sheet_view.zoomScale = 90


def build_detail(wb):
    ws = wb.create_sheet("Detailed Index Breakdown")
    cols = ["Risk group", "Indicator", "Underlying index / metric", "Signal", f"Signal {SB.PREV_ASOF}", "Change",
            "Latest reading / comment", "Note / what to watch", "As of"]
    title(ws, "Systemic Risk Monitoring Dashboard — Detailed Index Breakdown",
          f"Each indicator expanded into its underlying trackable indices · readings as of {SB.AS_OF} · "
          "grey italic metric = carried from prior update, needs a fresh print", len(cols))
    first = 4
    header(ws, first - 1, cols)
    rows = SB.DETAIL
    last = first + len(rows) - 1
    for i, (g, ind, m, sig, prev, rd, note, src, asof, code, ref) in enumerate(rows):
        r = first + i
        vals = [None, None, m, sig, prev, change_formula(f"D{r}", f"E{r}"), rd, note, asof]
        for c, v in enumerate(vals, 1):
            if c <= 2:
                continue
            cell = ws.cell(r, c, v)
            cell.font = Font(name=F, size=9.5); cell.border = BOX
            cell.alignment = CENTER if c in (4, 5, 6, 9) else WRAP
        ws.cell(r, 4).font = Font(name=F, size=9.5); ws.cell(r, 5).font = Font(name=F, size=9.5)
        paint(ws.cell(r, 4), sig); paint(ws.cell(r, 5), prev); paint_change(ws.cell(r, 6), sig, prev)
        if not ref:
            ws.cell(r, 3).font = Font(name=F, size=9.5, italic=True, color="808080")
        ws.row_dimensions[r].height = 40
    merge_runs(ws, 1, first, [r[0] for r in rows], group_style)
    merge_runs(ws, 2, first, [r[0] + "|" + r[1] for r in rows], ind_style)
    for r in range(first, last + 1):   # strip group prefix used for unique runs
        v = ws.cell(r, 2).value
        if isinstance(v, str) and "|" in v:
            ws.cell(r, 2).value = v.split("|", 1)[1]
    signal_cf(ws, f"D{first}:E{last}")
    change_cf(ws, f"F{first}:F{last}")
    legend(ws, last + 2, len(cols))
    for col, w in zip("ABCDEFGHI", [24, 26, 30, 9, 12, 10, 78, 62, 12]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = f"D{first}"
    ws.sheet_view.zoomScale = 90


def build_sources(wb):
    ws = wb.create_sheet("Sources & Codes")
    cols = ["Risk group", "Underlying index / metric", "Source used for this reading", "Data as of",
            "Code for refresh (FRED / Bloomberg / overlay)", "Refreshed this update?"]
    title(ws, "Sources, data dates and refresh codes",
          "Bloomberg tickers marked (verify) should be checked on the Terminal before automating", len(cols))
    header(ws, 3, cols)
    for i, r in enumerate(SB.DETAIL):
        row = 4 + i
        for c, v in enumerate([r[0], r[2], r[7], r[8], r[9], "Yes" if r[10] else "No - carried"], 1):
            cell = ws.cell(row, c, v)
            cell.font = Font(name=F, size=9.5, color="9C0006" if (c == 6 and not r[10]) else "000000")
            cell.border = BOX; cell.alignment = WRAP
    for col, w in zip("ABCDEF", [30, 34, 52, 14, 44, 16]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C4"


def print_setup(ws):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Systemic_Risk_Dashboard.xlsx")
    a = ap.parse_args()
    wb = Workbook()
    build_summary(wb); build_detail(wb); build_sources(wb)
    for ws in wb.worksheets:
        print_setup(ws)
    wb.save(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
