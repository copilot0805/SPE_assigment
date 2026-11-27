import csv
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from drivethru.config.simulation_config import DriveThruParams
from drivethru.experiments.run_single import run_drivethru_network

REPORTS_DIR = Path("reports")
N_WORKERS = 4
T_CRIT_39 = 2.0227   # t(0.975, 39) cho R = 40 seed


def _warm(a):
    lam, c2, seed, wu = a
    r = run_drivethru_network(DriveThruParams(lam=lam, c2=c2, K1=8, t_warmup=wu, t_end=12000.0),
                              seed=seed, verify_invariants=False)
    return r["T"], r["W2"], r["L2"]


def main():
    rows = []
    for tend in (10000.0, 40000.0, 160000.0):
        r = run_drivethru_network(DriveThruParams(lam=0.7, c2=1, K1=8, t_warmup=2000.0, t_end=tend), seed=48)
        rows.append(dict(check="little_window", scenario="lam0.7_c2_1_K1_8_seed48", param=f"t_end={int(tend)}",
                         metric="little_err_s2_pct", value=round(r["little_err_s2"] * 100, 4)))
        rows.append(dict(check="little_window", scenario="lam0.7_c2_1_K1_8_seed48", param=f"t_end={int(tend)}",
                         metric="little_err_sys_pct", value=round(r["little_err_sys"] * 100, 4)))
    for lam, c2 in ((0.7, 1), (0.6, 1)):
        res = {}
        with ProcessPoolExecutor(N_WORKERS) as ex:
            for wu in (2000.0, 4000.0):
                res[wu] = np.array(list(ex.map(_warm, [(lam, c2, s, wu) for s in range(1, 41)])))
        d = res[2000.0] - res[4000.0]
        n = len(d)
        for i, nm in enumerate(("T", "W2", "L2")):
            m = d[:, i].mean()
            hw = T_CRIT_39 * d[:, i].std(ddof=1) / n ** 0.5
            base = res[4000.0][:, i].mean()
            for metric, val in ((f"{nm}_mean_warmup2000", res[2000.0][:, i].mean()), (f"{nm}_mean_warmup4000", base),
                                (f"{nm}_paired_diff", m), (f"{nm}_paired_hw95", hw), (f"{nm}_paired_diff_pct", m / base * 100)):
                rows.append(dict(check="warmup_sens", scenario=f"lam{lam}_c2_{c2}_K1_8", param="R=40,t_end=12000",
                                 metric=metric, value=round(float(val), 4)))
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / "supplementary_checks.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["check", "scenario", "param", "metric", "value"])
        w.writeheader()
        w.writerows(rows)
    print("OK ->", out)


if __name__ == "__main__":
    main()
