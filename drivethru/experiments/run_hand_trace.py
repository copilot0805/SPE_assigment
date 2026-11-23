from pathlib import Path
from typing import Any, Dict, List, Tuple

from drivethru.config.simulation_config import DriveThruParams
from drivethru.experiments.run_single import run_drivethru_network


def find_hand_trace_scenario() -> Tuple[DriveThruParams, int, Dict[str, Any]]:
    """
    Tìm seed nhỏ nhất tạo ~10 xe (8..14 xe) với sức chứa Order K1=3 để đảm bảo có:
    - Ít nhất 1 xe bị từ chối (DROP) tại Order
    - Ít nhất 1 xe phải chờ đồ tại bảng Join (W_f > 0)
    - Ít nhất 1 xe đồ xong trước xe (W_f == 0)
    """
    params = DriveThruParams(
        lam=1.0, c1=2, K1=3, mean_s1=1.5,
        c2=2, mean_s2=1.25, c3=2, mean_s3=2.0, c4=2, mean_s4=1.0,
        t_warmup=0.0, t_end=12.0, blocking_order=False,
    )
    for seed in range(1, 200):
        res = run_drivethru_network(
            params, seed=seed, verify_invariants=True,
            record_trace=True, record_event_log=True,
        )
        n_gen = res["total_generated"]
        recs = res["car_records"]
        drops = [c for st, _t, c in recs if st == "DROPPED"]
        comps = [c for st, _t, c in recs if st == "COMPLETED"]
        waited_food = [c for c in comps if c.food_wait_time > 1e-9]
        no_wait_food = [c for c in comps if c.food_wait_time <= 1e-9]
        if 9 <= n_gen <= 13 and len(drops) >= 1 and len(waited_food) >= 1 and len(no_wait_food) >= 1:
            return params, seed, res
    raise RuntimeError("Không tìm thấy seed phù hợp cho trace kiểm tay 10 xe!")


def verify_and_export_hand_trace(out_md: Path = Path("reports/hand_trace_10_cars.md")) -> Dict[str, Any]:
    params, seed, res = find_hand_trace_scenario()
    recs = sorted(res["car_records"], key=lambda x: x[2].car_id)
    ev_log = res["event_log"]

    # 1. Kiểm chứng tính đơn điệu toàn bộ event_log do MonitorLP ghi
    assert len(ev_log) == res["events_processed"], "event_log không khớp tổng số event đã xử lý!"
    for i in range(1, len(ev_log)):
        assert ev_log[i][0] >= ev_log[i - 1][0] - 1e-12, "event_log có timestamp đi lùi!"

    # 2. Kiểm chứng từng xe bằng công thức tay
    lines: List[str] = [
        "# Trace Kiểm Tay ~10 Xe (Verification — Mục 1.9 Thiết kế V2)\n",
        f"- **Cấu hình:** `lam={params.lam}, c1={params.c1}, K1={params.K1}, c2={params.c2}, c3={params.c3}, c4={params.c4}, t_end={params.t_end}, seed={seed}`",
        f"- **Tổng quan:** Sinh `{res['total_generated']}` xe | Hoàn thành `{res['total_completed']}` | Bị từ chối (DROP) `{res['total_dropped']}` | Chưa xong `{res['n_unfinished_total']}` | Tổng event log: `{len(ev_log)}` (100% không giảm)\n",
        "| car_id | Kết quả | t_arrive | Order [vào -> xong] | Payment xong (t_p) | Bếp xong (t_f) | Chờ đồ W_f | Pickup [vào -> rời] | Tổng T | Khớp tay |",
        "|---:|---|---:|---|---:|---:|---:|---|---:|---|",
    ]

    for status, t_done, car in recs:
        if status == "DROPPED":
            assert abs(t_done - car.t_arrive) < 1e-12
            assert 2 not in car.t_enter and 3 not in car.t_enter and 4 not in car.t_enter
            lines.append(
                f"| {car.car_id} | **DROP** | {car.t_arrive:.3f} | Đầy K1={params.K1} | — | — | — | — | — | OK |"
            )
            continue

        # COMPLETED: kiểm tra từng phương trình thời gian bằng tay
        t_ord_in, t_ord_st, t_ord_end = car.t_enter[1], car.t_start[1], car.t_end[1]
        t_pay_in, t_pay_st, t_pay_end = car.t_enter[2], car.t_start[2], car.t_end[2]
        t_p, t_f = car.t_payment_done, car.t_food_ready
        t_pk_in, t_pk_st, t_pk_end = car.t_enter[4], car.t_start[4], car.t_end[4]

        assert abs(t_ord_in - car.t_arrive) < 1e-12
        assert abs(t_ord_end - (t_ord_st + car.service_times[1])) < 1e-12
        assert abs(t_pay_in - t_ord_end) < 1e-12
        assert abs(t_pay_end - (t_pay_st + car.service_times[2])) < 1e-12
        assert abs(t_p - t_pay_end) < 1e-12
        assert abs(t_pk_in - max(t_p, t_f)) < 1e-12
        assert abs(car.food_wait_time - max(0.0, t_f - t_p)) < 1e-12
        assert abs(t_pk_end - (t_pk_st + car.service_times[4])) < 1e-12
        assert abs(t_done - t_pk_end) < 1e-12
        t_total = t_pk_end - car.t_arrive
        t_decomp = (t_ord_end - car.t_arrive) + max(t_p - t_ord_end, t_f - t_ord_end) + (t_pk_end - t_pk_in)
        assert abs(t_total - t_decomp) < 1e-12

        wf_tag = f"**{car.food_wait_time:.3f}**" if car.food_wait_time > 1e-9 else "0.000"
        lines.append(
            f"| {car.car_id} | COMPLETED | {car.t_arrive:.3f} | "
            f"{t_ord_in:.3f} -> {t_ord_end:.3f} | {t_p:.3f} | {t_f:.3f} | "
            f"{wf_tag} | {t_pk_in:.3f} -> {t_pk_end:.3f} | {t_total:.3f} | OK |"
        )

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[OK] Đã lưu bảng trace kiểm tay tại: {out_md}")
    return {"seed": seed, "n_generated": res["total_generated"], "n_events": len(ev_log), "out_md": str(out_md)}


if __name__ == "__main__":
    verify_and_export_hand_trace()
