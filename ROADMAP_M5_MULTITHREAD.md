# M5 — Mở rộng So sánh 3 Kiến trúc Thực thi DES (Nhánh `multithread_dev`)

Tài liệu phân tích hiệu năng phần cứng của **3 kiến trúc Engine DES** trên bài toán Drive-thru 4 trạm theo 10 bước PE, đo trên môi trường **Windows 11, CPU 4-core/8-thread, CPython 3.12.10 (có GIL)** của nhóm **SPE-L0x-008**.

---

## 1. Ba Kiến trúc Engine So sánh (Không sửa `bkitevsim/`)
1. **Single-thread (`sequential_engine.py`):** Chạy trực tiếp 4 lớp `CarSourceLP`, `StationLP`, `PickupLP`, `MonitorLP` trong `drivethru/models/` trên `SequentialEventDispatcher` (1 OS thread).
2. **Virtual Multi-thread (`coroutine_engine.py` — Mô hình lai):** Chạy trên `BkSysCoEventLoop` (1 OS thread). Các lớp bọc mỏng theo mẫu **Composition** (`CoCarSourceLP`, `CoStationLP`, `CoPickupLP`, `CoMonitorLP` kế thừa `SafeCoLogicalProcess`) ủy quyền logic hàng đợi và thống kê sang thực thể `models/` bên trong (không nhân bản mã nguồn nghiệp vụ).
   * *Ghi nhận trung thực về kiến trúc:* Đây là **mô hình lai** — trạng thái trạm vẫn xử lý theo cơ chế event-handler (`handle_event`), kết hợp đa nhiệm hợp tác của `BkSysCoEventLoop` và dùng **`BkSysFuture` + `asyncio.Task` tại bảng Join của `CoPickupLP`**. Đây không phải biến thể thuần hướng tiến trình (mỗi xe là một coroutine độc lập dùng `asyncio.gather(payment, kitchen)`).
3. **OS Multi-thread (`multithread_engine.py`):** Chạy trực tiếp 6 thực thể LP từ `drivethru/models/` trên 6 `threading.Thread` riêng biệt, điều phối bởi `ThreadedClockCoordinator` theo giao thức đồng bộ bảo thủ không có lookahead (*zero-lookahead conservative barrier*), bảo đảm 0 causality error và 0 deadlock.

---

## 2. Thiết kế Đo Đạc M5 (Đa mức $t_{end}$, Đa mức $\lambda$, Car-by-Car Fidelity)
* **5 kịch bản Drive-thru đo tuần tự 1-core (`run_m5_benchmark.py`, $R = 10$ seeds):**
  * Trục quy mô sự kiện (Peak $\lambda = 0.6$): $t_{end} \in \{2\,000, 5\,000, 10\,000\}$ phút.
  * Trục cường độ tải ($t_{end} = 5\,000$): $\lambda \in \{0.2, 0.6, 0.7\}$ xe/phút.
* **Chỉ số đo:** `wall_time`, `cpu_time`, `events/sec` (Pha 1 tắt `tracemalloc` để tránh observer effect), `peak_mem_mb` (Pha 2 bật `tracemalloc` đo **Python Heap Peak**), `pct_single_lp_epochs`, `avg_active_lps_per_epoch`, và **car-by-car trace fidelity (`< 1e-9`)**.
* **Giới hạn đo bộ nhớ đã biết:** `tracemalloc` chỉ theo dõi cấp phát trên Python heap (~0.45–0.48 MB tại $t_{end} = 10\,000$), không tính dung lượng stack cấp phát ở mức hệ điều hành cho 6 OS threads.
* **Đầu ra:** `reports/exp_m5_benchmark.csv`, `reports/fig6_m5_walltime_throughput.png`, `reports/fig7_m5_memory_and_overhead.png`.

---

## 3. Phân tích Nguyên nhân & Thí nghiệm Đối chứng Điều kiện Tăng tốc OS-Thread
1. **Độ toàn vẹn tuyệt đối (Car-by-Car Fidelity = 0.0):** Trên cả 5 kịch bản (và kiểm thử bổ sung Blocking/Simultaneous Join), quỹ đạo từng xe và toàn bộ 10 chỉ số tổng hợp đều khớp `0.0e+00`, 0 causality error, 0 deadlock.
2. **Vì sao OS Multi-thread chậm hơn (~4.3x–5.1x) trên mạng Drive-thru:**
   * **Giới hạn cấu trúc zero-lookahead (nguyên nhân gốc):** Do thời gian đến và phục vụ phân phối mũ liên tục, rất hiếm khi 2 sự kiện độc lập trùng timestamp. Phép đo từ `ThreadedClockCoordinator` cho thấy **~82% nhịp đồng bộ chỉ có đúng 1 LP hoạt động**, trung bình chỉ **~1.2 LP/nhịp** — trần tăng tốc lý thuyết chỉ khoảng **1.2x** ngay cả trước khi tính chi phí đồng bộ và GIL.
   * **Độ hạt sự kiện siêu nhỏ & CPython GIL:** Mỗi sự kiện Drive-thru tốn vài micro-giây Python, nhỏ hơn nhiều chi phí `threading.Condition` barrier, chuyển ngữ cảnh OS và tranh chấp GIL trên CPython 3.12.
