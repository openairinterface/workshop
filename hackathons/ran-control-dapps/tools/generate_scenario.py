#!/usr/bin/env python3
"""Generate a random incumbent scenario from a seed.

    tools/generate_scenario.py --seed 4711 --level 3 --out /tmp/seed4711.json [--show]

The same seed and level give the same scenario on every machine (own PRNG, integer grids, fixed
draw order, no external random source), so a seed announced at the demo is a fixed test.
The output uses the scenario format of the injector; run it with tools/run_scenario.py or
`tools/run_scenario.py --seed 4711 --level 3 --gnb-log /tmp/gnb.log`.

Levels:
  1  one strong tone
  2  one 4-8 PRB wide signal, on and off once or twice
  3  a hopping tone, or two incumbents of different power and width at the same time
  4  one weaker wide signal that is only on for part of every few milliseconds
  5  two or three weak incumbents (tone, band, hopping, duty-cycled)

Incumbents sit in PRBs 16-105 outside the DC guard (50-56), so the UE control channels are never
under them, and every scenario is quiet for 20 s before the first and after the last one.
Set INCUMBENT_SALT (number or text) to change every seed's scenario; the default is no salt.
"""
import argparse
import json
import os
import sys

MASK = (1 << 64) - 1
NUM_PRBS = 106
FIRST_PRB = 16
DC_FIRST, DC_LAST = 50, 56
QUIET_S = 20
MIN_DURATION_S = 80
LEVELS = (1, 2, 3, 4, 5)


class Rng:
    """SplitMix64 stream."""

    def __init__(self, seed: int):
        self.s = seed & MASK

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n

    def between(self, lo: int, hi: int) -> int:
        """Integer in lo..hi, both included."""
        return lo + self.below(hi - lo + 1)

    def pick(self, items):
        return items[self.below(len(items))]


def salt_value() -> int:
    raw = os.environ.get("INCUMBENT_SALT", "")
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw) & MASK
    h = 0xCBF29CE484222325                       # FNV-1a, for text
    for b in raw.encode():
        h = ((h ^ b) * 0x100000001B3) & MASK
    return h


def starts(width: int):
    """First PRBs where a signal `width` PRBs wide fits in the allowed area."""
    out = []
    for p in range(FIRST_PRB, NUM_PRBS - width + 1):
        if p + width - 1 < DC_FIRST or p > DC_LAST:
            out.append(p)
    return out


def free_start(rng: Rng, width: int, taken, gap: int = 4):
    """A start PRB for `width` PRBs, at least `gap` PRBs away from the (first, width) pairs in `taken`."""
    cand = starts(width)
    ok = [p for p in cand if all(p + width + gap <= q or q + w + gap <= p for q, w in taken)]
    return rng.pick(ok or cand)


