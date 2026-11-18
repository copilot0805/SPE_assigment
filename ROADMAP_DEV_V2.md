# LỘ TRÌNH PHÁT TRIỂN HỆ THỐNG MÔ PHỎNG DRIVE-THRU (PHIÊN BẢN V2.1 - ĐA ĐỘNG CƠ)

Tài liệu này chuẩn hóa lộ trình phát triển hệ thống mô phỏng sự kiện rời rạc (DES) trên nền tảng bkitevsim, đóng gói toàn bộ mã nguồn vào package drivethru/, tích hợp đầy đủ các hiệu chỉnh kỹ thuật để khớp 100% với đặc tả Design V2 (Assignment_SPE_Design_v2.pdf), đồng thời quy hoạch kiến trúc mở rộng cho các phương pháp thực thi Coroutine, Virtual Thread và Multi-thread.

---

## 1. Các nguyên tắc cốt lõi giữ nguyên

1. Nền tảng thực thi chuẩn (V2-Sync): Sử dụng BkSysLogicalProcess kết hợp với SequentialEventDispatcher làm phiên bản chuẩn đồng bộ để kiểm chứng giải tích và chạy toàn bộ 4 thí nghiệm chính (Exp A, B, C, D).
2. Tái sử dụng lớp StationLP: Dùng chung một lớp StationLP duy nhất cho 3 trạm (Order, Payment, Kitchen) và cả 6 mô hình hàng đợi đơn (M/M/1, M/M/1/K, M/M/inf, M/M/n/n, M/M/c, M/M/c/K), chỉ thay đổi cặp tham số cấu hình (c, K).
3. Ba quy tắc an toàn trên bkitevsim:
   - DistributedEventDispatcher chỉ phân hoạch hàng đợi sự kiện theo từng LP nhưng vẫn rút sự kiện và thực thi tuần tự trên 1 luồng.
   - Tham số timeout trong wait_for() của BkSysCoLogicalProcess tính bằng giây đồng hồ thực (wall-clock seconds), không phải thời gian mô phỏng.
   - Tuyệt đối không dùng time.sleep(), asyncio.sleep() hay elapse_virt_time() để thay thế cho việc lập lịch sự kiện END_SERVICE tại mốc event.timestamp + service_time.
4. Quy ước sức chứa K và giữ chỗ server tức thì:
   - Sức chứa K của trạm tính cả số xe đang phục vụ lẫn số xe đang chờ (K = w + c).
   - Ngay trong handler nhận xe (ARRIVAL / TRANSFER / ORDER_PLACED), nếu busy < c, trạm phải tăng busy += 1 trước khi lập lịch sự kiện BEGIN_SERVICE (độ trễ 0) tại t. Tại END_SERVICE, nếu queue còn xe thì lấy xe đầu hàng (popleft()) và lập lịch BEGIN_SERVICE tại t (giữ nguyên busy); chỉ khi queue rỗng mới giảm busy -= 1.

---

## 2. Sáu quy định kỹ thuật và kiến trúc đã hiệu chỉnh

### 2.1. Công thức safe_bucket_width(t_end) có lề cố định +100 phút
- Trong bkitevsim/queues/ladder_queue.py, chỉ số xô được tính bởi int(timestamp / self.bucket_width) % 1024. Để đảm bảo 1024 * bucket_width > max_timestamp (ngăn chặn triệt để lỗi xoay vòng xô % 1024 cho cả lượt chạy ngắn lẫn lượt chạy dài), bucket_width luôn được tính bằng công thức:
  bucket_width = ceil(1.05 * (t_end + 100) / 1024)
  (Ví dụ: t_end = 10000 -> 11; t_end = 20000 -> 21; t_end = 60000 -> 62).

### 2.2. Tích hợp đầy đủ Metrics vào StationLP và MonitorLP ngay tại Mốc M2
- Tích phân diện tích liên tục theo thời gian: area_busy, area_queue, area_system trên cửa sổ đo [t_warmup, t_end] để tính U_i, L_q_i, L_i.
- Thống kê theo từng xe hoàn thành (có t_arrive >= t_warmup): W_q_i, W_i, xác suất phải chờ P_w, thông lượng X_i, xác suất từ chối P_b; tại MonitorLP thu thập mẫu thời gian toàn trình T để tính mean(T), P95(T) và P(T > 8).
- Bộ đếm toàn trình [0, t_end]: total_arrived, total_served, total_dropped được giữ nguyên qua mốc WARMUP_END để kiểm tra tự động phương trình cân bằng dòng trên mọi lượt chạy.

