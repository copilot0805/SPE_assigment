import bkitevsim.core  # Né Lỗi 5

import csv
import gc
import hashlib
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bkitevsim.core import BkSysLogicalProcess, Event, Simulation, SimulationOptions
from drivethru.config.simulation_config import safe_bucket_width
from drivethru.engines.multithread_engine import ThreadedClockCoordinator
from drivethru.engines.safe_co_base import SafeCoLogicalProcess, check_and_raise_errors
from drivethru.metrics.stats_utils import compute_ci95

REPORTS_DIR = Path("reports")
OUT_CSV = REPORTS_DIR / "exp_m5_speedup_probe.csv"

NUM_LPS = 6
REPS = 5

# (regime_id, label, synchronized_6lp, workload_kind, num_epochs)
REGIMES: Tuple[Tuple[str, str, bool, str, int], ...] = (
    ("R1_zero_lookahead_light", "Zero-Lookahead (1 LP/nhịp) + Python nhẹ", False, "light_py", 2000),
    ("R2_pos_lookahead_py_gil", "Lookahead dương (6 LP/nhịp) + Python nặng (GIL)", True, "heavy_py_gil", 30),
    ("R3_pos_lookahead_nogil_c", "Lookahead dương (6 LP/nhịp) + C/OpenSSL (No-GIL)", True, "heavy_c_nogil", 30),
)


def _do_event_work(workload_kind: str, lp_id: int, step: int) -> int:
    if workload_kind == "light_py":
        return (lp_id * 131 + step * 17) & 0xFFFFFFFF
    if workload_kind == "heavy_py_gil":
        acc = (lp_id + 1) * 1009 + step
        for i in range(45000):
            acc = (acc + i * 31) & 0xFFFFFFFF
        return acc
    if workload_kind == "heavy_c_nogil":
        # hashlib.pbkdf2_hmac gọi OpenSSL C và giải phóng GIL trong CPython 3.12
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            f"lp{lp_id}-step{step}".encode("ascii"),
            b"co3007_spe_probe",
            25000,
        )
        return int.from_bytes(digest[:4], "big")
    raise ValueError(f"Unknown workload_kind: {workload_kind}")


class ProbeSyncLP(BkSysLogicalProcess):
    def __init__(self, lp_id: int, num_epochs: int, synchronized: bool, workload_kind: str):
        super().__init__(lp_id)
        self.num_epochs = num_epochs
        self.synchronized = synchronized
        self.workload_kind = workload_kind
        self.checksum: int = 0
        self.count: int = 0

    def initialize(self) -> None:
        t0 = 0.0 if self.synchronized else 0.1 * self.lp_id
        self.send_event(Event(t0, self.lp_id, self.lp_id, "WORK", payload=0))

    def handle_event(self, event: Event) -> None:
        step = int(event.payload)
        self.local_virt_time = event.timestamp
        self.checksum ^= _do_event_work(self.workload_kind, self.lp_id, step)
        self.count += 1
        if step + 1 < self.num_epochs:
            self.send_event(Event(event.timestamp + 1.0, self.lp_id, self.lp_id, "WORK", payload=step + 1))


class ProbeCoLP(SafeCoLogicalProcess):
    def __init__(self, lp_id: int, num_epochs: int, synchronized: bool, workload_kind: str, t_end: float, error_sink):
        self._inner = ProbeSyncLP(lp_id, num_epochs, synchronized, workload_kind)
        super().__init__(lp_id=lp_id, t_end=t_end, error_sink=error_sink)
        self._inner.send_event = self.send_event

    @property
    def checksum(self) -> int:
        return self._inner.checksum

    def initialize(self) -> None:
        self._inner.initialize()

    def on_event_safe(self, event: Event) -> None:
        self.local_virt_time = event.timestamp
        self._inner.handle_event(event)


