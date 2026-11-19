# HƯỚNG DẪN REVIEW CODE & KIỂM ĐỊNH PHÉP ĐO CHO EXAMINER (NHÁNH `sequential_dev`)

Tài liệu này dành riêng cho các thành viên giữ vai trò **Examiner** (người kiểm định, xác thực mô hình, đánh giá phép đo và phân tích thống kê theo Bước 7–10 của quy trình 10 bước Performance Evaluation). Nếu bạn mới đọc đề bài và vừa nhận link Git, hãy đọc từ trên xuống dưới để nắm toàn bộ tiến độ, bản đồ mã nguồn, trình tự review code và các câu lệnh chạy thực nghiệm.

---

## 1. Dự án đang ở đâu? (Trạng thái hiện tại: Hoàn thành 4/5 Mốc)

Hệ thống mô phỏng sự kiện rời rạc (DES) mạng hàng đợi **Drive-thru 4 trạm kiểu Fork–Join** trên nền tảng `bkitevsim` của giảng viên (không sửa mã nguồn gốc trong `bkitevsim/`).

| Mốc | Nội dung chính | Trạng thái | Bằng chứng kiểm thử |
| :--- | :--- | :--- | :--- |
| **M1** | Khảo sát framework `bkitevsim`, xử lý lỗi wrap-around của `LadderQueue` bằng `safe_bucket_width(t_end)`. | **ĐÃ XONG** | Pass `3/3` tests (`tests/test_m1_framework.py`) |
| **M2** | Hiện thực lõi dữ liệu, CRN 5 luồng RNG, `CarSourceLP`, `StationLP` (tái sử dụng cho 6 mô hình đơn), `MonitorLP`, công thức giải tích + $CI_{95\%}$ và chạy **Thí nghiệm A**. | **ĐÃ XONG** | Pass `5/5` tests (M1+M2); **Exp A**: `144/144` chỉ số PASS (18 cấu hình x 30 seeds, sai số max `1.97%`, Little max `0.071%`) |
| **M3** | Hiện thực `PickupLP(StationLP)` kèm bảng `join_table[car_id]` đối xứng, ghép mạng 4 trạm (6 LP), thêm chế độ `blocking_order` cho Exp D. | **ĐÃ XONG** | Pass `12/12` tests (M1+M2+M3) gồm 3 ca Join, đảo thứ tự event trễ 0, thu gọn Jackson, khớp 2 Dispatcher |
| **M4** | Bộ chạy thí nghiệm đa tiến trình có Checkpoint/Resume; chạy trọn bộ **Exp B, Exp C (48 cấu hình), Exp D** và xuất **5 biểu đồ** báo cáo. | **ĐÃ XONG** | `53/53` cấu hình (`1 600` lượt chạy): `100%` cân bằng dòng, `100%` đạt chuẩn $CI_{95\%}$, xuất đủ 4 bảng CSV + 5 ảnh PNG |
| **M5** | Rẽ nhánh `multithread_dev` từ `sequential_dev`: cài đặt lát cắt Coroutine (`BkSysCoLogicalProcess` + `BkSysFuture`) và so sánh tốc độ/độ khớp với bản đồng bộ. | **KẾ TIẾP** | Sẽ triển khai trong `drivethru/engines/` |

---

## 2. Tổng quan Kiến trúc Hệ thống (Để Examiner đối chiếu với Thiết kế)

