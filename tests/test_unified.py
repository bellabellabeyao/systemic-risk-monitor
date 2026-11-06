"""Checks for the unified evaluation: one scale, one colour rule, no model results needed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sysrisk import signal_board as SB
from sysrisk.unified import evaluate


def test_colour_bands():
    assert SB.colour(39.4) == "GREEN" and SB.colour(39.6) == "AMBER" and SB.colour(64.6) == "RED"


def test_judgement_scores_keep_their_colour():
    assert all(SB.colour(v) == k for k, v in SB.JUDGEMENT_SCORE.items())


def test_evaluate_without_model():
    U = evaluate(None)
    assert U["themes"] and all(t["score"] is None or 0 <= t["score"] <= 100 for t in U["themes"])
    for t in U["themes"]:
        assert t["signal"] == SB.colour(t["score"])


if __name__ == "__main__":
    for f in [test_colour_bands, test_judgement_scores_keep_their_colour, test_evaluate_without_model]:
        f(); print("PASS", f.__name__)
