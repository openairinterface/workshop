"""Offline check of the injector: runs it without a gNB and looks at the spectrum.

    make && python3 test_injector.py
"""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
BIN = HERE / "incumbent-injector"
FS = 61.44e6
NPRB = 106
FFT = 2048          # 30 kHz subcarrier spacing at 61.44 Msps
SC = 12 * NPRB


def render(scenario: dict, seconds: float, extra=()) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.json"
        f.write_text(json.dumps(scenario))
        out = Path(d) / "iq.bin"
        subprocess.run([str(BIN), "--scenario", str(f), "--offline-seconds", str(seconds),
                        "--out-iq", str(out), *extra], check=True, capture_output=True)
        raw = np.fromfile(out, dtype=np.int16).astype(np.float32)
    return raw[0::2] + 1j * raw[1::2]


def prb_power_db(iq: np.ndarray) -> np.ndarray:
    """Mean power per PRB over all OFDM-sized windows of the signal (no CP handling needed)."""
    n = len(iq) // FFT
    x = iq[: n * FFT].reshape(n, FFT)
    spec = np.fft.fftshift(np.fft.fft(x * np.hanning(FFT), axis=1), axes=1)
    centre = FFT // 2
    sc = spec[:, centre - SC // 2: centre + SC // 2]
    p = (np.abs(sc) ** 2).mean(axis=0).reshape(NPRB, 12).sum(axis=1)
    return 10 * np.log10(p + 1e-9)


def test_tone_lands_in_its_prb():
    s = {"noise_dbfs": -70, "components": [{"shape": "tone", "prb": 72, "amplitude_dbfs": -30}]}
    p = prb_power_db(render(s, 0.02))
    assert int(np.argmax(p)) == 72
    assert p[72] - np.median(p) > 30


def test_sweep_fills_its_band_and_little_else():
    s = {"noise_dbfs": -70, "components": [
        {"shape": "sweep", "prb": 85, "width_prb": 6, "sweep_period_us": 50, "amplitude_dbfs": -30}]}
    p = prb_power_db(render(s, 0.02))
    floor = np.median(p)
    assert all(p[k] > floor + 40 for k in range(85, 91)), p[84:92] - floor
    outside = [k for k in range(NPRB) if k < 83 or k > 92]
    assert all(p[k] < floor + 10 for k in outside)


def test_quiet_run_has_only_noise():
    s = {"noise_dbfs": -60, "components": []}
    p = prb_power_db(render(s, 0.02))
    assert p.max() - p.min() < 3


def test_noise_level_is_the_requested_one():
    s = {"noise_dbfs": -50, "components": []}
    iq = render(s, 0.02)
    rms = np.sqrt(np.mean(np.abs(iq) ** 2))
    assert abs(20 * np.log10(rms / 32767) - (-50)) < 0.5


def test_on_off_follows_the_schedule():
    s = {"noise_dbfs": -70, "components": [
        {"shape": "tone", "prb": 72, "amplitude_dbfs": -30, "start_s": 0.01, "stop_s": 0.02}]}
    iq = render(s, 0.03)
    n = int(0.01 * FS)
    seg = [np.sqrt(np.mean(np.abs(iq[i * n:(i + 1) * n]) ** 2)) for i in range(3)]
    assert seg[1] > 10 * seg[0] and seg[1] > 10 * seg[2]


def test_hop_visits_only_listed_prbs_and_changes():
    s = {"noise_dbfs": -70, "components": [
        {"shape": "tone", "amplitude_dbfs": -30,
         "hop": {"prbs": [70, 80, 90], "dwell_s": 0.01, "seed": 5}}]}
    iq = render(s, 0.1)
    n = int(0.01 * FS)
    seen = [int(np.argmax(prb_power_db(iq[i * n:(i + 1) * n]))) for i in range(10)]
    assert set(seen) <= {70, 80, 90}
    assert len(set(seen)) > 1
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_duty_cycle_gates_the_signal():
    s = {"noise_dbfs": -70, "components": [
        {"shape": "tone", "prb": 72, "amplitude_dbfs": -30,
         "duty": {"period_ms": 5, "on_ms": 2}}]}
    iq = render(s, 0.05)
    ms = int(FS * 1e-3)
    pw = np.array([np.mean(np.abs(iq[i * ms:(i + 1) * ms]) ** 2) for i in range(50)])
    on = pw[[i for i in range(50) if i % 5 < 2]]
    off = pw[[i for i in range(50) if i % 5 >= 2]]
    assert on.min() > 100 * off.max()


def test_live_protocol_against_a_fake_gnb():
    """Speaks the RF simulator wire format as the gNB server: handshake, DL blocks, reads our replies."""
    import socket
    import struct
    import threading

    fs, blk, t0 = 46080000, 23040, 17_557_862_400
    scenario = {"noise_dbfs": -60, "components": [
        {"shape": "tone", "prb": 72, "amplitude_dbfs": -30, "start_s": 0.004}]}
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got = []

    def serve():
        c, _ = srv.accept()
        c.sendall(struct.pack("<IIQII", 1, 1, t0, 0, 0) + struct.pack("<f", 0.0) + b"\0\0\0\0")
        ts = t0
        for _ in range(40):
            c.sendall(struct.pack("<IIQII", blk, 1, ts, 0, 0) + struct.pack("<f", 0.0) + bytes(blk * 4))
            ts += blk
        want = 41
        buf = b""
        while len(got) < want:
            hdr = b""
            while len(hdr) < 24:
                hdr += c.recv(24 - len(hdr))
            size, nb, rts, _, _ = struct.unpack("<IIQII", hdr)
            need = nb * 4 + size * nb * 4
            payload = b""
            while len(payload) < need:
                payload += c.recv(need - len(payload))
            got.append((size, nb, rts, payload))
        c.close()

    th = threading.Thread(target=serve)
    th.start()
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.json"
        f.write_text(json.dumps(scenario))
        subprocess.run([str(BIN), "--scenario", str(f), "--server", "127.0.0.1", "--port", str(port),
                        "--sample-rate", str(fs), "--speed", "0"], capture_output=True, timeout=30)
    th.join(timeout=10)
    assert len(got) >= 41
    assert got[0][0] == 1 and got[0][2] == t0           # answer to the handshake block
    assert [g[2] for g in got[1:4]] == [t0, t0 + blk, t0 + 2 * blk]   # same timestamps as the DL blocks
    iq = np.concatenate([np.frombuffer(g[3][4:], dtype=np.int16).astype(np.float32) for g in got[1:]])
    iq = iq[0::2] + 1j * iq[1::2]
    global FS, FFT
    FS0, FFT0 = FS, FFT
    FS, FFT = fs, 1536
    try:
        p = prb_power_db(iq[int(0.006 * fs):])
    finally:
        FS, FFT = FS0, FFT0
    assert int(np.argmax(p)) == 72


def test_duty_cycle_does_not_flood_the_ground_truth():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.json"
        f.write_text(json.dumps({"noise_dbfs": -70, "components": [
            {"id": "w", "shape": "tone", "prb": 72, "amplitude_dbfs": -40, "start_s": 0.01, "stop_s": 0.04,
             "duty": {"period_ms": 2, "on_ms": 1}}]}))
        ev = Path(d) / "e.jsonl"
        subprocess.run([str(BIN), "--scenario", str(f), "--offline-seconds", "0.05", "--events", str(ev)],
                       check=True, capture_output=True)
        states = [json.loads(x) for x in ev.read_text().splitlines() if '"state"' in x]
    assert [s["state"] for s in states] == ["on", "off"]
    assert states[0]["prbs"] == [72]