* **Tô-pô mạng Drive-thru 4 trạm (6 Logical Processes — chỉ dùng 4 lớp LP):**
  * `LP0` — `CarSourceLP`: Sinh xe theo quá trình Poisson tốc độ `lam`, lấy mẫu sẵn 4 thời gian phục vụ `(s1, s2, s3, s4)` bằng **5 dòng `random.Random` độc lập** để đảm bảo kỹ thuật **Common Random Numbers (CRN)** khi so sánh cấu hình.
  * `LP1` — `Order` (`StationLP`, mô hình $M/M/c_1/K_1$, $c_1=2$, $1/\mu_1=1.5$ phút, sức chứa hữu hạn $K_1 \in \{3, 4, 6, 8\}$ tính cả xe đang phục vụ). Nếu đầy $K_1$, xe bị `DROP` ngay sang `LP5`. Khi gọi món xong, phát đồng thời `TRANSFER` sang `Payment` và `ORDER_PLACED` (kèm bản sao độc lập `car.copy_for_branch()`) sang `Kitchen` mà không chờ bếp.
  * `LP2` — `Payment` (`StationLP`, mô hình $M/M/c_2$, $c_2 \in \{1, 2, 3\}$, $K_2=\infty$, $1/\mu_2=1.25$ phút). Xong gửi `TRANSFER` sang `LP4`.
  * `LP3` — `Kitchen` (`StationLP`, mô hình $M/M/c_3$, $c_3=2$, $K_3=\infty$, $1/\mu_3=1.5$ phút). Xong gửi `FOOD_READY` sang `LP4` (ở chế độ **Blocking** của Exp D thì gửi về cả `LP1` và `LP4`).
  * `LP4` — `PickupLP(StationLP)` (mô hình $M/M/c_4$, $c_4=2$, $K_4=\infty$, $1/\mu_4=1.0$ phút): Kế thừa `StationLP`, thêm bảng `join_table[car_id]`. Xe và đồ gặp nhau ở bảng Join mới đi vào hàng đợi/server Pickup. Xong gửi `DEPARTURE` sang `LP5`.
  * `LP5` — `MonitorLP`: Chỉ nhận sự kiện `DROP` và `DEPARTURE`, đo $T$, $P_{95}(T)$, $P(T > 8)$, $W_f$, $P_f$ mà không đọc chéo trạng thái nội bộ của LP khác.
* **Tái sử dụng 1 lớp `StationLP` cho cả 6 mô hình đơn ở Thí nghiệm A:** Nối mạch `LP0 -> LP1 -> LP5` và chỉ đổi cặp `(c, K)`: $M/M/1$ `(1, inf)`, $M/M/1/K$ `(1, 4)`, $M/M/\infty$ `(inf, inf)`, $M/M/n/n$ `(3, 3)`, $M/M/c$ `(2, inf)`, $M/M/c/K$ `(2, 5)`.
* **Đơn vị & Cửa sổ đo (Transient Removal):** Đơn vị thời gian là **phút**. Giai đoạn làm nóng `t_warmup = 2000` phút; khi nhận sự kiện `WARMUP_END`, các bộ đếm và tích phân trong cửa sổ đo được đặt lại về `0` nhưng giữ nguyên trạng thái hệ thống (`busy`, `queue`, `join_table`) và các bộ đếm toàn trình `total_*` để kiểm tra cân bằng dòng.

---

## 3. Bản đồ File — File nào dùng để làm gì?

    hk261_spe_BKsyspeEvsim/
    ├── bkitevsim/                          # [KHÔNG SỬA] Framework gốc của giảng viên
    ├── ROADMAP_DEV_V2.md                   # Lộ trình phát triển chuẩn hóa V2.1 (M1 -> M5)
    ├── EXAMINER_GUIDE.md                   # File hướng dẫn này
    ├── drivethru/                          # PACKAGE CHÍNH CỦA NHÓM
    │   ├── config/
    │   │   ├── simulation_config.py        # Hàm safe_bucket_width(t_end) & dataclass DriveThruParams
    │   │   └── experiment_config.py        # Danh sách 18 cấu hình Exp A & 53 cấu hình Exp B, C, D
    │   ├── core/
    │   │   ├── event_types.py              # Enum LPID (0..5) và đúng 10 EventType chuẩn
    │   │   ├── distributions.py            # MultiStreamRNG: 5 dòng số ngẫu nhiên độc lập cho CRN
    │   │   └── state.py                    # CarRecord (+ copy_for_branch), StationState, PickupState, MonitorState
    │   ├── models/
    │   │   ├── car_source.py               # LP0: Sinh xe Poisson + lấy mẫu sẵn (s1..s4)
    │   │   ├── station.py                  # LP1..LP3 & 6 mô hình đơn: StationLP + tích phân + blocking_order
    │   │   ├── pickup.py                   # LP4: PickupLP kế thừa StationLP + join_table + tích phân L_f
    │   │   └── monitor.py                  # LP5: MonitorLP tính T, P95(T), P(T>8), W_f, P_f
    │   ├── metrics/
    │   │   ├── analytical.py               # Công thức giải tích 6 mô hình đơn & xấp xỉ Fork-Join
    │   │   └── statistics.py               # Tính Mean, Std, CI 95% (Student-t) và kiểm tra Little's Law
    │   ├── engines/                        # Thư mục chờ cho nhánh multithread_dev (Mốc M5)
    │   └── experiments/
    │       ├── run_exp_a.py                # Chạy Validation 6 mô hình đơn (18 cấu hình x 30 seeds)
    │       ├── run_single.py               # Dựng & chạy 1 lượt mạng 4 trạm kèm assert bất biến
    │       ├── runner.py                   # Bộ chạy đa tiến trình 4 worker + lưu checkpoint CSV + tự mở rộng CI95%
    │       ├── run_exp_bcd.py              # Chạy chính thức Exp B, Exp C (48 cấu hình), Exp D & xuất CSV tóm tắt
    │       └── plot_results.py             # Vẽ 5 biểu đồ PNG báo cáo từ các file CSV
    ├── tests/                              # BỘ KIỂM THỬ CỔNG (12 Unit Tests)
    │   ├── test_m1_framework.py            # Cổng M1: Chứng minh bug LadderQueue & test safe_bucket_width
    │   ├── test_m2_station_gate.py         # Cổng M2: Ràng buộc (c, K), cân bằng dòng, đồng nhất công thức giải tích
    │   └── test_m3_network_gate.py         # Cổng M3: 3 ca Join, đảo event trễ 0, Little toàn mạng, thu gọn, 2 Dispatcher, Exp D
    └── reports/                            # Thư mục đầu ra CSV & 5 ảnh PNG (nằm trong .gitignore, chạy lệnh sẽ tự tạo)

