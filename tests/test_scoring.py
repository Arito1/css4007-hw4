"""Tests for the answer parser, the S2 vote and the scoring rule. No API key needed."""

from run import is_correct
from strategies import majority_vote, parse_answer

Q09 = {"answer": "Millbrook", "value": 0.6, "decimals": 1}
Q19 = {"answer": "Lindenmoor", "value": 0.035, "decimals": 3}


def test_parse_takes_the_last_answer_line():
    text = "ANSWER: Ossford | 1\nworking...\nANSWER: **Millbrook** | 0.556"
    assert parse_answer(text) == ("Millbrook", 0.556)
    assert parse_answer("ANSWER: yes | 14,069") == ("yes", 14069.0)
    assert parse_answer("no answer here") is None


def test_scoring_rule():
    assert is_correct(("Millbrook", 0.556), Q09)
    assert is_correct(("millbrook", 0.5), Q09)       # 1 unit in the last digit allowed
    assert not is_correct(("Millbrook", 0.077), Q09)  # uncorrected-area answer (0.1)
    assert not is_correct(("Brightwater", 0.556), Q09)
    assert not is_correct(None, Q09)
    assert is_correct(("Lindenmoor", 0.0348), Q19)
    assert not is_correct(("Lindenmoor", 0.03), Q19)


def test_majority_vote():
    votes = [("Millbrook", 0.556), ("Brightwater", 0.1), ("millbrook", 0.556), None, ("Millbrook", 0.5)]
    assert majority_vote(votes) == ("Millbrook", 0.556)
    assert majority_vote([None, None]) is None
