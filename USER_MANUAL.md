# Hướng dẫn Sử dụng — Bộ Mô phỏng Mạng Hàng đợi Drive-thru (`drivethru`)

Nhóm **XX-08** (Lớp L02 — CO3007 Đánh giá Hiệu năng Hệ thống, ĐH Bách Khoa TP.HCM).

---

## 1. Yêu cầu Môi trường & Cài đặt
* **Môi trường kiểm thử chính thức:** Windows 11, CPU 4-core/8-thread, Python 3.12.10 (CPython có GIL).
* **Thư viện lõi:** 100% thư viện chuẩn Python.
* **Thư viện ngoài (dùng cho `plot_results.py`, `run_welch_warmup.py`, `analyze_step9.py`, `plot_m5_benchmark.py` và `supplementary_checks.py`; phần lõi mô phỏng và `audit_invariants.py` chỉ cần thư viện chuẩn):**
```powershell
python -m pip install matplotlib numpy
```

---

## 2. Cấu trúc Thư mục
* `bkitevsim/`: Thư viện gốc.
* `drivethru/config/`: `simulation_config.py` (`safe_bucket_width`, `DriveThruParams`), `experiment_config.py` (18 cấu hình Exp A, 53 cấu hình Exp B/C/D).
* `drivethru/core/`: `event_types.py` (6 LPID, 10 EventType), `distributions.py` (5 dòng RNG CRN), `state.py` (`CarRecord`, `StationState`, `PickupState`, `MonitorState`).
* `drivethru/models/`: `car_source.py`, `station.py` (dùng chung cho 6 mô hình đơn và Order/Payment/Kitchen), `pickup.py` (`PickupLP(StationLP)` + bảng Join đối xứng), `monitor.py` (thống kê đầu-cuối + log sự kiện tùy chọn).
* `drivethru/metrics/`: `analytical.py` (giải tích 6 mô hình đơn & xấp xỉ Fork–Join), `stats_utils.py` (CI 95% Student-t, Little's Law, phân loại SLA 3 mức `PASS`/`FAIL`/`BOUNDARY`).
* `drivethru/experiments/`: `run_single.py`, `run_hand_trace.py`, `run_welch_warmup.py`, `run_exp_a.py`, `runner.py`, `run_exp_bcd.py`, `plot_results.py`, `analyze_step9.py` (phân tích Bước 9), `audit_invariants.py` (hậu kiểm bất biến trên CSV), `supplementary_checks.py` (hai kiểm tra bổ sung: Little ở cửa sổ đo dài hơn, độ nhạy theo warm-up), cùng bộ benchmark M5 (`run_m5_benchmark.py`, `run_m5_speedup_probe.py`, `plot_m5_benchmark.py`).
* `drivethru/engines/` *(Mở rộng M5)*:
  * `sequential_engine.py`: chạy trực tiếp `drivethru/models/` trên `SequentialEventDispatcher`.
  * `coroutine_engine.py`: mô hình lai trên `BkSysCoEventLoop`, dùng các lớp bọc mỏng Composition (`CoCarSourceLP`, `CoStationLP`, `CoPickupLP`, `CoMonitorLP`) ủy quyền logic sang `drivethru/models/` và bổ sung `BkSysFuture` tại điểm Join.
  * `multithread_engine.py`: chạy trực tiếp 6 LP từ `drivethru/models/` trên 6 `threading.Thread` với `ThreadedClockCoordinator` (zero-lookahead conservative barrier).
* `tests/`: 29 bài kiểm thử tự động (`test_m1_framework.py` .. `test_m5_engines_gate.py`).
* `reports/`: Toàn bộ bảng số liệu CSV (nguồn số liệu chính thức cho báo cáo), bảng trace kiểm tay và 11 biểu đồ (`fig0` .. `fig10`), mỗi hình có bản PNG và bản PDF vector (dùng cho LaTeX).

---

## 3. Trình tự Chạy Thí nghiệm Chính (Bắt buộc — Exp A–D, Welch, Trace kiểm tay)
```powershell
# 1. Chạy trọn bộ 29 unit tests kiểm chứng (M1-M5)
python -m unittest discover -s tests -p "test_m*.py" -v

# 2. Chạy thử 1 lượt mạng Drive-thru 4 trạm
python -m drivethru.experiments.run_single

# 3. Xuất bảng trace kiểm tay ~10 xe có DROP và chờ đồ (-> reports/hand_trace_10_cars.md)
python -m drivethru.experiments.run_hand_trace

# 4. Kiểm chứng Warm-up bằng phương pháp Welch (R=60 -> reports/fig0_welch_warmup.png)
python -m drivethru.experiments.run_welch_warmup

# 5. Chạy Thí nghiệm A — Validation 6 mô hình đơn (18 cấu hình x 30 seeds -> reports/exp_a_validation.csv)
python -m drivethru.experiments.run_exp_a

# 6. Chạy Thí nghiệm B, C, D — Mạng 4 trạm (53 cấu hình, có checkpoint config_hash + .bak)
python -m drivethru.experiments.run_exp_bcd

# 7. Xuất 5 biểu đồ chính (fig1..fig5 -> reports/, mỗi hình có .png và .pdf)
python -m drivethru.experiments.plot_results

# 8. Phân tích Bước 9 từ exp_c_summary.csv và exp_bcd_raw_runs.csv (phải chạy sau bước 6):
#    -> reports/exp_c_sensitivity_anova.csv   (phân bổ phương sai có sai số SSE)
#    -> reports/exp_c_min_sla_configs.csv     (cấu hình tối thiểu đạt SLA theo λ)
#    -> reports/exp_c_little_audit.csv        (kiểm toán định luật Little, xe còn sót)
#    -> reports/exp_d_paired_crn.csv          (CI 95% ghép cặp CRN, Exp D)
#    -> reports/fig9_pareto_T_vs_Pb.(png|pdf), reports/fig10_allocation_of_variation.(png|pdf)
python -m drivethru.experiments.analyze_step9

# 9. Hậu kiểm bất biến trên dữ liệu thô (chỉ đọc CSV, chạy vài giây, phải chạy sau bước 6):
#    -> reports/audit_invariants.csv      (cân bằng dòng, thông lượng lambda_eff, định luật Little theo từng trạm và toàn hệ)
#    -> reports/audit_seeds30_exp_c.csv   (Exp C tính lại trên 30 seed chung: trạng thái SLA và cấu hình khuyến nghị)
#    Mã thoát là 1 nếu một khẳng định của báo cáo bị vi phạm.
python -m drivethru.experiments.audit_invariants

# 10. Hai kiểm tra bổ sung của báo cáo (cần numpy; chạy vài phút):
#    -> reports/supplementary_checks.csv  (Little của lượt tệ nhất ở cửa sổ đo dài hơn; độ nhạy theo warm-up 2000 so với 4000)
python -m drivethru.experiments.supplementary_checks
```

---

## 4. Phần Mở rộng Tùy chọn (M5 — So sánh 3 Kiến trúc DES & Thí nghiệm Đối chứng)
```powershell
# 1. Benchmark 1-core trên mạng Drive-thru (5 kịch bản đa t_end & lambda -> reports/exp_m5_benchmark.csv)
python -m drivethru.experiments.run_m5_benchmark

# 2. Thí nghiệm đối chứng điều kiện tăng tốc OS-thread: Zero-Lookahead, tải Python thuần (giữ GIL) và tải mã C (nhả GIL)
#    (-> reports/exp_m5_speedup_probe.csv). Lưu ý: CPython 3.12.10 luôn bật GIL ở mọi lượt chạy; nhãn "No-GIL" trong
#    CSV chỉ tải mã C tự nhả GIL, không phải bản CPython free-threaded (nhóm chưa thử bản đó).
python -m drivethru.experiments.run_m5_speedup_probe

# 3. Xuất 3 biểu đồ M5 (fig6, fig7, fig8 -> reports/)
python -m drivethru.experiments.plot_m5_benchmark
```

---

## 5. Vị trí Đầu ra & Lưu ý Tái lập
* **Nguồn số liệu chính thức (CSV):** `reports/exp_a_validation.csv`, `reports/exp_b_summary.csv`, `reports/exp_c_summary.csv`, `reports/exp_d_summary.csv`, `reports/exp_welch_warmup.csv`, `reports/exp_c_sensitivity_anova.csv`, `reports/exp_c_min_sla_configs.csv`, `reports/exp_c_little_audit.csv`, `reports/exp_d_paired_crn.csv`, `reports/audit_invariants.csv`, `reports/audit_seeds30_exp_c.csv`, `reports/supplementary_checks.csv`, `reports/exp_m5_benchmark.csv`, `reports/exp_m5_speedup_probe.csv`.
* **Bảng trace kiểm tay:** `reports/hand_trace_10_cars.md`.
* **Biểu đồ (PNG và PDF vector):** `fig0_welch_warmup`, `fig1` .. `fig5` (chính), `fig9` (Pareto T–P_b), `fig10` (phân bổ phương sai), `fig6` .. `fig8` (mở rộng M5). Tiêu đề trong hình là tiêu đề ngắn; tiêu đề đầy đủ dùng làm caption nằm trong `reports/figure_captions.md`.
* **Chạy mới hoàn toàn:** Chỉ xóa các tệp `.csv` trong `reports/` trước khi chạy, không xóa cả thư mục (`reports/diagrams/` và `reports/figure_captions.md` là tài liệu soạn tay, không do script sinh ra); nếu tham số hoặc `MODEL_CODE_VERSION` đổi, `runner.py` tự động sao lưu checkpoint cũ sang `.bak` và chạy mới.