---

## 4. Trình tự Review Code cho Examiner (Mất ~15 phút để nắm chắc 100%)

Để kiểm định xem Developer đã hiện thực đúng lý thuyết hàng đợi và phép đo thống kê chưa (Structured Walk-Through), Examiner nên đọc theo đúng 4 bước sau:

1. **Bước 1 — Kiểm tra độ sạch của Framework & Tránh sai số đồng hồ ảo (M1):**
   * Đọc `drivethru/config/simulation_config.py` và `tests/test_m1_framework.py`.
   * *Điểm cần xác nhận:* Trong `bkitevsim/queues/ladder_queue.py`, `num_buckets=1024` và `_get_bucket_index` lấy `int(ts / bucket_width) % 1024`. Nếu giữ mặc định `bucket_width=1.0`, sự kiện `t >= 1024` sẽ bị xoay vòng về xô đầu làm thời gian đi lùi. Hàm `safe_bucket_width(t_end) = ceil(1.05 * (t_end + 100) / 1024)` đã triệt tiêu hoàn toàn lỗi này (được chứng minh bằng test `test_default_bucket_width_wrap_around_bug` và `test_safe_bucket_width_formula_and_monotonic_order`).
2. **Bước 2 — Kiểm tra logic Hàng đợi, Tích phân thời gian liên tục và Cắt quá độ (M2):**
   * Đọc `drivethru/core/distributions.py`, `drivethru/core/state.py`, `drivethru/models/station.py`.
   * *Điểm cần xác nhận:*
     * `_update_integrals(t)` luôn được gọi ở đầu `handle_event()` **trước** khi đổi `busy`/`queue` và gọi chốt lần cuối tại `t_end` trong `get_statistics()`.
     * Chống lỗi double-start khi trùng timestamp: trong `_handle_arrival()`, tăng `busy += 1` **trước** khi lập lịch `BEGIN_SERVICE`; trong `_release_server_or_serve_next()`, nếu còn xe trong `queue` thì giữ nguyên `busy`.
     * Tại `_handle_warmup_end(t)`: chỉ reset tích phân và bộ đếm trong cửa sổ đo, giữ nguyên trạng thái vật lý và bộ đếm `total_*`.
     * Các chỉ số theo xe ($W, W_q, P_w, T$) chỉ thu thập cho các xe có `car.t_arrive >= t_warmup`.
3. **Bước 3 — Kiểm tra bảng Join, Đấu dây mạng và Các bất biến (M3):**
   * Đọc `drivethru/models/pickup.py`, `drivethru/experiments/run_single.py` và `tests/test_m3_network_gate.py`.
   * *Điểm cần xác nhận:*
     * Bảng `join_table[car_id]` xử lý đối xứng 3 ca (xe đến trước, đồ xong trước, trùng timestamp) và xóa mục ngay sau khi hợp luồng.
     * Cân bằng dòng vật lý: `total_generated == completed + dropped + (unfin_Order + unfin_Payment + unfin_Join_xe_den + unfin_Pickup)`. Lưu ý chỉ đếm xe có `xe_den == True` trong bảng Join để không đếm trùng xe còn ở Payment.
     * Định luật Little toàn mạng: `L_system = L1 + L2 + L_f + L4` (không cộng `L3` vì Kitchen chứa đơn hàng song song) so với `X * T`.
     * Biến thể Chặn (Exp D, `blocking_order=True`): Order giữ server chờ bếp, Kitchen gửi `FOOD_READY` tới **cả Order và Pickup** để giải phóng Order mà không làm treo bảng Join.
