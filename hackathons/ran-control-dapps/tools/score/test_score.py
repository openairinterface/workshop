import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import score  # noqa: E402

T0 = 1_000_000.0  # wall seconds


def ev(t, cid, state, prbs=()):
    return {"t_s": t, "wall_unix_ns": int((T0 + t) * 1e9), "id": cid, "state": state, "prbs": list(prbs)}


def run(comp, controls, end=30.0):
    head = {"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0}
    ticks = [{"tick": True, "t_s": end, "wall_unix_ns": int((T0 + end) * 1e9)}]
    return score.compute(head, ticks, comp, [(T0 + t, frozenset(p)) for t, p in controls])


def test_perfect_policy_scores_high():
    m = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [(10.05, [72]), (20.5, [])])
    assert m["protection"] > 0.99
    assert m["episodes"][0]["time_to_block_s"] < 0.1
    assert abs(m["episodes"][0]["time_to_release_s"] - 0.5) < 0.02
    # the 0.5 s of holding the PRB after the incumbent left is the only cost
    assert abs(m["over_block_prb_s"] - 0.5) < 0.02 and abs(m["quiet_false_block_prb_s"] - 0.5) < 0.02
    assert m["score"] > 95


def test_no_policy_has_no_protection():
    m = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [])
    assert m["protection"] == 0 and m["episodes"][0]["time_to_block_s"] is None
    assert m["score"] == 0


def test_blocking_everything_is_penalised_not_rewarded():
    good = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [(10.05, [72]), (20.1, [])])
    lazy = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [(0.1, list(range(106)))])
    assert lazy["protection"] > 0.99 and lazy["over_block_fraction"] > 0.5
    assert lazy["score"] < good["score"] - 20


def test_neighbour_prbs_are_tolerated_but_not_far_ones():
    near = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [(10.0, [71, 72, 73]), (20.0, [])])
    far = run([ev(10, "a", "on", [72]), ev(20, "a", "off")], [(10.0, [72, 90]), (20.0, [])])
    assert near["over_block_prb_s"] == 0
    assert far["over_block_prb_s"] > 9


def test_false_block_when_nothing_is_active():
    m = run([], [(5.0, [10]), (15.0, [])])
    assert m["protection"] is None
    assert abs(m["quiet_false_block_prb_s"] - 10.0) < 0.1


def test_hop_makes_two_episodes():
    comp = [ev(5, "h", "on", [70]), ev(10, "h", "on", [80]), ev(15, "h", "off")]
    m = run(comp, [(5.2, [70]), (10.3, [80]), (15.2, [])])
    assert [e["prbs"] for e in m["episodes"]] == [[70], [80]]
    assert m["protection"] > 0.9


