#!/usr/bin/env python3
"""Score one run of an incumbent scenario.

Inputs:
  --events   ground truth written by the injector (--events FILE)
  --gnb-log  the gNB log of the same run (PRB blocks are read from the E3 "prbBlock:" lines)
  --meta     optional JSON with the clock link between the gNB log and wall time,
             {"wall_unix": <float>, "uptime_s": <float>} taken at the same instant;
             defaults to the current machine's /proc/uptime (valid on the machine that ran the gNB)

Output: the metrics as JSON on stdout and a short summary on stderr.
The final score formula is deliberately a placeholder: edit `score()` once the
evaluation rules are fixed.
"""
import argparse
import json
import re
import sys
import time

NUM_PRBS = 106
GRID_S = 0.005
TOLERANCE_PRBS = 1  # PRBs next to the incumbent are not counted as over-blocking

# UE health, from the gNB log
UL_FAIL_RE = re.compile(r"^\s*(\d+\.\d+)\s.*Detected UL Failure")
RA_RE = re.compile(r"^\s*(\d+\.\d+)\s.*Initiating RA procedure")
PUCCH_HIT_RE = re.compile(r"^\s*(\d+\.\d+)\s.*new block hits configured PUCCH")

SET_RE = re.compile(r"^\s*(\d+\.\d+)\s.*prbBlock: set .*PRBs=\[([0-9, ]*)\]\s*->\s*ok=(\d)")
CLEAR_RE = re.compile(r"^\s*(\d+\.\d+)\s.*prbBlock: clear .*->\s*ok=(\d)")


def read_events(path):
    head, ticks, comp = None, [], []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        if "scenario_start_wall_unix_ns" in e:
            head = e
        elif e.get("tick"):
            ticks.append(e)
        elif "state" in e:
            comp.append(e)
    if head is None:
        raise SystemExit("no scenario header in " + path)
    return head, ticks, comp


class NoTimestamps(SystemExit):
    pass


def check_timestamps(path):
    """The gNB log needs time prefixes to be matched with the scenario clock."""
    with open(path, errors="replace") as f:
        for line in f:
            if "prbBlock:" in line:
                if not re.match(r"^\s*\d+\.\d+\s", line):
                    raise NoTimestamps(
                        f"{path} has no timestamps, so the blocks cannot be matched with the scenario.\n"
                        "Start the gNB with --log_config.global_log_options level,nocolor,time to score a run yourself.")
                return


def read_blocks(path, wall_offset):
    """-> list of (wall_s, frozenset(PRBs)) in time order; the state after each control."""
    out, bad = [], 0
    for line in open(path, errors="replace"):
        m = SET_RE.match(line)
        if m:
            t, prbs, ok = float(m.group(1)), m.group(2), m.group(3)
            if ok != "1":
                bad += 1
                continue
            out.append((t + wall_offset, frozenset(int(x) for x in prbs.replace(" ", "").split(",") if x)))
            continue
        m = CLEAR_RE.match(line)
        if m:
            if m.group(2) != "1":
                bad += 1
                continue
            out.append((float(m.group(1)) + wall_offset, frozenset()))
    return out, bad


def read_ue_events(path, wall_offset):
    """-> dict of event name -> list of wall times, from the gNB log."""
    out = {"ul_failure": [], "random_access": [], "pucch_block_hit": []}
    for line in open(path, errors="replace"):
        for key, rx in (("ul_failure", UL_FAIL_RE), ("random_access", RA_RE), ("pucch_block_hit", PUCCH_HIT_RE)):
            m = rx.match(line)
            if m:
                out[key].append(float(m.group(1)) + wall_offset)
    return out


def read_iperf(path):
    """UE uplink traffic from `iperf3 -u -J`: delivered share of the offered rate.

    Returns None without a file; ratio 0 with an error (no connectivity)."""
    if not path:
        return None
    try:
        d = json.load(open(path))
    except (OSError, ValueError):
        return {"error": "no usable iperf3 output", "ratio": 0.0}
    if "error" in d:
        return {"error": str(d["error"]), "ratio": 0.0}
    end = d.get("end", {})
    got = end.get("sum_received") or end.get("sum") or {}
    offered = d.get("start", {}).get("test_start", {}).get("target_bitrate") or 0
    bps = float(got.get("bits_per_second", 0.0))
    ratio = min(1.0, bps / offered) if offered else 0.0
    return {"offered_mbps": round(offered / 1e6, 3), "delivered_mbps": round(bps / 1e6, 3),
            "lost_percent": got.get("lost_percent"), "ratio": round(ratio, 4)}


def episodes(comp):
    """Ground-truth episodes: (id, start_wall_s, end_wall_s or None, frozenset(PRBs))."""
    open_ = {}
    out = []
    for e in comp:
        t = e["wall_unix_ns"] / 1e9
        cid = e["id"]
        if cid in open_:
            s, prbs = open_.pop(cid)
            out.append((cid, s, t, prbs))
        if e["state"] == "on":
            open_[cid] = (t, frozenset(e["prbs"]))
    for cid, (s, prbs) in open_.items():
        out.append((cid, s, None, prbs))
    return sorted(out, key=lambda x: x[1])


def blocked_at(blocks, t):
    cur = frozenset()
    for bt, s in blocks:
        if bt > t:
            break
        cur = s
    return cur


