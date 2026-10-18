"""Tests for `calculate` and the loop's input validation. No API key needed."""

import time

import pytest

from tools import calculate, run_tool, validate_args


def test_multiplication_is_exact():
    assert calculate("48317 * 1.0947")["result"] == pytest.approx(52892.6199, abs=1e-9)


def test_q09_expression():
    r = calculate("37203 / 758.6 - 44675 / 921.4")
    assert r["result"] == pytest.approx(0.5556561156, abs=1e-9)


def test_precedence_parentheses_and_unary_minus():
    assert calculate("-(2 + 3) * 4 ** 2 / 8")["result"] == -10.0
    assert calculate("(11902 - 11407) / 11902 * 100")["result"] == pytest.approx(4.15896488, abs=1e-6)


@pytest.mark.parametrize(
    "expression, expected_error",
    [
        ("__import__('os').system('echo hi')", "not allowed"),
        ("(1).__class__", "not allowed"),
        ("9**9**9", "exponent too large"),
    ],
)
def test_refuses_dangerous_inputs_quickly(expression, expected_error):
    start = time.perf_counter()
    r = calculate(expression)
    assert expected_error in r["error"]
    assert "result" not in r
    assert time.perf_counter() - start < 0.5  # refused, not computed


def test_division_by_zero():
    assert calculate("1 / 0")["error"] == "division by zero"
    assert calculate("5 % 0")["error"] == "division by zero"


def test_too_large_results_are_refused():
    assert calculate("10 ** 100")["error"] == "result too large"
    assert calculate("1e308 * 10")["error"] == "result too large"


def test_other_bad_inputs():
    assert "thousands separators" in calculate("44,675 / 921.4")["error"]
    assert "could not parse" in calculate("2 +")["error"]
    assert "not allowed" in calculate("x + 1")["error"]
    assert "not allowed" in calculate("'a' * 3")["error"]
    assert "not allowed" in calculate("True + 1")["error"]
    assert "not allowed" in calculate("[1, 2][0]")["error"]
    assert "too long" in calculate("1+" * 150 + "1")["error"]
    assert "error" in calculate(None)


def test_loop_validation_rejects_bad_arguments():
    assert validate_args("lookup", {"district": "Ossford", "field": "area_km2"}) is None
    assert validate_args("lookup", '{"district": "Ossford", "field": "area_km2"}') is None
    assert "not valid JSON" in validate_args("lookup", '{"district": "Ossford"')
    assert "required" in validate_args("lookup", {"district": "Ossford"})
    assert "unexpected" in validate_args("calculate", {"expression": "1", "x": 2})
    assert "must be a string" in validate_args("calculate", {"expression": 5})
    assert "unknown tool" in validate_args("eval", {"code": "1"})
    result, is_error = run_tool("calculate", {"expression": "__import__('os')"})
    assert is_error and "not allowed" in result["error"]