4. **Bước 4 — Kiểm tra Công thức giải tích, Khoảng tin cậy 95% và Phép đo thực nghiệm (M2 & M4):**
   * Đọc `drivethru/metrics/analytical.py`, `drivethru/metrics/statistics.py`, `drivethru/experiments/runner.py`, `drivethru/experiments/run_exp_bcd.py`.
   * *Điểm cần xác nhận:* Công thức 6 mô hình đơn (đệ quy Erlang B chống tràn số, $P_w$ có điều kiện cho $M/M/1/K$ và $M/M/c/K$), hệ số Student-t `t_{0.975, 29} = 2.04523`, điều kiện kiểm định độ chính xác `CI95(T) <= 5%` và `CI95(P_b) <= 0.3%`.

---

## 5. Hướng dẫn Cài đặt & Câu lệnh Chạy Kiểm chứng cho Examiner (Windows PowerShell)

### Bước 1: Clone repo và chuyển sang nhánh `sequential_dev`

    git clone <URL_REPO_GITHUB>
    cd hk261_spe_BKsyspeEvsim
    git checkout sequential_dev

### Bước 2: Cài đặt thư viện vẽ đồ thị (chỉ cần cho bước vẽ biểu đồ)
*(Toàn bộ lõi mô phỏng và unit test chỉ dùng thư viện chuẩn Python 3.10+, không cần cài gói ngoài. Chỉ riêng script vẽ hình cần `matplotlib` và `numpy`).*

    python -m pip install matplotlib numpy

### Bước 3: Chạy bộ 12 Unit Tests kiểm định Verification (Mất ~20 giây)
Lệnh này kiểm chứng tự động toàn bộ Cổng M1, M2, M3 (lỗi `LadderQueue`, cân bằng dòng, đồng nhất công thức giải tích 6 mô hình, 3 ca Join, đảo thứ tự event trễ 0, Little toàn mạng, kiểm tra thu gọn Jackson, khớp 2 Dispatcher và chế độ Blocking Exp D):

    python -m unittest discover -s tests -p "test_m*.py" -v

*Kết quả kỳ vọng:* `Ran 12 tests in ~21s — OK`.

### Bước 4: Chạy thử nhanh 1 lượt mạng Drive-thru 4 trạm (Mất ~1.6 giây)
In trực tiếp các chỉ số $T$, $P_{95}(T)$, $P_b$, $U_1..U_4$, $W_f$, $L_{\text{system}}$, cân bằng dòng và đối chiếu xấp xỉ Fork–Join:

    python -m drivethru.experiments.run_single

### Bước 5: Tái lập Thí nghiệm A — Validation 6 mô hình đơn (Mất ~2–3 phút trên 4 nhân CPU)
Chạy 18 cấu hình x 30 seeds = 540 lượt, in bảng đối chiếu Lý thuyết vs. Mô phỏng và lưu ra `reports/exp_a_validation.csv`:

    python -m drivethru.experiments.run_exp_a

*Kết quả kỳ vọng:* `144/144` chỉ số PASS, sai số trung bình `0.23%`, max `1.97%` (<= 5%), Little max `0.071%` (<= 1%).

### Bước 6: Tái lập Thí nghiệm B, C, D & Vẽ trọn bộ 5 biểu đồ (Mất ~15–16 phút trên 4 nhân CPU)
Chạy 53 cấu hình duy nhất (1 600 lượt chạy, có lưu checkpoint vào `reports/exp_bcd_raw_runs.csv` — dừng giữa chừng chạy lại vẫn tiếp tục được), xuất 3 bảng tóm tắt CSV và 5 ảnh PNG:

    python -m drivethru.experiments.run_exp_bcd
    python -m drivethru.experiments.plot_results

*(Lưu ý về 4 nhân CPU: `runner.py` và `run_exp_a.py` dùng `ProcessPoolExecutor(max_workers=4)` để chạy đồng thời nhiều `seed` độc lập cho nhanh; bên trong mỗi worker vẫn chạy 100% mô phỏng đơn luồng tuần tự `SequentialEventDispatcher`).*

---

## 6. Tóm tắt Số liệu Thực nghiệm Chuẩn đã Chạy được (Để Examiner đối chiếu)