def compute(head, ticks, comp, blocks, bad_controls=0, ue_events=None, iperf=None):
    t0 = head["scenario_start_wall_unix_ns"] / 1e9
    t_end = ticks[-1]["wall_unix_ns"] / 1e9 if ticks else max(e["wall_unix_ns"] for e in comp) / 1e9
    eps = [(c, s, e if e is not None else t_end, p) for c, s, e, p in episodes(comp)]
    n_grid = int((t_end - t0) / GRID_S)

    bi = 0
    cur = frozenset()
    prot_num = prot_den = 0.0
    over_prb_s = quiet_over_prb_s = 0.0
    inc_prb_s_allowed = 0.0
    quiet_s = 0.0
    for k in range(n_grid):
        t = t0 + (k + 0.5) * GRID_S
        while bi < len(blocks) and blocks[bi][0] <= t:
            cur = blocks[bi][1]
            bi += 1
        truth = set()
        for _, s, e, p in eps:
            if s <= t < e:
                truth |= p
        if truth:
            prot_num += len(cur & truth) / len(truth)
            prot_den += 1
        near = set(truth)
        for p in truth:
            for d in range(1, TOLERANCE_PRBS + 1):
                near.update((p - d, p + d))
        extra = len(cur - near)
        over_prb_s += extra * GRID_S
        inc_prb_s_allowed += (NUM_PRBS - len(near)) * GRID_S
        if not truth:
            quiet_over_prb_s += len(cur) * GRID_S
            quiet_s += GRID_S

    per = []
    for cid, s, e, p in eps:
        tb = None
        t = s
        while t < e:
            if p <= blocked_at(blocks, t):
                tb = t - s
                break
            t += GRID_S
        tr = None
        if e < t_end:
            t = e
            while t < t_end:
                if not (blocked_at(blocks, t) & p):
                    tr = t - e
                    break
                t += GRID_S
        per.append({"id": cid, "prbs": sorted(p), "start_s": round(s - t0, 3), "end_s": round(e - t0, 3),
                    "time_to_block_s": None if tb is None else round(tb, 3),
                    "time_to_release_s": None if tr is None else round(tr, 3)})

    m = {
        "scenario": head["scenario"],
        "noise_dbfs": head["noise_dbfs"],
        "duration_s": round(t_end - t0, 2),
        "protection": None if prot_den == 0 else round(prot_num / prot_den, 4),
        "over_block_prb_s": round(over_prb_s, 3),
        "over_block_fraction": round(over_prb_s / inc_prb_s_allowed, 5) if inc_prb_s_allowed else 0.0,
        "quiet_false_block_prb_s": round(quiet_over_prb_s, 3),
        "quiet_s": round(quiet_s, 2),
        "episodes": per,
        "controls_rejected": bad_controls,
    }
    # The UE is attached when the run starts, so any random access inside the run is a reconnection.
    ue = {k: sum(1 for t in v if t0 <= t <= t_end) for k, v in (ue_events or {}).items()}
    m["ue_ul_failures"] = ue.get("ul_failure", 0)
    m["ue_random_access"] = ue.get("random_access", 0)
    m["pucch_block_hits"] = ue.get("pucch_block_hit", 0)
    m["ue_dropped"] = m["ue_ul_failures"] > 0 or m["ue_random_access"] > 0
    m["ue_traffic"] = iperf
    m["score"] = score(m)
    return m


def score(m):
    """PLACEHOLDER 0-100 score; replace with the final evaluation rules."""
    prot = m["protection"] or 0.0
    ttb = [e["time_to_block_s"] for e in m["episodes"]]
    ttb = [x if x is not None else 10.0 for x in ttb]
    latency_penalty = min(20.0, 2.0 * (sum(ttb) / len(ttb))) if ttb else 0.0
    over_penalty = min(30.0, 300.0 * m["over_block_fraction"])
    drop_penalty = 60.0 if m.get("ue_dropped") else 0.0  # the largest single penalty: do not break the UE
    traffic = m.get("ue_traffic")
    traffic_penalty = 20.0 * (1.0 - traffic["ratio"]) if traffic else 0.0  # share of the offered uplink rate not delivered
    return round(max(0.0, 100.0 * prot - latency_penalty - over_penalty - drop_penalty - traffic_penalty), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", required=True)
    ap.add_argument("--gnb-log", required=True)
    ap.add_argument("--meta")
    ap.add_argument("--iperf", help="`iperf3 -u -J` output of the UE uplink flow during the run")
    a = ap.parse_args()
    if a.meta:
        meta = json.load(open(a.meta))
        offset = meta["wall_unix"] - meta["uptime_s"]
    else:
        offset = time.time() - float(open("/proc/uptime").read().split()[0])
    head, ticks, comp = read_events(a.events)
    check_timestamps(a.gnb_log)
    blocks, bad = read_blocks(a.gnb_log, offset)
    m = compute(head, ticks, comp, blocks, bad, read_ue_events(a.gnb_log, offset), read_iperf(a.iperf))
    json.dump(m, sys.stdout, indent=2)
    print()
    prot = "n/a" if m["protection"] is None else f"{100 * m['protection']:.1f}%"
    print(f"{m['scenario']}: protection {prot}, over-blocked {m['over_block_prb_s']} PRB.s, "
          f"quiet false blocks {m['quiet_false_block_prb_s']} PRB.s, "
          f"UE {'DROPPED' if m['ue_dropped'] else 'kept'} (UL failures {m['ue_ul_failures']}, "
          f"random access {m['ue_random_access']}, PUCCH hits {m['pucch_block_hits']}), "
          f"uplink {'n/a' if not m['ue_traffic'] else str(m['ue_traffic']['delivered_mbps']) + ' of ' + str(m['ue_traffic'].get('offered_mbps', '?')) + ' Mbit/s'}, "
          f"score {m['score']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
