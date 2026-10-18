"""Tests for `lookup`. No API key needed."""

from tools import lookup


def test_finds_correct_2025_population():
    r = lookup("Ossbridge", "population_2025")
    assert r["value"] == 52904
    assert r["source"] == "NR-01"
    assert "52,904" in r["evidence"]


def test_finds_2020_population_from_all_three_phrasings():
    assert lookup("Ossbridge", "population_2020")["value"] == 48317  # "the 2020 census had recorded"
    assert lookup("Tarnvale", "population_2020")["value"] == 67214   # "up from ... at the 2020 census"
    assert lookup("Ossford", "population_2020")["value"] == 31560    # "Census population: X in 2020"


def test_misspelled_name_is_not_guessed():
    r = lookup("Ossbrige", "area_km2")
    assert "value" not in r
    assert "Ossbridge" in r["error"] and "Ossford" in r["error"]


def test_similar_names_are_kept_apart():
    assert lookup("Ossbridge", "area_km2")["value"] == 1284.6
    assert lookup("Ossford", "area_km2")["value"] == 846.2
    r = lookup("Oss", "area_km2")
    assert "more than one district" in r["error"]


def test_archived_profile_is_never_used():
    r = lookup("Tarnvale", "population_2025")
    assert r["value"] == 71388          # NR-03, not the 2019 estimate 65,030 in NR-13
    assert r["source"] == "NR-03"
    assert r["archived_ignored"] == "NR-13"
    k = lookup("Kelmarsh", "water_use_2025_megalitres")
    assert k["value"] == 1739           # not 1,652 (2018) from archived NR-14
    assert k["source"] == "NR-04"


def test_correction_notice_wins():
    r = lookup("Brightwater", "area_km2")
    assert r["value"] == 921.4
    assert r["source"] == "NR-16"
    assert "912.4" in r["note"]


def test_cubic_metres_converted_to_megalitres():
    r = lookup("Lindenmoor", "water_use_2025_megalitres")
    assert r["value"] == 2151.4
    assert r["unit"] == "megalitres"
    assert "cubic metres" in r["note"]


def test_region_tariff_is_2025_not_2024():
    r = lookup("region", "water_tariff_tenge_per_m3")
    assert r["value"] == 142.35
    assert r["source"] == "NR-15"


def test_bad_inputs_return_errors_not_exceptions():
    assert "error" in lookup("Ossbridge", "gdp")
    assert "error" in lookup("", "area_km2")
    assert "error" in lookup("x" * 10_000, "area_km2")
    assert "error" in lookup(None, "area_km2")
    assert "error" in lookup("region", "schools")
    assert "error" in lookup("Millbrook", "water_tariff_tenge_per_m3")


def test_evidence_is_short_not_whole_document():
    r = lookup("Harrowfield", "pupils_2025_26")
    assert r["value"] == 13904
    assert len(r["evidence"]) <= 200