### 2.3. PickupLP kế thừa StationLP kèm tích phân bãi chờ đồ L_f
- PickupLP (LP4) là lớp con của StationLP (có hàng đợi FCFS và c4 server với tốc độ mu4), bổ sung bảng join_table[car_id] lưu (xe_den, do_xong, t_p, t_f, car_record).
- Duy trì biến đếm số xe đang đậu chờ đồ tại bảng Join waiting_food_count (số mục có xe_den == True và do_xong == False) và tích phân diện tích area_food_wait để tính số xe trung bình chờ đồ L_f.
- Khi cả xe_den và do_xong đều True: xóa mục join, ghi nhận W_f = max(0, t_f - t_p) rồi gọi super()._handle_arrival(car, t) để đưa xe vào hàng đợi/server của Pickup.
- Cuối lượt chạy tại t_end, chỉ những mục trong join_table có xe_den == True mới được đếm vào số xe chưa hoàn thành tại bãi Join (để không đếm trùng với các xe đang còn nằm ở trạm Payment).

### 2.4. Cơ chế biến thể "Chặn" (Blocking) cho Thí nghiệm D (Bảng 12 Design V2)
- Biến thể Không chặn (blocking_order = False - Cơ sở): Khi kết thúc END_SERVICE, Order (LP1) gửi đồng thời TRANSFER sang Payment (LP2) và ORDER_PLACED (kèm bản sao car.copy_for_branch()) sang Kitchen (LP3), rồi phục vụ ngay xe kế tiếp. Kitchen (LP3) nấu xong chỉ gửi FOOD_READY tới Pickup (LP4).
- Biến thể Chặn (blocking_order = True - Đối chứng ở Exp D với c1 = 2, c3 = 2 => c3 >= c1):
  1. Khi xe gọi món xong tại Order (END_SERVICE ở LP1): LP1 chỉ gửi ORDER_PLACED (kèm bản sao car.copy_for_branch()) sang Kitchen (LP3), lưu xe vào state.waiting_food_cars[car.car_id] = car và giữ nguyên server đang bận (busy không giảm, chưa chuyển xe sang Payment và chưa lấy xe tiếp theo trong queue của Order).
  2. Khi Kitchen (LP3) nấu xong (END_SERVICE ở LP3): Kitchen gửi FOOD_READY tới cả Order (LP1) và Pickup (LP4) (out_targets = [(1, "FOOD_READY"), (4, "FOOD_READY")]). Việc vẫn gửi FOOD_READY cho Pickup đảm bảo bảng Join tại Pickup nhận được cờ do_xong = True khi xe thanh toán xong đi tới.
  3. Khi Order (LP1) nhận được FOOD_READY từ Kitchen tại thời điểm t: LP1 lấy xe ra khỏi waiting_food_cars, chốt thời điểm xe rời trạm Order (car.t_end[1] = t), thống kê W_1 = t - t_enter_1, gửi TRANSFER đưa xe sang Payment (LP2), và giải phóng server để phục vụ xe tiếp theo trong hàng đợi Order (hoặc giảm busy -= 1 nếu hàng đợi rỗng).

### 2.5. Quy tắc đa tiến trình (ProcessPoolExecutor) trên Windows
- Hàm thực thi 1 lượt chạy run_single_replication(config, seed) bắt buộc là top-level function ở cấp module.
- Bên trong run_single_replication, luôn khởi tạo một đối tượng Simulation mới, đặt tên tham số kết thúc của các LP là t_end (tránh bị Simulation.create_lp lọc mất khóa "end_time"), và không dùng create_lps().
- Mọi script chạy batch đa tiến trình bắt buộc đặt lệnh gọi pool bên trong if __name__ == "__main__":, kèm cơ chế lưu checkpoint từng lượt chạy ra CSV/JSON.

### 2.6. Đóng gói vào package drivethru/ và Kiến trúc Đa Động cơ (Multi-Engine)
- Toàn bộ mã nguồn mới được gom vào gói drivethru/ để không trùng tên với bkitevsim/core/.
- Tách biệt Tầng Lõi (drivethru/core/) với Tầng Động cơ thực thi (drivethru/models/ và drivethru/engines/) để phục vụ nhánh sequential_dev và nhánh mở rộng multithread_dev:
  1. Sync Sequential / Distributed Engine (drivethru/models/): Kế thừa BkSysLogicalProcess.
  2. Coroutine / Virtual Multi-thread Engine (drivethru/engines/coroutine_engine.py): Kế thừa BkSysCoLogicalProcess + BkSysFuture.
  3. OS Multi-thread Engine (drivethru/engines/multithread_engine.py): Thực thi đa luồng hệ điều hành (threading / ThreadPoolExecutor) có đồng bộ hóa đồng hồ ảo.

