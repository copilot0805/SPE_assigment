# Hướng dẫn Sử dụng — Bộ Mô phỏng Mạng Hàng đợi Drive-thru (`drivethru`)

Nhóm **SPE-L0x-008** (Lớp L02 — CO3007 Đánh giá Hiệu năng Hệ thống, ĐH Bách Khoa TP.HCM).

---

## 1. Yêu cầu Môi trường & Cài đặt
* **Python:** 3.12+ (đã kiểm thử trên CPython 3.12.10 Windows và Python 3.13 Linux).
* **Thư viện lõi:** 100% thư viện chuẩn Python (mô phỏng chạy không cần gói ngoài).
* **Thư viện vẽ biểu đồ (chỉ cần cho `plot_results.py`, `run_welch_warmup.py`, `plot_m5_benchmark.py`):**
```powershell
python -m pip install matplotlib numpy
```

---

## 2. Cấu trúc Thư mục
* `bkitevsim/`: Thư viện gốc của giảng viên — **giữ nguyên vẹn byte-by-byte, không chỉnh sửa**.
* `drivethru/config/`: `simulation_config.py` (`safe_bucket_width`, `DriveThruParams`), `experiment_config.py` (18 cấu hình Exp A, 53 cấu hình Exp B/C/D).
* `drivethru/core/`: `event_types.py` (6 LPID, 10 EventType), `distributions.py` (5 dòng RNG CRN), `state.py` (`CarRecord`, `StationState`, `PickupState`, `MonitorState`).
* `drivethru/models/`: `car_source.py`, `station.py` (tái sử dụng cho cả 6 mô hình đơn và Order/Payment/Kitchen), `pickup.py` (`PickupLP(StationLP)` + bảng Join đối xứng), `monitor.py` (thống kê đầu-cuối + log sự kiện tùy chọn).
* `drivethru/metrics/`: `analytical.py` (công thức giải tích 6 mô hình đơn & xấp xỉ Fork–Join), `stats_utils.py` (CI 95% Student-t, Little's Law, phân loại SLA 3 mức `PASS`/`FAIL`/`BOUNDARY`).
* `drivethru/experiments/`: `run_single.py`, `run_hand_trace.py`, `run_welch_warmup.py`, `run_exp_a.py`, `runner.py`, `run_exp_bcd.py`, `plot_results.py`, cùng bộ benchmark M5 (`run_m5_benchmark.py`, `plot_m5_benchmark.py`).
* `drivethru/engines/` *(Mở rộng M5)*: 3 kiến trúc thực thi (`sequential_engine.py`, `coroutine_engine.py` bọc trực tiếp `models/` + `BkSysFuture` tại bảng Join, `multithread_engine.py` 6 OS threads + `ThreadedClockCoordinator`).
* `tests/`: 26 bài kiểm thử tự động (`test_m1_framework.py` .. `test_m5_engines_gate.py`).
* `reports/`: Toàn bộ bảng số liệu CSV (nguồn số liệu chính thức cho báo cáo), bảng trace tay và biểu đồ PNG.

---

## 3. Trình tự Chạy Thí nghiệm Chính (Bắt buộc — Exp A–D, Welch, Trace tay)
Chạy từ thư mục gốc của dự án:

```powershell
# 1. Chạy trọn bộ 26 unit tests kiểm chứng (M1-M5, ~45 giây)
python -m unittest discover -s tests -p "test_m*.py" -v

# 2. Chạy thử 1 lượt mạng Drive-thru 4 trạm (~1 giây)
python -m drivethru.experiments.run_single

# 3. Xuất bảng trace kiểm tay ~10 xe có DROP và chờ đồ (~0.5 giây -> reports/hand_trace_10_cars.md)
python -m drivethru.experiments.run_hand_trace

# 4. Kiểm chứng Warm-up bằng phương pháp Welch (R=60 seeds, ~25 giây -> reports/fig0_welch_warmup.png)
python -m drivethru.experiments.run_welch_warmup

# 5. Chạy Thí nghiệm A — Validation 6 mô hình đơn (18 cấu hình x 30 seeds, ~2-3 phút -> reports/exp_a_validation.csv)
python -m drivethru.experiments.run_exp_a

# 6. Chạy Thí nghiệm B, C, D — Mạng 4 trạm (53 cấu hình, có checkpoint config_hash, ~10-12 phút)
python -m drivethru.experiments.run_exp_bcd

# 7. Xuất 5 biểu đồ chính (fig1..fig5 -> reports/)
python -m drivethru.experiments.plot_results
```

---

## 4. Phần Mở rộng Tùy chọn (M5 — So sánh 3 Kiến trúc DES)
Đo tuần tự đơn tiến trình (1 core) trên 5 kịch bản (đa mức $t_{end}$ và đa mức $\lambda$), kiểm chứng sai lệch **từng xe một** $< 10^{-9}$, đo Python Heap + OS RSS + tỷ lệ epoch 1-LP:

```powershell
# Chạy benchmark 1-core (có checkpoint -> reports/exp_m5_benchmark.csv)
python -m drivethru.experiments.run_m5_benchmark

# Xuất 2 biểu đồ M5 (fig6 & fig7 -> reports/)
python -m drivethru.experiments.plot_m5_benchmark
```

---

## 5. Vị trí Đầu ra & Lưu ý Tái lập
* **Nguồn số liệu chính thức (CSV):** `reports/exp_a_validation.csv`, `reports/exp_b_summary.csv`, `reports/exp_c_summary.csv`, `reports/exp_d_summary.csv`, `reports/exp_welch_warmup.csv`, `reports/exp_m5_benchmark.csv`.
* **Bảng trace tay:** `reports/hand_trace_10_cars.md`.
* **Biểu đồ PNG:** `fig0_welch_warmup.png`, `fig1` .. `fig5` (chính), `fig6` .. `fig7` (mở rộng M5).
* **Chạy mới hoàn toàn:** Xóa thư mục `reports/` trước khi chạy; nếu tham số hoặc `MODEL_CODE_VERSION` đổi, `runner.py` tự động sao lưu checkpoint cũ sang `.bak` và chạy mới.
