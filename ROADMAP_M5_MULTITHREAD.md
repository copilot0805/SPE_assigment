# M5 — Đánh giá Hiệu năng 3 Kiến trúc Thực thi Mô phỏng DES (Nhánh `multithread_dev`)

Tài liệu tổng kết toàn bộ kiến trúc, phương pháp luận 10 bước Đánh giá Hiệu năng Hệ thống (SPE), số liệu thực đo 1-core và hướng dẫn tái lập cho **Mốc M5** của nhóm **SPE-L0x-008** (CO3007 — ĐH Bách Khoa TP.HCM).

---

## 1. Phạm vi & Nguyên tắc Kỹ thuật
* **Không chỉnh sửa thư mục `bkitevsim/`:** Toàn bộ 5 lỗi của framework gốc (LadderQueue wrap-around, `create_lp` lọc `end_time` & `create_lps` ghi đè ID 0, `wait_for()` bỏ sót `_pending_events`, `_process_events_at_current_time()` nuốt Exception, circular import `queues`/`core`) đều được hóa giải ở tầng trên trong `drivethru/engines/`.
* **Tách nhánh an toàn:** Nhánh `multithread_dev` rẽ từ nhánh ổn định `sequential_dev` (M1–M4), giữ nguyên 100% logic nghiệp vụ trong `drivethru/core/`, `drivethru/models/`, `drivethru/metrics/`.
* **Ba kiến trúc thực thi so sánh trực tiếp trên cùng mạng Drive-thru 4 trạm (6 LP):**
  1. **Single-thread (`drivethru/engines/sequential_engine.py`):** `SequentialEventDispatcher` + `BkSysLogicalProcess` (1 OS thread, gọi hàm đồng bộ `handle_event()`).
  2. **Virtual Multi-thread (`drivethru/engines/coroutine_engine.py`):** `BkSysCoEventLoop` + `SafeCoLogicalProcess` + **`BkSysFuture` tại bảng Join của `CoPickupLP`** (1 OS thread, đa nhiệm hợp tác `async/await`).
  3. **OS Multi-thread (`drivethru/engines/multithread_engine.py`):** 6 `threading.Thread` thật cho 6 LP (`LP0..LP5`) + `ThreadedClockCoordinator` đồng bộ bảo thủ theo từng mốc thời gian nhỏ nhất $t_{min}$ bằng `LadderQueue` và `threading.Condition` (0 causality error, 0 deadlock).

---

## 2. Thiết kế Thí nghiệm M5 theo 10 Bước Đánh giá Hiệu năng (SPE)