---

## 3. Cấu trúc Thư mục Dự án Đã Chuẩn hóa

    hk261_spe_BKsyspeEvsim/
    ├── bkitevsim/                          # Framework gốc của giảng viên
    ├── apps/                               # Ứng dụng mẫu của giảng viên
    ├── scenarios/                          # Kịch bản mẫu của giảng viên
    ├── ROADMAP_DEV_V2.md                   # Lộ trình phát triển V2.1 đã hiệu chỉnh
    ├── drivethru/                          # PACKAGE CHÍNH CỦA NHÓM
    │   ├── __init__.py
    │   ├── config/
    │   │   ├── __init__.py
    │   │   ├── simulation_config.py        # Hàm safe_bucket_width(t_end) & DriveThruParams
    │   │   └── experiment_config.py        # Bảng cấu hình chuẩn cho Exp A (18 cấu hình), B, C, D
    │   ├── core/
    │   │   ├── __init__.py
    │   │   ├── event_types.py              # Enum LPID (0..5) và EventType (10 sự kiện chuẩn)
    │   │   ├── distributions.py            # MultiStreamRNG (5 dòng số ngẫu nhiên độc lập CRN)
    │   │   └── state.py                    # CarRecord, StationState, PickupState, MonitorState
    │   ├── models/                         # ĐỘNG CƠ CHUẨN ĐỒNG BỘ (V2-Sync: BkSysLogicalProcess)
    │   │   ├── __init__.py
    │   │   ├── car_source.py               # LP0: CarSourceLP
    │   │   ├── station.py                  # LP1..LP3 & 6 mô hình đơn: StationLP (hỗ trợ blocking_order)
    │   │   ├── pickup.py                   # LP4: PickupLP(StationLP) kèm join_table & tích phân L_f
    │   │   └── monitor.py                  # LP5: MonitorLP
    │   ├── engines/                        # KHÔNG GIAN ĐỘNG CƠ MỞ RỘNG (Nhánh multithread_dev ở M5)
    │   │   ├── __init__.py
    │   │   ├── coroutine_engine.py         # Virtual Multi-thread (BkSysCoLogicalProcess + BkSysFuture)
    │   │   └── multithread_engine.py       # OS Multi-thread (threading + Barrier/Lock-step)
    │   ├── metrics/
    │   │   ├── __init__.py
    │   │   ├── analytical.py               # Công thức giải tích 6 mô hình đơn (CT 2..45) & xấp xỉ Fork-Join
    │   │   └── statistics.py               # Mean, Std, 95% CI (t=2.045), kiểm tra Little & Cân bằng dòng
    │   └── experiments/
    │       ├── __init__.py
    │       ├── runner.py                   # Top-level worker cho ProcessPoolExecutor + Checkpoint CSV/JSON
    │       ├── run_exp_a.py                # Chạy kiểm chứng 18 cấu hình Exp A (6 mô hình đơn x 3 mức tải)
    │       ├── run_exp_bcd.py              # Chạy Exp B, Exp C (48 cấu hình x 30 seeds) và Exp D
    │       └── plot_results.py             # Xuất 5 biểu đồ chuẩn báo cáo Phase 2
    ├── tests/                              # BỘ KIỂM THỬ CỔNG (Chạy từ thư mục gốc)
    │   ├── __init__.py
    │   ├── test_m1_framework.py            # Cổng M1: Wrap-around bug, safe_bucket_width, tính đơn điệu
    │   ├── test_m2_station_gate.py         # Cổng M2: Ràng buộc (c, K), cân bằng dòng, khớp giải tích trạm đơn
    │   └── test_m3_network_gate.py         # Cổng M3: 3 ca Join, đảo event trễ 0, L_system, thu gọn, blocking_order
    └── reports/                            # Lưu CSV/JSON checkpoint và hình ảnh biểu đồ (trong .gitignore)

---

## 4. Bảng Cấu hình Chốt cho Thí nghiệm A (18 Cấu hình Kiểm chứng 6 Mô hình Đơn)

Cố định tốc độ phục vụ mỗi server mu = 1.0 xe/phút (1/mu = 1.0 phút), R = 30 seeds (seed in 1..30), t_warmup = 2000 phút:

