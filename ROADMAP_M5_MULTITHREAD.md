# M5 — Mở rộng So sánh 3 Kiến trúc Thực thi DES (Nhánh `multithread_dev`)

Tài liệu phân tích hiệu năng phần cứng của **3 kiến trúc Engine DES** trên cùng bài toán Drive-thru 4 trạm theo 10 bước PE (phần mở rộng tùy chọn của nhóm **SPE-L0x-008**).

---

## 1. Ba Kiến trúc Engine So sánh (Tái sử dụng 100% `drivethru/models/`)
Không sửa `bkitevsim/`; cả 3 engine đều dùng chung logic nghiệp vụ trong `drivethru/models/` (chỉ khác cơ chế điều phối):
1. **Single-thread (`sequential_engine.py`):** `SequentialEventDispatcher` + 6 LP đồng bộ (1 OS thread).
2. **Virtual Multi-thread (`coroutine_engine.py`):** `BkSysCoEventLoop` + `SafeCoLogicalProcess` (bọc trực tiếp `CarSourceLP`, `StationLP`, `PickupLP`, `MonitorLP` theo mẫu Composition — không nhân bản code) + **`BkSysFuture` tại bảng Join của `CoPickupLP`** (1 OS thread).
   * *Lưu ý kiến trúc:* Đây là mô hình lai (event-handler + `BkSysFuture` tại điểm Join) tương thích với thiết kế `BkSysCoEventLoop` của giảng viên; một phương án hướng tiến trình thuần khác trong `asyncio` là mô hình hóa mỗi xe thành một coroutine dùng `asyncio.gather(payment, kitchen)`.
3. **OS Multi-thread (`multithread_engine.py`):** 6 `threading.Thread` cho 6 LP + `ThreadedClockCoordinator` đồng bộ bảo thủ theo từng mốc thời gian nhỏ nhất $t_{min}$ (zero-lookahead conservative barrier), bảo đảm 0 causality error và 0 deadlock.

---

## 2. Thiết kế Đo Đạc M5 (Đa mức $t_{end}$, Đa mức $\lambda$, OS RSS & Car-by-Car Fidelity)
* **5 kịch bản đo tuần tự 1-core (`run_m5_benchmark.py`):**
  * Trục quy mô sự kiện (Peak $\lambda = 0.6$): $t_{end} \in \{2\,000, 5\,000, 10\,000\}$ phút.
  * Trục cường độ tải ($t_{end} = 5\,000$): $\lambda \in \{0.2, 0.6, 0.7\}$ xe/phút.
* **Chỉ số đo:** `wall_time`, `cpu_time`, `events/sec` (đo ở Pha 1 tắt `tracemalloc` để sạch observer effect), `peak_mem_mb` (Python heap), **`rss_mb` (OS Working Set/VmRSS tính cả stack của 6 OS threads)**, `pct_single_lp_epochs`, `avg_active_lps_per_epoch`, và **car-by-car trace fidelity (`< 1e-9`)**.
* **Đầu ra:** `reports/exp_m5_benchmark.csv`, `reports/fig6_m5_walltime_throughput.png`, `reports/fig7_m5_memory_and_overhead.png`.

---

## 3. Phân tích Nguyên nhân Kỹ thuật (Giới hạn Zero-Lookahead, GIL & Nền tảng)
1. **Độ toàn vẹn tuyệt đối (Fidelity = 0.0 trên từng xe):** So khớp cả 10 chỉ số tổng hợp lẫn quỹ đạo từng chiếc xe (`status, car_id, t_arrive, t_done, food_wait_time`) đều cho sai lệch `0.0e+00`, 0 causality error, 0 deadlock.
2. **Vì sao OS Multi-thread chậm hơn Single-thread (không chỉ do GIL):**
   * **Giới hạn cấu trúc zero-lookahead (nguyên nhân chính):** Do thời gian đến và phục vụ phân phối mũ liên tục, xác suất hai sự kiện độc lập trùng timestamp gần bằng 0. Phép đo trực tiếp từ `ThreadedClockCoordinator` cho thấy **~82% nhịp đồng bộ chỉ có đúng 1 LP hoạt động**, trung bình chỉ **~1.2 LP/nhịp** — tức trần tăng tốc lý thuyết chỉ khoảng **1.2x** ngay cả trước khi tính tới GIL hay chi phí đồng bộ. Chương trình thực chất vận hành như 6 thread chuyền tay nhau một lượt "baton".
   * **Cộng hưởng CPython GIL & chi phí đồng bộ:** Mỗi sự kiện chỉ tốn vài micro-giây Python, nhỏ hơn nhiều lần chi phí đánh thức `threading.Condition` barrier + chuyển ngữ cảnh OS + tranh chấp GIL trên CPython 3.12.
   * **Phạm vi kết luận:** Kết luận *"không nên dùng OS thread"* chỉ áp dụng cho **thiết kế barrier bảo thủ không có lookahead (zero-lookahead) với sự kiện siêu nhẹ trên CPython có GIL**; muốn tăng tốc PDES song song thực thụ cần cơ chế **lookahead dương** (hoặc thuật toán lạc quan Time Warp) kèm tải tính toán đủ lớn trên mỗi sự kiện và runtime không bị GIL cản trở.
3. **Bộ nhớ (Python Heap vs. OS RSS):** `tracemalloc` chỉ đo Python heap (~0.45–0.48 MB tại $t_{end}=10\,000$), không tính stack của từng OS thread; vì vậy `run_m5_benchmark.py` báo cáo đồng thời cả `peak_mem_mb` (heap) lẫn `rss_mb` (OS Working Set/VmRSS).
4. **Phụ thuộc nền tảng:** Thứ hạng hiệu năng (`Single > Coroutine > OS-Thread`) giữ nguyên trên cả Windows (CPython 3.12) lẫn Linux (Python 3.13), nhưng tốc độ tuyệt đối (`ev/s`) và hệ số slowdown phụ thuộc hệ điều hành, trình lập lịch thread và phiên bản Python.

---

## 4. Lệnh Tái lập M5
```powershell
python -m unittest tests/test_m5_engines_gate.py -v
python -m drivethru.experiments.run_m5_benchmark
python -m drivethru.experiments.plot_m5_benchmark
```