| Bước PE | Nội dung triển khai tại M5 |
|---|---|
| **1. Goals & SUT** | So sánh tốc độ thực thi, tài nguyên phần cứng và độ toàn vẹn kết quả của 3 kiến trúc DES. SUT = Engine thực thi mạng Drive-thru 4 trạm (6 LP + hàng đợi sự kiện + điều phối) trên **Windows 11, CPU 4-core/8-thread, CPython 3.12.10 (có GIL)**. |
| **2. Services & Outcomes** | Dịch vụ = thực thi trọn vẹn 1 lượt mô phỏng $[0, t_{end}]$ bảo toàn nhân quả. 3 kết quả: (i) Đúng — khớp bản chuẩn; (ii) Sai — causality error/race condition; (iii) Không làm được — Deadlock/Crash. |
| **3. Metrics** | Wall-clock Time (s, LB), Event Throughput (events/sec, HB), CPU Time & tỷ số CPU/Wall (LB), Peak Python Heap Memory (MB, LB), Fidelity Error (sai lệch max trên 10 chỉ số cốt lõi, bắt buộc $< 10^{-9}$), Deadlock & Causality Error Rate (bắt buộc = 0%). |
| **4. Parameters** | Cố định: cấu hình tối ưu M4 ($c_1=c_2=c_3=c_4=2, K_1=6$), $\lambda = 0.6$ (Peak), $t_{warmup} = 500$ phút, `safe_bucket_width(t_end)`. |
| **5. Factors & Levels** | **Factor A — Kiến trúc (3 mức):** `sequential`, `coroutine`, `multithread`. **Factor B — Quy mô $t_{end}$ (3 mức):** 2 000, 5 000, 10 000 phút (tương ứng ~17.6k, ~44.3k, ~89.2k sự kiện). |
| **6. Technique** | **Measurement** trực tiếp trên chương trình thật kết hợp **Cross-validation** cùng seed với bản chuẩn `sequential`. |
| **7. Workload** | Cùng dòng sự kiện sinh từ `MultiStreamRNG` (5 luồng CRN) với `seed = 1..10` để cả 3 engine xử lý số sự kiện giống hệt nhau. |
| **8. Experimental Design** | Giai thừa đầy đủ $3 \times 3 = 9$ cấu hình $\times R=10$ seeds (+ 1 lượt warm-up `seed=999` bỏ đi). **Đo tuần tự đơn tiến trình (1 core)**, không dùng `ProcessPoolExecutor`. Tách riêng Pha 1 (`tracemalloc` tắt -> đo `wall_time`/`cpu_time` sạch observer effect) và Pha 2 (`tracemalloc` bật trên 3 seeds -> đo `peak_mem_mb`). |
| **9. Analyze & Interpret** | Mean ± CI 95% (Student-$t$, $t_{0.975,9}=2.2622$), Slowdown Ratio so với Single-thread, phân rã chi phí Coroutine frame vs. GIL + Condition barrier. |
| **10. Present Results** | Bảng `reports/exp_m5_benchmark.csv` và 2 biểu đồ `reports/fig6_m5_walltime_throughput.png`, `reports/fig7_m5_memory_and_overhead.png`. |

---

## 3. Kết quả Thực đo (1-Core, CPython 3.12.10 GIL)

Trích từ `reports/exp_m5_benchmark.csv` (90/90 lượt Timing PASS fidelity $< 10^{-9}$, 0 causality error, 0 deadlock):

| Engine | $t_{end}$ (phút) | Events (TB) | Wall Time (s) ± CI 95% | Slowdown | Throughput (ev/s) | CPU/Wall | Peak Mem (MB) | Max Fidelity Err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **sequential** | 2 000 | 17 633 | `0.3222 ± 0.0475` | **1.00x** | 56 633 | 0.975 | 0.109 | `0.0e+00` |
| **coroutine** | 2 000 | 17 633 | `0.7449 ± 0.0799` | **2.31x** | 24 087 | 0.988 | 0.136 | `0.0e+00` |
| **multithread** | 2 000 | 17 633 | `1.1559 ± 0.0811` | **3.59x** | 15 379 | 0.962 | 0.134 | `0.0e+00` |
| **sequential** | 5 000 | 44 258 | `0.6906 ± 0.0560` | **1.00x** | 64 800 | 0.976 | 0.239 | `0.0e+00` |
| **coroutine** | 5 000 | 44 258 | `1.7512 ± 0.1088` | **2.54x** | 25 418 | 0.983 | 0.255 | `0.0e+00` |
| **multithread** | 5 000 | 44 258 | `3.1330 ± 0.0986` | **4.54x** | 14 154 | 0.958 | 0.262 | `0.0e+00` |
| **sequential** | 10 000 | 89 157 | `1.2857 ± 0.0725` | **1.00x** | 69 726 | 0.986 | 0.451 | `0.0e+00` |
| **coroutine** | 10 000 | 89 157 | `3.3657 ± 0.1046` | **2.62x** | 26 529 | 0.990 | 0.468 | `0.0e+00` |
| **multithread** | 10 000 | 89 157 | `6.3266 ± 0.1306` | **4.92x** | 14 102 | 0.954 | 0.475 | `0.0e+00` |

---