| Mã cấu hình | Mô hình | Số server c | Sức chứa K | Hệ số tải / Cường độ | Tốc độ đến lambda | Thời gian kết thúc t_end | Chỉ số kiểm chứng chính |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| A1-1..3 | M/M/1 | 1 | inf | rho in {0.5, 0.8, 0.9} | 0.5, 0.8, 0.9 | 20000 (rho=0.9 -> 60000) | U, L, L_q, W, W_q, X, P_w |
| A2-1..3 | M/M/1/K | 1 | 4 | rho in {0.5, 0.8, 0.9} | 0.5, 0.8, 0.9 | 20000 | P_b, U, L, L_q, W, W_q, X |
| A3-1..3 | M/M/inf | inf | inf | a = lambda/mu in {1.0, 2.0, 4.0} | 1.0, 2.0, 4.0 | 20000 | L = a, W = 1/mu, L_q = 0, W_q = 0, X = lambda |
| A4-1..3 | M/M/n/n (Erlang B) | 3 | 3 | rho = lambda/(n*mu) in {0.5, 0.8, 0.9} | 1.5, 2.4, 2.7 | 20000 | P_b = B(n, a), U, L, W = 1/mu, L_q = 0, X |
| A5-1..3 | M/M/c (Erlang C) | 2 | inf | rho = lambda/(c*mu) in {0.5, 0.8, 0.9} | 1.0, 1.6, 1.8 | 20000 | P_w = C(c, a), U, L, L_q, W, W_q, X |
| A6-1..3 | M/M/c/K | 2 | 5 | rho = lambda/(c*mu) in {0.5, 0.8, 0.9} | 1.0, 1.6, 1.8 | 20000 | P_b, P_w, U, L, L_q, W, W_q, X |

---

## 5. Lộ trình 5 Mốc Phát triển (M1 -> M5) và Tiêu chí Cổng (Gate Criteria)

| Mốc | Nội dung triển khai | Tiêu chí hoàn thành (Gate Criteria) |
| :--- | :--- | :--- |
| M1 | Chạy 3 app mẫu của giảng viên; cài đặt safe_bucket_width(t_end) = ceil(1.05 * (t_end + 100) / 1024) trong drivethru/config/simulation_config.py và kiểm thử LadderQueue + SequentialEventDispatcher. | ĐÃ XONG (PASS 3/3): tests/test_m1_framework.py chạy hoàn tất trong 0.131s. |
| M2 | Hiện thực drivethru/core/, drivethru/models/ (CarSourceLP, StationLP hỗ trợ cả blocking_order, MonitorLP), drivethru/metrics/analytical.py & statistics.py; chạy run_exp_a.py cho 18 cấu hình Bảng 4. | Pass tests/test_m2_station_gate.py; cân bằng dòng khớp tuyệt đối; kết quả 18 cấu hình Exp A (R=30 seeds) có giá trị lý thuyết nằm trong CI 95% hoặc sai số tương đối <= 5%. |
| M3 | Hiện thực PickupLP(StationLP) kèm join_table và tích phân L_f; ghép mạng Fork-Join 4 trạm (cả chế độ Non-blocking và Blocking của Exp D). | Pass tests/test_m3_network_gate.py: (1) 3 ca bảng Join, (2) Đảo thứ tự gửi event trễ 0 kết quả không đổi, (3) Định luật Little từng trạm và toàn mạng L_system = L_1 + L_2 + L_f + L_4 = lambda_eff * T lệch <= 1%, (4) Kiểm tra thu gọn 1/mu_3 = 0.01, (5) Cùng seed khớp tuyệt đối giữa 2 Dispatcher, (6) Chế độ blocking_order=True bảo toàn dòng và làm tăng U_1, P_b, T. |
| M4 | Xây dựng drivethru/experiments/runner.py dùng ProcessPoolExecutor chuẩn Windows; chạy Exp B, Exp C (48 x 30 seeds), Exp D (6 x 30 seeds) và xuất 5 biểu đồ. | Đủ toàn bộ số lượt chạy; nửa độ rộng CI 95% đạt <= 5% giá trị trung bình (<= 0.3% với P_b); xuất đầy đủ bảng tổng hợp và 5 đồ thị báo cáo. |
| M5 | Từ sequential_dev rẽ nhánh multithread_dev: Hiện thực drivethru/engines/ (Coroutine / Virtual Multi-thread và OS Multi-thread) và chạy đối chiếu cùng seed. | Cùng seed và workload cho kết quả thống kê khớp với bản chuẩn đồng bộ; xuất bảng so sánh tốc độ xử lý (events/sec) và overhead. |