3. **Thí nghiệm đối chứng tách biệt Zero-Lookahead vs. GIL (`run_m5_speedup_probe.py`, `fig8_m5_speedup_conditions.png`):**
   Chạy chính `ThreadedClockCoordinator` (6 OS threads) so với `SequentialEventDispatcher` và `BkSysCoEventLoop` trên 3 chế độ tải có kiểm soát (đo trên máy Windows 11, CPU 4-core/8-thread, CPython 3.12.10):

| Chế độ kiểm chứng | Kiến trúc | Wall Time (s) ± CI 95% | Speedup vs Single | CPU/Wall | ActLP | 1LP% | Khớp Checksum |
|---|---|---:|---:|---:|---:|---:|---|
| Zero-Lookahead (1 LP/nhịp) + Python nhẹ | **sequential** | `0.1896 ± 0.0614` | **1.00x** | 1.01 | 1.0 | 100.0% | OK |
| Zero-Lookahead (1 LP/nhịp) + Python nhẹ | **coroutine** | `1.0844 ± 0.2010` | **0.17x** | 0.98 | 1.0 | 100.0% | OK |
| Zero-Lookahead (1 LP/nhịp) + Python nhẹ | **multithread** | `1.3611 ± 0.1302` | **0.14x** | 0.98 | 1.0 | 100.0% | OK |
| Lookahead dương (6 LP/nhịp) + Python nặng (GIL) | **sequential** | `1.7417 ± 0.6719` | **1.00x** | 0.95 | 1.0 | 100.0% | OK |
| Lookahead dương (6 LP/nhịp) + Python nặng (GIL) | **coroutine** | `1.2020 ± 0.2418` | **1.45x** | 0.98 | 1.0 | 100.0% | OK |
| Lookahead dương (6 LP/nhịp) + Python nặng (GIL) | **multithread** | `1.3234 ± 0.3895` | **1.32x** | 0.99 | 6.0 | 0.0% | OK |
| Lookahead dương (6 LP/nhịp) + C/OpenSSL (No-GIL) | **sequential** | `6.2945 ± 1.0641` | **1.00x** | 0.98 | 1.0 | 100.0% | OK |
| Lookahead dương (6 LP/nhịp) + C/OpenSSL (No-GIL) | **coroutine** | `6.1642 ± 0.4448` | **1.02x** | 0.98 | 1.0 | 100.0% | OK |
| Lookahead dương (6 LP/nhịp) + C/OpenSSL (No-GIL) | **multithread** | `2.1420 ± 0.1239` | **2.94x** | 5.27 | 6.0 | 0.0% | OK |

* **Kết luận thực nghiệm:**
  * Ở **Chế độ 1 (Zero-lookahead, nhẹ):** OS-thread chậm hơn nhiều (Speedup $< 1.0	imes$) tương đồng hành vi mạng Drive-thru.
  * Ở **Chế độ 2 (Lookahead dương 6 LP đồng thời, tải Python nặng giữ GIL):** Dù 100% nhịp đều có 6 LP chạy song song, `CPU/Wall` vẫn bị khóa quanh `1.0` do **CPython 3.12 GIL** nên OS-thread vẫn không nhanh hơn Single-thread.
  * Ở **Chế độ 3 (Lookahead dương 6 LP đồng thời, tải C/OpenSSL giải phóng GIL):** Chính `ThreadedClockCoordinator` khai thác được đa nhân (`CPU/Wall > 2.5`) và đạt **Speedup thực sự vượt trội so với Single-thread** (trong khi Coroutine 1 luồng vẫn giữ $pprox 1.0	imes$).
  * Do đó, khuyến nghị không dùng OS `threading.Thread` chỉ áp dụng cho **thiết kế bảo thủ zero-lookahead với sự kiện Python siêu nhẹ chịu ảnh hưởng GIL**; khi mô hình có lookahead dương kết hợp tác vụ tính toán nặng giải phóng GIL, OS multi-thread mang lại tăng tốc đa nhân rõ rệt.

---

## 4. Lệnh Tái lập M5
```powershell
python -m unittest tests/test_m5_engines_gate.py -v
python -m drivethru.experiments.run_m5_benchmark
python -m drivethru.experiments.run_m5_speedup_probe
python -m drivethru.experiments.plot_m5_benchmark
```