class Builder:
    def __init__(self, rng: Rng, duration: int):
        self.rng = rng
        self.duration = duration
        self.taken = []                          # (first PRB, width) of what is already placed
        self.components = []
        self.n = 0

    def window(self, min_len: int, max_len: int):
        """Start and stop in whole seconds inside the quiet margins."""
        avail = self.duration - 2 * QUIET_S
        length = self.rng.between(min(min_len, avail), min(max_len, avail))
        start = QUIET_S + self.rng.between(0, avail - length)
        return start, start + length

    def add(self, shape, amp, win, width=1, hop=False, duty=False, label=None):
        rng = self.rng
        self.n += 1
        c = {"id": f"{label or shape}_{self.n}", "shape": shape}
        if hop:
            positions, dwell = self.hop_set(width)
            hop_seed = rng.between(1, 2**31 - 1)
            self.taken.extend((p, width) for p in positions)
        else:
            prb = free_start(rng, width, self.taken)
            self.taken.append((prb, width))
            c["prb"] = prb
        if shape == "sweep":
            c["width_prb"] = width
            c["sweep_period_us"] = 50
        c["amplitude_dbfs"] = amp
        c["start_s"], c["stop_s"] = win
        if hop:
            c["hop"] = {"prbs": positions, "dwell_s": dwell, "seed": hop_seed}
        if duty:
            period = rng.pick((5, 8, 10, 20))
            on = max(1, (period * rng.between(30, 60) + 50) // 100)     # whole ms, 30-60 % of the period
            c["duty"] = {"period_ms": period, "on_ms": on, "offset_ms": 0}
        self.components.append(c)

    def hop_set(self, width):
        rng = self.rng
        count = rng.between(3, 4)
        positions = []
        for _ in range(count):
            cand = [p for p in starts(width) if all(abs(p - q) >= 8 for q in positions)
                    and all(p + width + 4 <= q or q + w + 4 <= p for q, w in self.taken)]
            if not cand:
                break
            positions.append(rng.pick(cand))
        return positions, rng.between(2, 5)


def level1(b):
    b.add("tone", b.rng.between(-45, -35), b.window(30, 60))


def level2(b):
    rng = b.rng
    width, amp = rng.between(4, 8), rng.between(-36, -28)
    avail = b.duration - 2 * QUIET_S
    first, gap, second = rng.between(15, 25), rng.between(10, 20), rng.between(15, 25)
    prb = free_start(rng, width, [])
    if rng.below(2) and first + gap + second <= avail:
        t0 = QUIET_S + rng.between(0, avail - (first + gap + second))
        wins = [(t0, t0 + first), (t0 + first + gap, t0 + first + gap + second)]
    else:
        wins = [b.window(20, 50)]
    for w in wins:
        b.n += 1
        b.components.append({"id": f"band_{b.n}", "shape": "sweep", "prb": prb, "width_prb": width,
                             "sweep_period_us": 50, "amplitude_dbfs": amp, "start_s": w[0], "stop_s": w[1]})
    b.taken.append((prb, width))


def level3(b):
    rng = b.rng
    if rng.below(2):
        b.add("tone", rng.between(-42, -36), b.window(30, 60), hop=True, label="hop")
    else:
        strong = rng.between(-36, -32)
        a = b.window(30, 60)
        b.add("sweep", strong, a, width=rng.between(6, 10), label="wide")
        b.add("tone", strong - rng.between(4, 8), b.window(25, 50), label="narrow")


def level4(b):
    rng = b.rng
    b.add("sweep", rng.between(-50, -44), b.window(30, 60), width=rng.between(4, 10), duty=True, label="weak")


def level5(b):
    rng = b.rng
    for _ in range(rng.between(2, 3)):
        kind = rng.below(3)
        amp = rng.between(-50, -40)
        win = b.window(20, 50)
        if kind == 0:
            b.add("tone", amp, win, hop=True, duty=bool(rng.below(2)), label="hop")
        elif kind == 1:
            b.add("sweep", amp, win, width=rng.between(4, 10), duty=bool(rng.below(2)), label="band")
        else:
            b.add("tone", amp, win, duty=bool(rng.below(2)), label="tone")


BUILD = {1: level1, 2: level2, 3: level3, 4: level4, 5: level5}


def generate(seed: int, level: int = 1, duration: int = 120, noise_dbfs: int = -60) -> dict:
    if seed < 0:
        raise ValueError("the seed must not be negative")
    if level not in LEVELS:
        raise ValueError("the level must be 1 to 5")
    if duration < MIN_DURATION_S:
        raise ValueError(f"the duration must be at least {MIN_DURATION_S} s")
    rng = Rng(Rng((seed ^ salt_value()) & MASK).next() ^ level)
    b = Builder(rng, duration)
    BUILD[level](b)
    scen = {"name": f"seed{seed}_level{level}", "seed": seed, "level": level,
            "duration_s": duration, "noise_dbfs": noise_dbfs, "components": b.components}
    scen["comment"] = summary(scen)
    return scen


def summary(scen: dict) -> str:
    parts = []
    for c in scen["components"]:
        where = f"PRBs {c['hop']['prbs']} (hop every {c['hop']['dwell_s']} s)" if "hop" in c else \
            (f"PRBs {c['prb']}-{c['prb'] + c['width_prb'] - 1}" if "width_prb" in c else f"PRB {c['prb']}")
        duty = f", {c['duty']['on_ms']} ms on every {c['duty']['period_ms']} ms" if "duty" in c else ""
        parts.append(f"{c['id']}: {where}, {c['amplitude_dbfs']} dBFS, {c['start_s']}-{c['stop_s']} s{duty}")
    return "; ".join(parts)


def dumps(scen: dict) -> str:
    head = [f'  "{k}": {json.dumps(scen[k])}' for k in ("name", "comment", "seed", "level", "duration_s", "noise_dbfs")]
    comps = ",\n".join("    " + json.dumps(c, separators=(", ", ": ")) for c in scen["components"])
    return "{\n" + ",\n".join(head) + ',\n  "components": [\n' + comps + "\n  ]\n}\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--level", type=int, default=1, choices=LEVELS)
    ap.add_argument("--duration", type=int, default=120, help="seconds (default 120, at least 80)")
    ap.add_argument("--noise-dbfs", type=int, default=-60)
    ap.add_argument("--out", help="write the scenario here (default: stdout)")
    ap.add_argument("--show", action="store_true", help="print what the scenario contains")
    a = ap.parse_args()
    try:
        scen = generate(a.seed, a.level, a.duration, a.noise_dbfs)
    except ValueError as e:
        sys.exit(str(e))
    text = dumps(scen)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    elif not a.show:
        sys.stdout.write(text)
    if a.show:
        print(f"{scen['name']}: {a.duration} s, noise {a.noise_dbfs} dBFS")
        for c in scen["components"]:
            print("  " + summary({"components": [c]}))


if __name__ == "__main__":
    main()
