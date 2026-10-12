#!/usr/bin/env python3
"""Run one incumbent scenario against a running gNB and score it.

The core network, the gNB (with its log in --gnb-log), the UE and your dApp must already be running.

    tools/run_scenario.py scenarios/incumbent1_tone.json --gnb-log /tmp/gnb.log [--noise-dbfs -50]
    tools/run_scenario.py --seed 4711 --level 3 --gnb-log /tmp/gnb.log     # scenario from tools/generate_scenario.py

Results (ground truth, injector output, metrics) are written to --outdir (default: results/<scenario>-<noise>).
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate_scenario  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?", help="scenario file (or use --seed)")
    ap.add_argument("--seed", type=int, help="generate the scenario from this seed instead (tools/generate_scenario.py)")
    ap.add_argument("--level", type=int, default=1, choices=generate_scenario.LEVELS, help="difficulty with --seed")
    ap.add_argument("--duration", type=int, default=120, help="seconds, with --seed")
    ap.add_argument("--gnb-log", required=True, help="log of the running gNB (it must stay open while this runs)")
    ap.add_argument("--noise-dbfs", type=float, help="override the noise level of the scenario")
    ap.add_argument("--sample-rate", default="46080000", help="gNB sample rate (46080000 with -E)")
    ap.add_argument("--speed", default="1.0")
    ap.add_argument("--outdir")
    ap.add_argument("--injector", default=str(HERE / "incumbent-injector" / "incumbent-injector"))
    ap.add_argument("--no-iperf", action="store_true", help="do not run the UE uplink iperf3 flow")
    ap.add_argument("--iperf-server", default="192.168.70.135", help="iperf3 server (the oai-ext-dn container)")
    ap.add_argument("--iperf-dev", default="oaitun_ue1", help="UE tunnel interface")
    ap.add_argument("--iperf-rate", default="5M", help="offered uplink rate")
    a = ap.parse_args()

    if (a.scenario is None) == (a.seed is None):
        sys.exit("give a scenario file or --seed")
    if a.seed is not None:
        try:
            scen = generate_scenario.generate(a.seed, a.level, a.duration)
        except ValueError as e:
            sys.exit(str(e))
        gen_dir = Path(a.outdir or HERE.parent / "results" / f"{scen['name']}-noise{scen['noise_dbfs']:g}")
        gen_dir.mkdir(parents=True, exist_ok=True)
        a.scenario = str(gen_dir / "scenario.json")
        Path(a.scenario).write_text(generate_scenario.dumps(scen))
        print("scenario:", scen["comment"], file=sys.stderr)
    else:
        scen = json.load(open(a.scenario))
    if not scen.get("duration_s"):
        sys.exit("the scenario needs duration_s so the run ends by itself")
    noise = a.noise_dbfs if a.noise_dbfs is not None else scen.get("noise_dbfs")
    tag = f"{scen.get('name', Path(a.scenario).stem)}-noise{noise:g}"
    out = Path(a.outdir or HERE.parent / "results" / tag)
    out.mkdir(parents=True, exist_ok=True)

    uptime = float(open("/proc/uptime").read().split()[0])
    (out / "meta.json").write_text(json.dumps({"wall_unix": time.time(), "uptime_s": uptime}))
    cmd = [a.injector, "--scenario", a.scenario, "--sample-rate", a.sample_rate, "--speed", a.speed,
           "--events", str(out / "events.jsonl")]
    if a.noise_dbfs is not None:
        cmd += ["--noise-dbfs", str(a.noise_dbfs)]
    print("running", " ".join(cmd), file=sys.stderr)
    iperf_proc = None
    if not a.no_iperf and shutil.which("iperf3"):
        secs = int(scen["duration_s"]) + 4
        icmd = ["iperf3", "--bind-dev", a.iperf_dev, "-c", a.iperf_server, "-u", "-b", a.iperf_rate, "-t", str(secs), "-J"]
        print("uplink traffic:", " ".join(icmd), file=sys.stderr)
        iperf_proc = subprocess.Popen(icmd, stdout=open(out / "iperf.json", "w"), stderr=subprocess.STDOUT)
    elif not a.no_iperf:
        print("iperf3 not found: running without uplink traffic", file=sys.stderr)
    with open(out / "injector.log", "w") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    if iperf_proc is not None:
        iperf_proc.wait()
    if rc != 0:
        sys.exit(f"the injector failed (rc={rc}); see {out / 'injector.log'}")

    # copy the part of the gNB log that belongs to the run, so the result folder is self-contained
    res = subprocess.run([sys.executable, str(HERE / "score" / "score.py"), "--events", str(out / "events.jsonl"),
                          "--gnb-log", a.gnb_log, "--meta", str(out / "meta.json")]
                         + (["--iperf", str(out / "iperf.json")] if iperf_proc is not None else []),
                         capture_output=True, text=True)
    sys.stderr.write(res.stderr)
    if res.returncode != 0:
        sys.exit(res.stdout + res.stderr)
    (out / "score.json").write_text(res.stdout)
    print(f"results in {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
