"""Tests of the scenario generator.

    python3 -m pytest tools/test_generate_scenario.py

The scenarios in scenarios/ named seed<N>_level<L>.json pin the output of a few seeds: if one changes, every announced seed changes too.
Regenerate them on purpose with `python3 tools/test_generate_scenario.py --update-scenarios`.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import generate_scenario as g  # noqa: E402

SCENARIOS = HERE.parent / "scenarios"
PINNED = [(1, 1), (4711, 2), (4711, 3), (31337, 4), (2026, 5)]
INJECTOR = HERE / "incumbent-injector" / "incumbent-injector"


def pinned_path(seed, level):
    return SCENARIOS / f"seed{seed}_level{level}.json"


def occupied(c):
    width = c.get("width_prb", 1)
    firsts = c["hop"]["prbs"] if "hop" in c else [c["prb"]]
    return [(p, p + width - 1) for p in firsts]


@pytest.mark.parametrize("seed,level", PINNED)
def test_matches_the_pinned_scenario(seed, level, monkeypatch):
    monkeypatch.delenv("INCUMBENT_SALT", raising=False)
    assert g.dumps(g.generate(seed, level)) == pinned_path(seed, level).read_text()


def test_same_seed_same_bytes():
    for level in g.LEVELS:
        assert g.dumps(g.generate(99, level)) == g.dumps(g.generate(99, level))


def test_seeds_and_levels_differ():
    texts = {g.dumps(g.generate(s, 3)) for s in range(50)}
    assert len(texts) > 40
    assert g.dumps(g.generate(5, 1)) != g.dumps(g.generate(5, 2))


@pytest.mark.parametrize("duration", [80, 120, 200])
def test_constraints(duration):
    for level in g.LEVELS:
        for seed in range(400):
            scen = g.generate(seed, level, duration)
            assert scen["components"]
            starts = [c["start_s"] for c in scen["components"]]
            stops = [c["stop_s"] for c in scen["components"]]
            assert min(starts) >= g.QUIET_S and max(stops) <= duration - g.QUIET_S
            assert all(a < b for a, b in zip(starts, stops))
            for c in scen["components"]:
                for lo, hi in occupied(c):
                    assert g.FIRST_PRB <= lo and hi < g.NUM_PRBS
                    assert hi < g.DC_FIRST or lo > g.DC_LAST
                if "duty" in c:
                    assert 0 < c["duty"]["on_ms"] < c["duty"]["period_ms"]
                if "hop" in c:
                    assert len(c["hop"]["prbs"]) >= 2


def test_levels_have_their_shape():
    for seed in range(200):
        assert [c["shape"] for c in g.generate(seed, 1)["components"]] == ["tone"]
        assert {c["shape"] for c in g.generate(seed, 2)["components"]} == {"sweep"}
        assert len(g.generate(seed, 4)["components"]) == 1
        assert "duty" in g.generate(seed, 4)["components"][0]
        assert len(g.generate(seed, 5)["components"]) >= 2
    wide = [c for s in range(200) for c in g.generate(s, 3)["components"] if c["id"].startswith("wide")]
    assert wide


def test_simultaneous_incumbents_do_not_overlap_in_frequency():
    for level in (3, 5):
        for seed in range(300):
            comps = g.generate(seed, level)["components"]
            spans = [s for c in comps for s in occupied(c)]
            spans.sort()
            for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
                assert b0 > a1


def test_salt_changes_the_scenario(monkeypatch):
    monkeypatch.delenv("INCUMBENT_SALT", raising=False)
    plain = g.dumps(g.generate(7, 3))
    monkeypatch.setenv("INCUMBENT_SALT", "event")
    salted = g.dumps(g.generate(7, 3))
    assert salted != plain
    assert salted == g.dumps(g.generate(7, 3))


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        g.generate(-1, 1)
    with pytest.raises(ValueError):
        g.generate(1, 6)
    with pytest.raises(ValueError):
        g.generate(1, 1, duration=60)


@pytest.mark.skipif(not INJECTOR.exists(), reason="build the injector first (make in tools/incumbent-injector)")
@pytest.mark.parametrize("level", g.LEVELS)
def test_injector_accepts_output(level):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.json"
        f.write_text(g.dumps(g.generate(4711, level)))
        json.loads(f.read_text())
        subprocess.run([str(INJECTOR), "--scenario", str(f), "--offline-seconds", "0.1",
                        "--out-iq", str(Path(d) / "iq.bin")], check=True, capture_output=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--update-scenarios"]:
        for seed, level in PINNED:
            pinned_path(seed, level).write_text(g.dumps(g.generate(seed, level)))
            print("wrote", pinned_path(seed, level))
    else:
        sys.exit("run with pytest, or with --update-scenarios")
