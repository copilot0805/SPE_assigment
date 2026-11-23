# Hướng dẫn Kiểm định & Chấm chéo dành cho Examiner (CO3007 — Nhóm SPE-L0x-008)

Tài liệu cập nhật cho phiên bản hợp nhất hoàn chỉnh (**M1–M4 cốt lõi + Mở rộng M5**), đo trên môi trường **Windows 11, CPU 4-core/8-thread, CPython 3.12.10**, bảo đảm `bkitevsim/` gốc của giảng viên giữ nguyên vẹn byte-by-byte.

---

## 1. Tổng quan Trạng thái Hiện thực
* **Bộ kiểm thử tự động:** **29/29 unit tests PASS** (`test_m1_framework.py`: 3, `test_m2_station_gate.py`: 2, `test_m3_network_gate.py`: 7, `test_m4_review_guards.py`: 11, `test_m5_engines_gate.py`: 6).
* **Tài liệu đi kèm:**
  * `USER_MANUAL.md`: Hướng dẫn cài đặt, chạy từng lệnh và tra cứu đầu ra.
  * `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md`: Sơ đồ kiến trúc, sơ đồ lớp, tóm tắt workload/thí nghiệm và bảng đính chính Bảng 7 (`safe_bucket_width`).
  * `ROADMAP_M5_MULTITHREAD.md`: Phân tích 10 bước PE cho 3 kiến trúc DES (mô hình lai Coroutine, giới hạn zero-lookahead ~82% nhịp 1 LP, thí nghiệm đối chứng tăng tốc OS-thread `fig8` và car-by-car fidelity).

---

## 2. Các Cơ chế Đảm bảo Chất lượng (Verification & Validation)
1. **Chống wrap-around `LadderQueue`:** Dùng `safe_bucket_width(t_end)` cho mọi thí nghiệm; `test_m1_framework.py` (`test_3`) dùng 30 chuỗi TICK đồng thời chứng minh `bucket_width=1.0` gây thời gian đi lùi còn `safe_bucket_width` bằng 0.
2. **Chốt chặn thời gian không giảm lúc chạy:** Chốt cục bộ trong từng LP (`_last_handled_time`) + chốt toàn cục liên-LP (`attach_global_monotonic_guard` trong `run_single.py` và `run_exp_a.py`).
3. **Fail-fast & Cân bằng dòng:** Kiểm tra cân bằng dòng xe + đơn bếp và `unmatched_food_ready_count` (ném `RuntimeError` nếu lệch ở chế độ Blocking).
4. **Trace kiểm tay ~10 xe & Event Log:** `run_hand_trace.py` xuất `reports/hand_trace_10_cars.md` có đủ ca `DROP` và ca chờ đồ `W_f > 0`, kiểm khớp công thức tay $< 10^{-12}$ và log đủ 100% sự kiện đơn điệu qua `MonitorLP.log_event()`.
5. **Kiểm chứng Warm-up (Welch):** `run_welch_warmup.py` ($R=60$, bỏ $w$ bin mép phải) chứng minh $t_{warmup} = 2\,000$ phút dư an toàn -> `reports/fig0_welch_warmup.png`.
6. **Checkpoint an toàn & Độ chính xác CI 95%:** `runner.py` băm SHA-256 cả `MODEL_CODE_VERSION` lẫn `DriveThruParams` thành `config_hash` (tự sao lưu `.bak` nếu lệch hash), kiểm tra nửa độ rộng CI 95% $\le 5$% trên toàn bộ `U, L, W, T` và $\le 0.3$ điểm phần trăm cho `P_b`, đồng thời phân loại SLA 3 trạng thái **`PASS` / `FAIL` / `BOUNDARY`** (tự mở rộng seed khi Peak ở `BOUNDARY`).
7. **Không trùng module chuẩn:** Đã đổi `statistics.py` -> `drivethru/metrics/stats_utils.py`.

---

## 3. Lệnh Kiểm tra nhanh cho Examiner (PowerShell)
```powershell
# 1. Xác nhận bkitevsim/ không bị sửa đổi
git diff --stat main -- bkitevsim/

# 2. Chạy toàn bộ 29 unit tests (M1-M5)
python -m unittest discover -s tests -p "test_m*.py" -v

# 3. Tái lập các thí nghiệm chính (nên xóa reports/ trước khi chạy mới)
python -m drivethru.experiments.run_hand_trace
python -m drivethru.experiments.run_welch_warmup
python -m drivethru.experiments.run_exp_a
python -m drivethru.experiments.run_exp_bcd
python -m drivethru.experiments.plot_results

# 4. (Tùy chọn) Tái lập mở rộng M5 & thí nghiệm đối chứng tăng tốc OS-thread
python -m drivethru.experiments.run_m5_benchmark
python -m drivethru.experiments.run_m5_speedup_probe
python -m drivethru.experiments.plot_m5_benchmark
```

---

## 4. Điểm lưu ý khi đọc Kết quả Exp C (Peak $\lambda = 0.6$)
* Báo cáo tách bạch hai góc nhìn theo §2.6 và §3.3.1:
  * **Cấu hình nhỏ nhất đạt cả 2 ngưỡng SLA ($\overline{T} \le 8$ phút, $P_b \le 5$%):** `c2 = 1, K1 = 4` (nhờ hiệu ứng ~3.2% xe bị từ chối tại Order giảm tải vào Payment).
  * **Cấu hình khuyến nghị vận hành ổn định:** `c2 = 2, K1 = 6` (loại bỏ nút cổ chai Payment, giảm $P_b$ xuống ~0.63%, giữ $U_2 < 0.8$ và đạt SLA ngay cả ở kịch bản Heavy $\lambda = 0.7$).
