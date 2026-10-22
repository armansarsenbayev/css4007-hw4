"""Tests for lookup and calculate. No API key needed."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import calculate, lookup, run_tool  # noqa: E402


# ----------------------------- lookup -----------------------------------

def test_lookup_finds_2025_population():
    r = lookup("Millbrook", "population")
    assert r["value"] == 37203 and r["year"] == 2025 and r["source"] == "NR-11"
    assert "37,203" in r["evidence"]


def test_lookup_2020_population():
    assert lookup("Tarnvale", "population", 2020)["value"] == 67214


def test_lookup_misspelled_name_suggests_but_does_not_guess():
    r = lookup("Ossbrige", "population")
    assert "error" in r and "value" not in r
    assert "Ossbridge" in r["error"]


def test_lookup_similar_names_are_kept_apart():
    assert lookup("Ossbridge", "population")["value"] == 52904
    assert lookup("Ossford", "population")["value"] == 30982
    assert lookup("Ossbridge", "area_km2")["source"] == "NR-01"
    assert lookup("Ossford", "area_km2")["source"] == "NR-02"


def test_lookup_ambiguous_prefix_is_an_error():
    r = lookup("Oss", "population")
    assert "ambiguous" in r["error"] and "Ossbridge" in r["error"] and "Ossford" in r["error"]


@pytest.mark.parametrize("district,field,current,archived", [
    ("Tarnvale", "population", 71388, 65030),
    ("Tarnvale", "water_use_megalitres", 5207, 4980),
    ("Kelmarsh", "schools", 11, 10),
    ("Kelmarsh", "pupils", 3268, 2944),
])
def test_lookup_ignores_archived_profiles(district, field, current, archived):
    r = lookup(district, field)
    assert r["value"] == current and r["value"] != archived
    assert r["source"] not in ("NR-13", "NR-14")


def test_lookup_refuses_archived_year():
    assert "error" in lookup("Tarnvale", "population", 2019)


def test_lookup_applies_correction_notice():
    r = lookup("Brightwater", "area_km2")
    assert r["value"] == 921.4 and r["source"] == "NR-16"
    assert "912.4" in r["note"]


def test_lookup_converts_cubic_metres_to_megalitres():
    r = lookup("Lindenmoor", "water_use_megalitres")
    assert r["value"] == pytest.approx(2151.4) and r["unit"] == "megalitres"
    assert "converted" in r["note"]


def test_lookup_water_tariff():
    assert lookup(field="water_tariff_tenge_per_m3")["value"] == 142.35
    assert lookup(field="water_tariff_tenge_per_m3", year=2024)["value"] == 131.80


def test_lookup_bad_inputs_never_crash():
    for args in [("Brightwater", "density"), (None, "population"), (123, "population"),
                 ("x" * 10000, "population"), ("Brightwater", "area_km2", 2020),
                 ("Brightwater", "population", "2025")]:
        r = lookup(*args)
        assert "error" in r


def test_lookup_result_is_short():
    for f in ["population", "area_km2", "water_use_megalitres", "pupils"]:
        assert len(str(lookup("Harrowfield", f))) < 600


# ---------------------------- calculate ---------------------------------

def test_calculate_multiplication():
    assert calculate("48317 * 1.0947")["result"] == pytest.approx(52892.6199)


def test_calculate_q09_expression():
    r = calculate("37203/758.6 - 44675/921.4")
    assert r["result"] == pytest.approx(0.55566, abs=1e-4)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",
    "(1).__class__",
    "9**9**9",
])
def test_calculate_refuses_dangerous_input_quickly(expr, capfd):
    start = time.perf_counter()
    r = calculate(expr)
    assert "error" in r and "result" not in r
    assert time.perf_counter() - start < 1.0
    assert "hi" not in capfd.readouterr().out   # nothing was executed


@pytest.mark.parametrize("expr", [
    "open('x')", "x + 1", "[1, 2]", "'a' * 3", "lambda: 1", "True + 1",
    "(1).__class__.__bases__[0].__subclasses__()",
])
def test_calculate_refuses_non_arithmetic(expr):
    assert "error" in calculate(expr)


def test_calculate_division_by_zero():
    assert calculate("1/0")["error"] == "division by zero"
    assert "error" in calculate("5 % 0")
    assert "error" in calculate("0 ** -1")


def test_calculate_large_numbers():
    assert "too large" in calculate("10**20 * 10**20")["error"]
    assert "too large" in calculate("2 ** 1000")["error"] or "exponent" in calculate("2 ** 1000")["error"]
    assert "error" in calculate("1" + "*999999" * 60)


def test_calculate_syntax_errors_and_commas():
    assert "error" in calculate("2 +* 3")
    assert "thousands" in calculate("52,904 / 2")["error"]
    assert "error" in calculate("")
    assert "too long" in calculate("1+" * 200 + "1")["error"]


def test_calculate_precedence_and_unary():
    assert calculate("-2 ** 2")["result"] == -4
    assert calculate("(1 + 2) * 3 / 4")["result"] == pytest.approx(2.25)


# ---------------------------- loop helper -------------------------------

def test_run_tool_validates_json_arguments():
    assert "not valid JSON" in run_tool("lookup", "{district: Millbrook}")["error"]
    assert "unknown tool" in run_tool("rm", "{}")["error"]
    assert "unexpected" in run_tool("calculate", '{"expression": "1+1", "x": 1}')["error"]
    assert run_tool("lookup", '{"district": "Redfen", "field": "schools"}')["value"] == 10