def _run_probe(engine: str, synchronized: bool, workload_kind: str, num_epochs: int) -> Dict[str, Any]:
    t_end = float(num_epochs + 5)
    bw = safe_bucket_width(t_end)
    gc.collect()
    t0 = time.perf_counter()
    c0 = time.process_time()

    if engine == "sequential":
        sim = Simulation(
            SimulationOptions(end_time=t_end, dispatcher="sequential", bucket_width=bw, log_level="ERROR"),
            models={"Probe": ProbeSyncLP},
        )
        lps = [
            sim.create_lp(i, "Probe", num_epochs=num_epochs, synchronized=synchronized, workload_kind=workload_kind)
            for i in range(NUM_LPS)
        ]
        st = sim.run()
        avg_act, pct_1lp, evs = 1.0, 100.0, int(st["events_processed"])
        checksums = tuple(lp.checksum for lp in lps)

    elif engine == "coroutine":
        sink: List[Exception] = []
        sim = Simulation(
            SimulationOptions(end_time=t_end, dispatcher="coroutine", bucket_width=bw, log_level="ERROR"),
            models={"ProbeCo": ProbeCoLP},
        )
        lps = [
            sim.create_lp(
                i, "ProbeCo", num_epochs=num_epochs, synchronized=synchronized,
                workload_kind=workload_kind, t_end=t_end, error_sink=sink,
            )
            for i in range(NUM_LPS)
        ]
        st = sim.run()
        check_and_raise_errors(sink, context="ProbeCo")
        avg_act, pct_1lp, evs = 1.0, 100.0, int(st["events_processed"])
        checksums = tuple(lp.checksum for lp in lps)

    elif engine == "multithread":
        lps_dict = {
            i: ProbeSyncLP(i, num_epochs=num_epochs, synchronized=synchronized, workload_kind=workload_kind)
            for i in range(NUM_LPS)
        }
        coord = ThreadedClockCoordinator(lps=lps_dict, end_time=t_end, bucket_width=bw)
        st = coord.run()
        assert st["causality_violations"] == 0 and not st["deadlocked"]
        avg_act = st["avg_active_lps_per_epoch"]
        pct_1lp = st["pct_single_lp_epochs"]
        evs = int(st["events_processed"])
        checksums = tuple(lps_dict[i].checksum for i in range(NUM_LPS))
    else:
        raise ValueError(engine)

    cpu_t = time.process_time() - c0
    wall_t = max(1e-12, time.perf_counter() - t0)
    return {
        "wall_time": wall_t,
        "cpu_time": cpu_t,
        "cpu_wall_ratio": cpu_t / wall_t,
        "events_processed": evs,
        "avg_active_lps": avg_act,
        "pct_single_lp": pct_1lp,
        "checksums": checksums,
    }


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 116)
    print("M5 CONTROLLED SPEEDUP PROBE — KIỂM CHỨNG ĐIỀU KIỆN ĐỂ OS-THREAD NHANH HƠN SINGLE-THREAD")
    print(f"Python: {platform.python_version()} | OS: {platform.platform()} | LPs={NUM_LPS} | R={REPS} reps")
    print("=" * 116)
    print(
        f"{'Regime':<26} | {'Engine':<11} | {'Events':>6} | {'Wall (s) ± CI95':>18} | "
        f"{'Speedup':>8} | {'CPU/Wall':>8} | {'ActLP':>5} | {'1LP%':>5} | {'Match':>5}"
    )
    print("-" * 116)

    rows: List[Dict[str, Any]] = []
    for reg_id, reg_label, sync_6lp, wk_kind, n_epochs in REGIMES:
        # Warm-up 1 lượt bỏ đi
        ref_checksums = _run_probe("sequential", sync_6lp, wk_kind, n_epochs)["checksums"]
        seq_wall_mean = 0.0

        for eng in ("sequential", "coroutine", "multithread"):
            reps_data = [_run_probe(eng, sync_6lp, wk_kind, n_epochs) for _ in range(REPS)]
            all_match = all(d["checksums"] == ref_checksums for d in reps_data)
            assert all_match, f"Checksum mismatch ở {reg_id} / {eng}!"

            ci_w = compute_ci95([d["wall_time"] for d in reps_data])
            ci_r = compute_ci95([d["cpu_wall_ratio"] for d in reps_data])
            if eng == "sequential":
                seq_wall_mean = ci_w["mean"]
            speedup = seq_wall_mean / ci_w["mean"] if ci_w["mean"] > 0 else 1.0
            evs = reps_data[0]["events_processed"]
            act_lp = reps_data[0]["avg_active_lps"]
            pct_1 = reps_data[0]["pct_single_lp"]

            rows.append({
                "regime_id": reg_id,
                "regime_label": reg_label,
                "engine_name": eng,
                "n_reps": REPS,
                "events_processed": evs,
                "wall_time_mean": ci_w["mean"],
                "wall_time_ci95": ci_w["half_width"],
                "speedup_vs_seq": speedup,
                "cpu_wall_ratio_mean": ci_r["mean"],
                "avg_active_lps": act_lp,
                "pct_single_lp_epochs": pct_1,
                "checksum_match": int(all_match),
            })
            print(
                f"{reg_id:<26} | {eng:<11} | {evs:6d} | "
                f"{ci_w['mean']:7.4f} ± {ci_w['half_width']:7.4f} | "
                f"{speedup:7.2f}x | {ci_r['mean']:8.2f} | {act_lp:5.1f} | {pct_1:5.1f} | {'OK':>5}"
            )
        print("-" * 116)

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] Đã xuất bảng thí nghiệm đối chứng: {OUT_CSV}")


if __name__ == "__main__":
    main()