## 4. Phân tích & Diễn giải Kỹ thuật (Bước 9 PE)
1. **Độ toàn vẹn tuyệt đối (Fidelity = 0.0):** Trên cả 3 quy mô ($t_{end} = 2000 \to 10000$) và cả 2 chế độ Non-blocking / Blocking, sai lệch cực đại giữa 3 kiến trúc bằng `0.0e+00` trên toàn bộ 10 chỉ số (`T, P_b, U1..U4, W_f, X, P95_T, L_system`). Thời gian ảo và kết quả mô hình hàng đợi hoàn toàn bất biến theo kiến trúc thực thi.
2. **Thứ bậc tốc độ thực tế:** $\text{Wall(Single)} < \text{Wall(Virtual/Coroutine)} \ll \text{Wall(OS-Thread)}$ ở mọi quy mô.
   * **Single-thread (`69.7k ev/s`, `1.00x`):** Mỗi sự kiện chỉ là một lời gọi hàm `handle_event()` trực tiếp trên 1 luồng, không có chi phí khung coroutine hay đồng bộ luồng.
   * **Virtual Multi-thread (`26.5k ev/s`, `2.62x`):** Chậm hơn chủ yếu do chi phí ở tầng người dùng (`CPU/Wall = 0.990`): khởi tạo `BkSysFuture` + `asyncio.Task` tại bảng Join của `CoPickupLP` và vòng nhường quyền `await asyncio.sleep(0)` trong `BkSysCoEventLoop._run_async()`. Tuy nhiên, vẫn nhanh gần **gấp đôi** OS Multi-thread.
   * **OS Multi-thread (`14.1k ev/s`, `4.92x`):** Chậm nhất và hệ số slowdown tăng dần theo quy mô (`3.59x` -> `4.54x` -> `4.92x`) vì 3 nguyên nhân cộng hưởng: (i) **CPython 3.12 GIL** tuần tự hóa thực thi bytecode của 6 luồng; (ii) **độ hạt sự kiện siêu nhỏ** (vài micro-giây/sự kiện) khiến chi phí đồng bộ `threading.Condition` barrier + chuyển ngữ cảnh nhân Windows lớn hơn nhiều lần chi phí tính toán sự kiện; (iii) tỷ số `CPU/Wall` giảm xuống `0.954` phản ánh thời gian luồng ngủ chờ khóa/tín hiệu đồng bộ.
3. **Dấu chân bộ nhớ (RAM):** Cả 3 kiến trúc đều gọn nhẹ (< 0.5 MB Python heap tại $t_{end}=10000$, chủ yếu lưu mẫu `t_samples` ở `MonitorLP`); Coroutine và OS Multi-thread chỉ tăng thêm khoảng `0.017–0.024 MB` so với Single-thread.
4. **Khuyến nghị kiến trúc DES trên Python:** Dùng **Single-thread Sequential** cho chiến dịch chạy hàng nghìn kịch bản (kết hợp `ProcessPoolExecutor` ở tầng ngoài để song song hóa theo seed độc lập như M4); dùng **Virtual Multi-thread (Coroutine)** khi cần biểu diễn tường minh luồng tiến trình/future bất đồng bộ; **không** dùng OS `threading.Thread` để song song hóa nội bộ các LP có tác vụ nhẹ trên CPython có GIL.

---

## 5. Lệnh Tái lập cho Examiner (Windows PowerShell)
```powershell
# 1. Chuyển sang nhánh M5
git checkout multithread_dev

# 2. Chạy trọn bộ 17 unit tests (M1 + M2 + M3 + M5)
python -m unittest discover -s tests -p "test_m*.py" -v

# 3. Chạy lại Benchmark 1-core (xóa CSV cũ trong reports/ nếu muốn đo mới hoàn toàn)
python -m drivethru.experiments.run_m5_benchmark

# 4. Vẽ lại 2 biểu đồ M5 (fig6 & fig7)
python -m drivethru.experiments.plot_m5_benchmark
```