def test_cli_parses_a_gnb_log():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ev_lines = [{"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0, "sample_rate": 46080000.0},
                    ev(2, "a", "on", [5]), ev(4, "a", "off"),
                    {"tick": True, "t_s": 6, "wall_unix_ns": int((T0 + 6) * 1e9)}]
        (d / "e.jsonl").write_text("\n".join(json.dumps(x) for x in ev_lines))
        (d / "g.log").write_text(
            "100.500000 [E3AP]   I [SPECTRUM-SM] prbBlock: set UL+DL mask n_prbs=1 PRBs=[5] -> ok=1\n"
            "102.500000 [E3AP]   I [SPECTRUM-SM] prbBlock: clear UL+DL -> ok=1\n")
        (d / "m.json").write_text(json.dumps({"wall_unix": T0 + 2.0, "uptime_s": 100.4}))
        out = subprocess.run([sys.executable, str(HERE / "score.py"), "--events", str(d / "e.jsonl"),
                              "--gnb-log", str(d / "g.log"), "--meta", str(d / "m.json")],
                             capture_output=True, text=True, check=True).stdout
        m = json.loads(out)
        assert m["protection"] > 0.9 and abs(m["episodes"][0]["time_to_block_s"] - 0.1) < 0.02


def test_dropped_ue_is_counted_and_penalised():
    comp = [ev(10, "a", "on", [72]), ev(20, "a", "off")]
    controls = [(10.05, [72]), (20.5, [])]
    head = {"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0}
    ticks = [{"tick": True, "t_s": 30.0, "wall_unix_ns": int((T0 + 30.0) * 1e9)}]
    blocks = [(T0 + t, frozenset(p)) for t, p in controls]
    ok = score.compute(head, ticks, comp, blocks, 0, {"ul_failure": [], "random_access": [T0 - 5]})
    dropped = score.compute(head, ticks, comp, blocks, 0,
                            {"ul_failure": [T0 + 12], "random_access": [T0 + 13], "pucch_block_hit": [T0 + 11]})
    assert not ok["ue_dropped"] and ok["ue_random_access"] == 0      # the attach before the run does not count
    assert dropped["ue_dropped"] and dropped["pucch_block_hits"] == 1
    assert dropped["score"] < ok["score"] - 50


def test_cli_reads_ue_events_from_the_gnb_log():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ev_lines = [{"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0, "sample_rate": 46080000.0},
                    ev(2, "a", "on", [5]), ev(4, "a", "off"),
                    {"tick": True, "t_s": 6, "wall_unix_ns": int((T0 + 6) * 1e9)}]
        (d / "e.jsonl").write_text("\n".join(json.dumps(x) for x in ev_lines))
        (d / "g.log").write_text(
            "100.400000 [NR_PHY] A [RAPROC] 1.19 Initiating RA procedure with preamble 6\n"
            "100.500000 [E3AP]   I [SPECTRUM-SM] prbBlock: set UL+DL mask n_prbs=1 PRBs=[5] -> ok=1\n"
            "101.000000 [NR_MAC] W [PRB-BLOCK] new block hits configured PUCCH (RNTI 24b5): PRB[0..7]\n"
            "101.500000 [NR_MAC] W  486. 7 UE 24b5: Detected UL Failure on PUSCH after 10 PUSCH DTX, stopping scheduling\n"
            "102.500000 [E3AP]   I [SPECTRUM-SM] prbBlock: clear UL+DL -> ok=1\n")
        (d / "m.json").write_text(json.dumps({"wall_unix": T0 + 2.0, "uptime_s": 100.4}))
        out = subprocess.run([sys.executable, str(HERE / "score.py"), "--events", str(d / "e.jsonl"),
                              "--gnb-log", str(d / "g.log"), "--meta", str(d / "m.json")],
                             capture_output=True, text=True, check=True).stdout
        m = json.loads(out)
        assert m["ue_ul_failures"] == 1 and m["pucch_block_hits"] == 1 and m["ue_dropped"]


def test_log_without_timestamps_is_refused_with_a_hint():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "e.jsonl").write_text(json.dumps({"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0}) + "\n"
                                   + json.dumps({"tick": True, "t_s": 6, "wall_unix_ns": int((T0 + 6) * 1e9)}) + "\n")
        (d / "g.log").write_text("[E3AP]   I [SPECTRUM-SM] prbBlock: set UL+DL mask n_prbs=1 PRBs=[5] -> ok=1\n")
        r = subprocess.run([sys.executable, str(HERE / "score.py"), "--events", str(d / "e.jsonl"), "--gnb-log", str(d / "g.log")],
                           capture_output=True, text=True)
        assert r.returncode != 0 and "global_log_options" in (r.stderr + r.stdout)


def _iperf(tmp, delivered_bps, offered=5_000_000):
    p = Path(tmp) / "i.json"
    p.write_text(json.dumps({"start": {"test_start": {"target_bitrate": offered}},
                             "end": {"sum": {"bits_per_second": delivered_bps, "lost_percent": 0.0}}}))
    return str(p)


def test_uplink_traffic_ratio_and_penalty():
    comp = [ev(10, "a", "on", [72]), ev(20, "a", "off")]
    head = {"scenario": "t", "scenario_start_wall_unix_ns": int(T0 * 1e9), "noise_dbfs": -60.0}
    ticks = [{"tick": True, "t_s": 30.0, "wall_unix_ns": int((T0 + 30.0) * 1e9)}]
    blocks = [(T0 + 10.05, frozenset([72])), (T0 + 20.5, frozenset())]
    with tempfile.TemporaryDirectory() as d:
        full = score.compute(head, ticks, comp, blocks, 0, {}, score.read_iperf(_iperf(d, 4_960_000)))
        half = score.compute(head, ticks, comp, blocks, 0, {}, score.read_iperf(_iperf(d, 2_500_000)))
        none = score.compute(head, ticks, comp, blocks, 0, {}, None)
        broken = Path(d) / "e.json"
        broken.write_text(json.dumps({"error": "unable to connect to server"}))
        dead = score.compute(head, ticks, comp, blocks, 0, {}, score.read_iperf(str(broken)))
    assert full["ue_traffic"]["ratio"] > 0.99 and half["ue_traffic"]["ratio"] == 0.5
    assert none["ue_traffic"] is None and none["score"] > full["score"] - 0.5   # no iperf: no penalty
    assert full["score"] - half["score"] == pytest.approx(10.0, abs=0.6)
    assert dead["ue_traffic"]["ratio"] == 0.0 and dead["score"] < half["score"]
