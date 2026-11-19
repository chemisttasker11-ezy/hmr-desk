"""Result column keeps long and qualified values whole (no mid-word split, no truncation)."""
from docx import Document
from docx.oxml.ns import qn

import local_report_builder as builder

VALUES = ["<0.01", "\u2265 1000", "> 12.5 (H)", "68 (borderline)", "1234567.89", "12.5-14.0 (est)", "Not detected / <LOD", "HbA1c 53 mmol/mol"]


def _data(values):
    return dict(name="S", assess_date="2026-11-17", report_date="17/11/2026", patient="Synthetic Patient", doctor="Dr Example GP",
                dear="Dear Dr,", thanks="t", reason="r", intro="i", conditions="c", allergies="a", obs="o",
                meds=[["m", "d", "c", "r"]], otc=[["o", "a", "c"]], ceased=[["c", "d", "n"]],
                path=[["T%d" % i, v, "mL/min/1.73m2", "> 60", "Synthetic source"] for i, v in enumerate(values)],
                path_date="2026-11-17", issues=[{"title": "f", "rec": "r", "rationale": "x"}], followup="f")


def _table(tmp_path, values):
    target = tmp_path / "r.docx"
    builder.render(_data(values), target)
    return next(t for t in Document(target).tables if t.rows[0].cells[0].text == "Test")


def _grid(t):
    return [int(c.get(qn('w:w'))) for c in t._tbl.tblGrid.findall(qn('w:gridCol'))]


def test_values_preserved_exactly_including_comparators(tmp_path):
    assert [r.cells[1].text for r in _table(tmp_path, VALUES).rows[1:]] == VALUES


def test_reference_grid_unchanged_for_short_values(tmp_path):
    assert _grid(_table(tmp_path, ["68", "< 5", "> 12.5"])) == [1885, 1105, 1870, 1620, 3820]


def test_result_column_widens_for_long_tokens_and_total_and_floor_hold(tmp_path):
    grid = _grid(_table(tmp_path, VALUES))
    assert grid[1] > 1105 and sum(grid) == 10300 and grid[4] >= 2325 and grid[2] >= 1800