* **Exp A (Validation 6 mô hình đơn — 540 lượt):** `144/144` chỉ số PASS (`140/144` nằm trong $CI_{95\%}$, sai số max `1.97%`, Little max `0.071%`).
* **Exp B (Baseline $c_2=1, K_1=8$ & Đối chiếu $K_1=30$):**
  * Nút cổ chai nằm rõ ở **Payment** ($U_2 = 74.6\%$ tại Peak $\lambda=0.6$, $86.6\%$ tại Heavy $\lambda=0.7$), đẩy $T$ lên `8.317 ± 0.140` phút tại Peak (vượt SLA 8 phút) và `12.701 ± 0.620` phút tại Heavy.
  * Tại $K_1=30, \lambda=0.6$: Xấp xỉ Fork–Join lệch **`1.51%`** (`8.366` vs. `8.494` phút); ca thu gọn $1/\mu_3 = 0.01$ khớp mạng Jackson lệch **`0.45%`** (`7.944` vs. `7.980` phút).
* **Exp C (Độ nhạy & Tối ưu — 48 cấu hình):**
  * Tăng $c_2 = 1 \to 2$ (tại $K_1=8$) giảm $T$ tới **`34.9%`** tại Peak (`8.317 -> 5.415` phút) và **`54.4%`** tại Heavy (`12.701 -> 5.790` phút). Tăng tiếp $c_2 = 2 \to 3$ chỉ giảm thêm `1.6%–2.0%` (lợi ích biên bão hòa).
  * **Cấu hình tối ưu khuyến nghị:** **`c2 = 2, K1 = 6`** (Peak: $T = 5.368 \pm 0.030$ phút, $P_b = 0.63 \pm 0.07\%$; Heavy: $T = 5.679 \pm 0.029$ phút, $P_b = 1.34 \pm 0.12\%$ — đạt vững chắc SLA $T \le 8$ phút & $P_b \le 5\%$ trên mọi mức tải).
* **Exp D (Non-blocking vs. Blocking tại $c_2=2, K_1=8$):**
  * Tại Peak ($\lambda = 0.6$): Chế độ Blocking làm $U_1$ tăng vọt `44.9% -> 84.7%`, $P_b$ tăng `0.14% -> 5.65%` (vỡ SLA 5%), $T$ tăng `5.415 -> 8.722` phút (+61.1%, vỡ SLA 8 phút). Giao tiếp Non-blocking giúp giảm **`37.9%`** thời gian đáp ứng tại Peak và **`41.7%`** tại Heavy.
* **Ghi chú kỹ thuật về Little's Law cho Examiner:** Trên toàn bộ `53/53` cấu hình, sai số Định luật Little tổng hợp đều $\le 0.335\%$ (trung bình `0.107%`). Trong `1 600` lượt đơn lẻ, có đúng `1` lượt tải cực cao (`C_lam7_c2_1_K1_8`, `seed=8`, $\rho_2=0.875$) có sai số cục bộ `1.26%` do biến động hàng đợi còn lại ở mốc cuối $t_{\text{end}}=10\,000$ phút; toàn bộ `1 599` lượt còn lại đều $\le 1\%$.

---

## 7. Năm Lỗi Kỹ thuật của Framework `bkitevsim` Nhóm đã Phát hiện (Đưa vào Báo cáo Verification)

1. **`LadderQueue` wrap-around (`bkitevsim/queues/ladder_queue.py`):** `_get_bucket_index` chia `% 1024`, khiến `bucket_width=1.0` rút sai thứ tự `[1.0, 1025.0, 2.0]` khi $t \ge 1024$. *Khắc phục:* dùng `safe_bucket_width(t_end)`.
2. **`Simulation.create_lp` & `create_lps` (`bkitevsim/core/simulation.py`):** `create_lp` lọc mất tham số tên `"end_time"`; `create_lps` luôn đánh ID từ `0` gây ghi đè. *Khắc phục:* dùng tham số `t_end` và gọi `create_lp(lp_id, ...)` tường minh.
3. **`BkSysCoLogicalProcess.wait_for` (`bkitevsim/core/logical_coProcess.py`):** Quên kiểm tra `self._pending_events` (khác với `wait_for_multiple`), gây mất sự kiện đến sớm ở bản Coroutine (sẽ xử lý ở M5).
4. **`BkSysCoEventLoop._process_events_at_current_time`:** Dùng `try...except` chỉ ghi log mà không `raise`, dễ ẩn lỗi runtime ở bản Coroutine.
5. **Circular Import (`bkitevsim/queues/__init__.py` & `bkitevsim/core/__init__.py`):** Import `bkitevsim.queues` trước `bkitevsim.core` sẽ văng `ImportError`. *Khắc phục:* luôn import `bkitevsim.core` trước `bkitevsim.queues`.
