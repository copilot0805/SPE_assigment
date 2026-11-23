# BÁO CÁO PHASE 2 — ĐÁNH GIÁ HIỆU NĂNG MẠNG HÀNG ĐỢI DRIVE-THRU THEO 10 BƯỚC PE

* **Môn học:** Đánh giá Hiệu năng Hệ thống (CO3007) — Khoa KH&KT Máy tính, ĐH Bách Khoa TP.HCM.
* **Nhóm:** SPE-L0x-008 (Lớp L02).
* **Môi trường thực thi chính thức:** Windows 11, CPU 4-core/8-thread, Python 3.12.10 (CPython có GIL); thư viện gốc `bkitevsim/` giữ nguyên vẹn byte-by-byte.
* **Tài liệu kỹ thuật kèm theo:** `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` (kiến trúc, class diagram, bảng đối chiếu thiết kế, kiểm toán Bảng 5–7, errata), `USER_MANUAL.md` (hướng dẫn tái lập), `EXAMINER_GUIDE.md` (kiểm định **29/29 unit tests**), `ROADMAP_M5_MULTITHREAD.md` (chi tiết Phụ lục A — M5).

---

## Bảng Ánh xạ 10 Bước PE với Thiết kế V2 (`Assignment_SPE_Design_v2.pdf`) & Bài giảng

| Bước PE | Nội dung thực hiện | Liên kết Thiết kế V2 & Slide | Tệp mã nguồn / Bằng chứng đầu ra |
|---|---|---|---|
| **1–2** | Mục tiêu, ranh giới, dịch vụ và 3 kết quả | Thiết kế §1.1–1.2, `pe2` | `drivethru/models/`, `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` |
| **3** | Chọn chỉ số, phân loại tiện ích HB/LB/NB & độ dư thừa | Thiết kế §2.1–2.3, `pe3` | `drivethru/metrics/stats_utils.py`, `analytical.py` |
| **4–5** | Tham số hệ thống (Bảng 5–7) và 3 yếu tố ($\lambda, c_2, K_1$) | Thiết kế §3.1–3.2, `pe2` | `simulation_config.py`, `experiment_config.py` |
| **6** | Kỹ thuật DES + Giải tích; đủ 9 kỹ thuật Verification | Thiết kế §1.4, §1.9, `pe3`, `pe7` | `run_exp_a.py`, `tests/test_m1..m4` (**29/29 unit tests PASS**) |
| **7–8** | Workload CRN, Welch, Leftover, Student-$t$ CI & Full Factorial | Thiết kế §2.5, §3.3–3.4, `pe7`–`pe9` | `run_welch_warmup.py`, `run_hand_trace.py`, `runner.py`, `fig0` |
| **9** | Phân bổ phương sai có `SSE`, Paired CRN, Trade-off & Little | Thiết kế §2.6, §3.4, `pe9`–`pe10` | `analyze_step9.py`, `fig9`, `fig10`, `exp_d_paired_crn.csv` |
| **10** | Trình bày kết quả, khuyến nghị cấu hình & Hạn chế đã biết | Thiết kế §1.9, §3.4, `pe2` | `fig1`–`fig5`, `fig9`, `fig10` *(M5 tách riêng tại Phụ lục A)* |

---

## Bước 1–2: Mục tiêu, Ranh giới, Dịch vụ và Kết quả
_Liên kết Thiết kế V2: Mục 1.1 (Mục tiêu, ranh giới, giả thiết) và Mục 1.2 (Dịch vụ và kết quả); bảng đối chiếu chi tiết tại `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` §3._

* **Hệ thống nghiên cứu (SUT):** Mạng hàng đợi Drive-thru 4 trạm dạng Fork–Join (`Order -> (Payment || Kitchen) -> Join -> Pickup`), hiện thực bằng 6 Logical Processes (`LP0..LP5`) từ 4 lớp (`CarSourceLP`, `StationLP`, `PickupLP(StationLP)`, `MonitorLP`).
* **Mục tiêu:** Định lượng $\overline{T}$, $U_i$, $P_b$, $W_f$; tìm cấu hình $(c_2, K_1)$ đạt chuẩn SLA tại cao điểm Peak ($\lambda = 0.6$): **S1:** $\overline{T} \le 8.0$ phút và **S2:** $P_b \le 5.0$%; đồng thời lượng hóa lợi ích giao tiếp không chặn giữa Order và Kitchen.
* **Ba kết quả dịch vụ:** (1) Hoàn thành (`DEPARTURE`), (2) Bị từ chối tại Order khi đầy $K_1$ (`DROP`), (3) Chưa hoàn thành khi kết thúc $t_{end}$ (*leftover entities*, đếm riêng để kiểm cân bằng dòng).

## Bước 3: Lựa chọn & Phân loại Chỉ số Hiệu năng
_Liên kết Thiết kế V2: Mục 2.1–2.3 (Bảng 1–3) và bài giảng `pe3` (Utility classification)._

| Nhóm tiện ích (`pe3`) | Chỉ số đo | Ý nghĩa & Vai trò trong đánh giá |
|---|---|---|
| **HB** *(Higher is Better)* | $X$, $X_1..X_4$ | Thông lượng phục vụ (xe/phút) — phản ánh năng suất hệ thống. |
| **LB** *(Lower is Better)* | $\overline{T}$, $P_{95}(T)$, $P(T>8)$, $P_b$, $W_f$, $P_f$, $L_f$, $W_i$, $W_{q,i}$, $L_i$, $L_{q,i}$, $L_{sys}$ | Thời gian đáp ứng, xác suất từ chối và độ dài hàng đợi — dùng trực tiếp cho chuẩn SLA (S1, S2). |
| **NB** *(Nominal is Best)* | $U_1, U_2, U_3, U_4$ | Độ sử dụng tài nguyên: quá cao ($>80$%) gây nút cổ chai & tăng vọt hàng đợi; quá thấp gây lãng phí nhân lực/cửa phục vụ. |

* **Lưu ý về tính không dư thừa (`pe3`):** Ba nhóm chỉ số $L, W, X$ liên hệ qua Định luật Little ($L = X \cdot W$) nên có phần dư thừa về lý thuyết; nhóm cố ý đo độc lập cả ba ($L$ bằng tích phân diện tích theo thời gian; $W$ trung bình mẫu xe; $X$ tốc độ rời) để làm phép kiểm tra nhất quán chéo (*Consistency Verification*) trên mọi lượt chạy.

## Bước 4–5: Tham số Hệ thống & Yếu tố Nghiên cứu
_Liên kết Thiết kế V2: Mục 3.1 (Bảng 5, 6, 7) và Mục 3.2 (Bảng 8); kiểm toán từng dòng tham số tại `docs/PHASE2_ARCHITECTURE_AND_ERRATA.md` §4._

* **Tham số cố định:** $c_1 = c_3 = c_4 = 2$; $1/\mu_1 = 1.5$, $1/\mu_2 = 1.25$, $1/\mu_3 = 1.5$, $1/\mu_4 = 1.0$ phút; $K_2 = K_3 = K_4 = \infty$; FCFS; $t_{warmup} = 2\,000$ phút, $t_{end} = 10\,000$ phút ($T_m = 8\,000$ phút); `bucket_width = safe_bucket_width(t_end)` (đính chính Bảng 7 để triệt tiêu lỗi `% 1024` của `LadderQueue`).
* **3 yếu tố nghiên cứu (Full Factorial Exp C):** $\lambda \in \{0.2, 0.4, 0.6, 0.7\}$ (4 mức) $\times\ c_2 \in \{1, 2, 3\}$ (3 mức) $\times\ K_1 \in \{3, 4, 6, 8\}$ (4 mức) = **48 cấu hình**.

## Bước 6: Kỹ thuật Đánh giá, Verification (`pe7`) & Validation
_Liên kết Thiết kế V2: Mục 1.4 (Kỹ thuật đánh giá), Mục 1.9 (6 chỉ báo (i)–(vi) & trace ~10 xe) và Mục 2.4; đối chiếu bài giảng `pe3`, `pe7`._

* **Kỹ thuật:** Kết hợp **giải tích** (tìm dải tham số sơ bộ và làm chuẩn đối chiếu 6 mô hình đơn + xấp xỉ Fork–Join) với **mô phỏng DES** trên `bkitevsim` (khảo sát mạng có blocking + fork-join không có nghiệm dạng tích Jackson).
* **Kiểm chứng Verification đầy đủ theo danh mục `pe7` (**29/29 unit tests PASS**):**
  1. *Top-Down Modular Design:* Tách 4 lớp LP độc lập (`drivethru/models/`) khỏi tầng cấu hình, metrics và thực nghiệm.
  2. *Anti-bugging:* Cân bằng dòng xe & đơn bếp, chốt chặn thời gian không giảm cục bộ & liên-LP (`attach_global_monotonic_guard`), fail-fast `unmatched_food_ready_count`.
  3. *Deterministic Models:* `test_m4_review_guards.py::test_9` (đầu vào hằng số khớp chính xác công thức tay $W_f=0.25, T=4.0$, sai số $< 10^{-9}$).
  4. *Run Simplified Cases:* 6 mô hình hàng đợi đơn (Exp A) và 3 ca unit test bảng Join (`test_m3_network_gate.py::test_1..3`).
  5. *Trace:* `run_hand_trace.py` (`reports/hand_trace_10_cars.md`: seed=2, 13 xe, 3 DROP, 3 chờ đồ, 121 event đơn điệu qua `MonitorLP.log_event()`, khớp công thức tay $< 10^{-12}$).
  6. *Continuity Test:* `test_m4_review_guards.py::test_10` (đổi nhẹ $\lambda: 0.60 \to 0.61$ cho $\overline{T}, U_2$ biến thiên mượt).
  7. *Degeneracy Tests:* `test_m3_network_gate.py::test_6` ($1/\mu_3 = 0.01 \to$ khớp mạng Jackson $< 5$%).
  8. *Consistency Tests:* Định luật Little $\le 1$%, tính bất biến cùng seed & đảo thứ tự fork trễ 0 (`test_m3_network_gate.py::test_4`), và hai loại dispatcher `SequentialEventDispatcher` vs. `DistributedEventDispatcher` cho cùng chỉ số (`test_m3_network_gate.py::test_7`).
  9. *Seed Independence:* `test_m4_review_guards.py::test_11` (hai nhóm seed rời nhau `1..10` vs. `11..20` không khác biệt có ý nghĩa thống kê).
* **Validation Exp A (`reports/exp_a_validation.csv`, `fig4_exp_a_validation.png`):**
  * Đạt **144/144 chỉ số PASS** (140/144 giá trị lý thuyết nằm trong $CI_{95}$), sai số tương đối cực đại **1.97%** ($\le 5$%), sai số Little cực đại **0.071%** ($\le 1$%).

## Bước 7–8: Workload CRN, Warm-up (Welch), Leftover & Kế hoạch Thí nghiệm
_Liên kết Thiết kế V2: Mục 2.5 (Bảng 4), Mục 3.3 (Bảng 10) và Mục 3.4 (Bảng 12); đối chiếu bài giảng `pe7`–`pe9`._

* **Workload CRN:** 5 luồng số ngẫu nhiên độc lập (`MultiStreamRNG`) lấy mẫu sẵn $(s_1, s_2, s_3, s_4)$ ngay lúc sinh xe, đồng bộ hoàn toàn giữa các cấu hình và biến thể so sánh.
* **Loại bỏ trạng thái quá độ (Welch — Moving average of independent replications, `pe7`):** `run_welch_warmup.py` ($R = 60$, bỏ 4 bin cắt cụt + $w = 5$ bin mép phải, `fig0_welch_warmup.png`) chứng minh hai cấu hình hội tụ chậm nhất đều vào dải bình ổn $\pm 5$% quanh $t \approx 400$ phút $\implies$ $t_{warmup} = 2\,000$ phút dư an toàn.
* **Xử lý xe còn sót (Leftover entities, `pe7`):** $\overline{T}$ tính trung bình trên tập xe đến sau $t_{warmup}$ và đã hoàn thành trước $t_{end}$; $L_i$ và $U_i$ tính bằng tích phân diện tích theo thời gian chia $T_m = 8\,000$ phút.
* **Khoảng tin cậy Student-$t$, Tiêu chí dừng & Số lần lặp `R` (`pe7`, Thiết kế §2.5 & §3.4):**
  * Nhóm dùng phân phối **Student-$t$** ($t_{0.975, R-1}$ trong `stats_utils.py`) thay vì xấp xỉ $z$ do cỡ mẫu cơ sở $R=30$ hữu hạn. Checkpoint được bảo vệ bằng `config_hash` SHA-256 + tự sao lưu `.bak`.
  * Thực hiện theo Mục 2.5 và Mục 3.4 của Thiết kế V2, mọi cấu hình chưa đạt tiêu chí độ chính xác ($CI_{95} \le 5\%$ cho `U, L, W, T` và $\le 0.3$ điểm % cho `P_b`) được tự động tăng số lần lặp $R$; các giá trị $R$ cụ thể là kết quả đo thực tế của Phase 2. Trần $R$ tối đa (`max_replications = 60`) là lựa chọn cài đặt của nhóm (Thiết kế V2 không quy định trần này).
  * *Ghi chú ngưỡng `0.3` điểm % của $P_b$:* Thiết kế V2 (§2.5) áp dụng tiêu chí nửa độ rộng $\le 0.3$ điểm % cho $P_b$ (và lưu ý ở Exp A chỉ dùng cấu hình có $P_b$ lý thuyết $\ge 1\%$ làm bằng chứng kiểm chứng $P_b$); trong hiện thực `runner.py`, nhóm kiểm đồng nhất ngưỡng $\le 0.3$ điểm % cho mọi cấu hình mạng Exp B–D (kể cả khi $P_b$ rất nhỏ gần 0%, khi đó phương sai gần 0 nên điều kiện luôn thỏa).
  * **Các cấu hình tăng $R > 30$ trong Phase 2 (đồng bộ trên cả `exp_bcd_raw_runs.csv` và summary CSV):**
    * Exp C: `C_lam7_c2_1_K1_6` ($R=50$), `C_lam7_c2_1_K1_8` ($R=60$), `C_lam7_c2_2_K1_8` ($R=40$) *(trong đó `C_lam7_c2_2_K1_8` tăng từ 30 lên 40 để đồng bộ tập seed chung `1..40` với biến thể chặn của Exp D theo đúng quy định CRN §2.5)*.
    * Exp D: `C_lam7_c2_2_K1_8` ($R=40$), `D_BLK_lam7_c2_2_K1_8` ($R=40$) *(biến thể chặn tại $\lambda=0.7$ đạt chuẩn chính xác ở $R=40$; hai biến thể ở $\lambda=0.7$ dùng chung trọn 40 seed `1..40`)*.
  * **Tổng kết 48 cấu hình Exp C (`reports/exp_c_summary.csv`):** **48/48 đạt `precision_ok`**; phân loại SLA 3 mức theo cột `sla_status`: **35 `PASS`**, **11 `FAIL`**, **2 `BOUNDARY`**. Hai cấu hình `BOUNDARY` (cột `sla_pass` ghi `False` vì chỉ tính `PASS` chắc chắn khi cận trên $CI_{95}$ nằm trọn trong ngưỡng): `C_lam7_c2_2_K1_4` ($R=30$, $\overline{T}=5.398\pm0.022$p, $P_b=4.95\pm0.18$%); `C_lam7_c2_3_K1_4` ($R=30$, $\overline{T}=5.301\pm0.021$p, $P_b=4.95\pm0.18$%).

---

## Bước 9: Phân tích Dữ liệu Có Hệ thống
_Liên kết Thiết kế V2: Mục 2.6 (Tiêu chí SLA), Mục 3.3–3.4 và bài giảng `pe9`–`pe10` (Allocation of Variation, tránh lỗi bỏ qua tương tác và sai số thí nghiệm)._

### 9.1. Phân bổ Phương sai Có Sai số Thí nghiệm `SSE` (Allocation of Variation — 1,440 lượt Exp C)
Trích từ `reports/exp_c_sensitivity_anova.csv` và trực quan hóa tại `reports/fig10_allocation_of_variation.png` (thiết kế giai thừa đầy đủ $4 \times 3 \times 4$ cân bằng trên 30 seeds đầu mỗi ô):

| Chỉ số | $\lambda$ (%) | $c_2$ (%) | $K_1$ (%) | $\lambda \times c_2$ (%) | $\lambda \times K_1$ (%) | $c_2 \times K_1$ (%) | 3-way (%) | **Sai số `SSE` (%)** | Tác động chính |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| T (Thời gian E2E) | **28.14** | **34.09** | **2.31** | **25.16** | 2.62 | 1.64 | 2.48 | **3.56** | c2(34.1%), lam(28.1%), lam_x_c2(25.2%) |
| P_b (Xác suất từ chối) | **29.2** | **0.0** | **46.46** | **0.0** | 23.33 | 0.0 | 0.0 | **1.01** | K1(46.5%), lam(29.2%), lam_x_K1(23.3%) |
| X (Thông lượng) | **99.1** | **0.0** | **0.43** | **0.0** | 0.31 | 0.0 | 0.0 | **0.16** | lam(99.1%) |
| W_f (Thời gian chờ đồ) | **0.74** | **70.26** | **0.13** | **24.94** | 0.11 | 0.79 | 0.7 | **2.34** | c2(70.3%), lam_x_c2(24.9%) |
| U2 (Độ sử dụng Payment) | **38.25** | **53.06** | **0.17** | **8.22** | 0.12 | 0.04 | 0.03 | **0.12** | c2(53.1%), lam(38.3%), lam_x_c2(8.2%) |
| P95(T) (Phân vị 95%) | **22.82** | **32.24** | **2.19** | **27.99** | 2.56 | 2.08 | 3.1 | **7.01** | c2(32.2%), lam_x_c2(28.0%), lam(22.8%) |

* **Nhận xét trọng tâm (`pe9`–`pe10`):**
  * Với **$\overline{T}$:** Không chỉ yếu tố chính $c_2$ (~34%) và $\lambda$ (~28%) mà **tương tác $\lambda \times c_2$ chiếm ~25% tổng biến thiên**, trong khi sai số thí nghiệm `SSE` chỉ ~3.6%. Điều này giải thích hiện tượng $\overline{T}$ tăng phi tuyến mạnh ở $c_2=1$ khi $\lambda: 0.6 \to 0.7$ nhưng gần như phẳng ở $c_2 \ge 2$.
  * Với **$P_b$:** $K_1$ (~46%), $\lambda$ (~29%) và tương tác $\lambda \times K_1$ (~23%) giải thích ~98% biến thiên (`SSE` ~1%); $c_2$ bằng 0% do không có back-pressure từ Payment về Order.
  * Với **$X$:** $\lambda$ chiếm ~99% biến thiên (`SSE` ~0.2%).
  * Với **$W_f$:** $c_2$ (~70%) và tương tác $\lambda \times c_2$ (~25%) chi phối vì khi Payment chậm ($c_2=1$), đồ ăn thường xong trước xe nên $W_f \approx 0$; khi $c_2 \ge 2$, xe qua Payment nhanh nên phải chờ Kitchen.

### 9.2. Đánh đổi $\overline{T}$ vs. $P_b$ (`fig9`) & Cấu hình Tối thiểu Đạt SLA theo $\lambda$
Xem `reports/fig9_pareto_T_vs_Pb.png` và `reports/exp_c_min_sla_configs.csv`:

| Kịch bản | $\lambda$ | Đạt SLA (`PASS`) | Cấu hình nhỏ nhất đạt SLA | $\overline{T} \pm CI_{95}$ (phút) | $P_b$ (%) | $U_2$ | Cấu hình khuyến nghị vận hành ($U_2 \le 0.8, P_b \le 1.5\%$) |
|---|---:|---:|---|---:|---:|---:|---|
| Light | 0.2 | 12/12 | **$c_2=1, K_1=3$** | `4.896 ± 0.020` | 0.47% | 0.245 | **$c_2=1, K_1=3$** ($\overline{T}=4.90$p, $P_b=0.47$%, $U_2=0.245$) |
| Normal | 0.4 | 12/12 | **$c_2=1, K_1=3$** | `5.544 ± 0.039` | 2.88% | 0.483 | **$c_2=1, K_1=4$** ($\overline{T}=5.69$p, $P_b=0.84$%, $U_2=0.493$) |
| Peak | 0.6 | 7/12 | **$c_2=1, K_1=4$** | `7.550 ± 0.106` | 3.11% | 0.723 | **$c_2=2, K_1=6$** ($\overline{T}=5.37$p, $P_b=0.63$%, $U_2=0.371$) |
| Heavy | 0.7 | 4/12 | **$c_2=2, K_1=6$** | `5.679 ± 0.029` | 1.34% | 0.429 | **$c_2=2, K_1=6$** ($\overline{T}=5.68$p, $P_b=1.34$%, $U_2=0.429$) |

**Chi tiết 12 cấu hình tại cao điểm Peak ($\lambda = 0.6$, chuẩn SLA: $\overline{T} \le 8.0$ phút & $P_b \le 5.0$%):**

| $c_2$ | $K_1$ | R | $\overline{T} \pm CI_{95}$ (phút) | $P_{95}(T)$ (phút) | $P(T>8)$ (%) | $P_b \pm CI_{95}$ (%) | $U_2$ | Trạng thái SLA (§2.6) |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 3 | 30 | `6.899 ± 0.078` | 14.21 | 30.62% | `7.20 ± 0.19`% | 0.692 | **FAIL** |
| 1 | 4 | 30 | `7.550 ± 0.106` | 16.01 | 36.49% | `3.11 ± 0.16`% | 0.723 | **PASS** |
| 1 | 6 | 30 | `8.153 ± 0.126` | 17.77 | 41.21% | `0.63 ± 0.07`% | 0.742 | **FAIL** |
| 1 | 8 | 30 | `8.317 ± 0.140` | 18.31 | 42.31% | `0.14 ± 0.03`% | 0.746 | **FAIL** |
| 2 | 3 | 30 | `5.024 ± 0.018` | 9.69 | 11.74% | `7.20 ± 0.19`% | 0.346 | **FAIL** |
| 2 | 4 | 30 | `5.200 ± 0.022` | 9.99 | 13.35% | `3.11 ± 0.16`% | 0.362 | **PASS** |
| 2 | 6 | 30 | `5.368 ± 0.030` | 10.35 | 15.29% | `0.63 ± 0.07`% | 0.371 | **PASS** |
| 2 | 8 | 30 | `5.415 ± 0.033` | 10.49 | 15.88% | `0.14 ± 0.03`% | 0.373 | **PASS** |
| 3 | 3 | 30 | `4.961 ± 0.017` | 9.62 | 11.33% | `7.20 ± 0.19`% | 0.231 | **FAIL** |
| 3 | 4 | 30 | `5.125 ± 0.022` | 9.90 | 12.79% | `3.11 ± 0.16`% | 0.241 | **PASS** |
| 3 | 6 | 30 | `5.283 ± 0.029` | 10.24 | 14.55% | `0.63 ± 0.07`% | 0.247 | **PASS** |
| 3 | 8 | 30 | `5.327 ± 0.032` | 10.36 | 15.11% | `0.14 ± 0.03`% | 0.249 | **PASS** |

* **Biện luận chọn cấu hình khuyến nghị `$c_2 = 2, K_1 = 6$` (mọi con số trích trực tiếp từ bảng trên):**
  1. Theo đúng §2.6 và dự liệu ở §3.3.1 Thiết kế V2, **`c2 = 1, K1 = 4`** là cấu hình nhỏ nhất đạt đúng 2 ngưỡng SLA tại Peak ($\overline{T} = 7.550 \pm 0.106$ phút, $P_b = 3.11$% nhờ ~3.1% xe bị từ chối ở Order làm giảm $\lambda_{eff}$ vào Payment). Tuy nhiên cấu hình này vẫn mất khách đáng kể, vận hành ở $U_2 = 0.723$, có đuôi trễ cao ($P_{95}(T) = 16.01$ phút, $P(T>8) = 36.49$%) và **vỡ SLA hoàn toàn ở tải Heavy** ($\lambda = 0.7$).
  2. Nâng lên **`c2 = 2, K1 = 6`** nằm trên mặt biên Pareto, giải tỏa triệt để nút cổ chai Payment ($U_2 = 0.371 \le 0.8$), kéo $\overline{T}$ xuống **5.368 phút** ($P_{95}(T) = 10.35$ phút), giảm $P_b$ còn **0.63%** và đạt SLA bền vững ở cả Peak lẫn Heavy. Nâng tiếp lên $c_2 = 3, K_1 = 6$ chỉ giảm thêm $\overline{T}$ được **0.085 phút** (1.59%) trong khi tốn thêm 1 cửa thanh toán.

### 9.3. Lợi ích Giao tiếp Không chặn (Exp D — So sánh Ghép cặp CRN `Paired CI 95%`)
Xem `reports/fig5_exp_d_blocking_vs_nonblocking.png`, `reports/exp_d_summary.csv` và `reports/exp_d_paired_crn.csv`:

| $\lambda$ | Biến thể | R | $\overline{T} \pm CI_{95}$ (phút) | $P_b \pm CI_{95}$ (%) | $U_1$ (%) | $W_f$ (phút) |
|---:|---|---:|---:|---:|---:|---:|
| 0.4 | Non-blocking | 30 | `4.900 ± 0.025` | `0.01 ± 0.01`% | 29.97% | 0.8817 |
| 0.4 | Blocking | 30 | `6.504 ± 0.054` | `0.38 ± 0.08`% | 59.54% | 0.0000 |
| 0.6 | Non-blocking | 30 | `5.415 ± 0.033` | `0.14 ± 0.03`% | 44.89% | 1.0092 |
| 0.6 | Blocking | 30 | `8.722 ± 0.070` | `5.65 ± 0.23`% | 84.67% | 0.0000 |
| 0.7 | Non-blocking | 40 | `5.786 ± 0.027` | `0.35 ± 0.05`% | 52.15% | 1.1026 |
| 0.7 | Blocking | 40 | `9.934 ± 0.055` | `11.96 ± 0.25`% | 92.15% | 0.0000 |

**Khoảng tin cậy 95% cho hiệu từng cặp CRN ($\Delta_r = Y_{\text{Blocking}, r} - Y_{\text{Non-blocking}, r}$, dùng chung trọn tập seed `1..R` lớn nhất của từng cặp theo §2.5):**

| $\lambda$ | Tập seed chung (`1..R`) | $\Delta \overline{T} \pm CI_{95}$ (phút) | $\Delta P_b \pm CI_{95}$ (điểm %) | $\Delta U_1 \pm CI_{95}$ (điểm %) | $\Delta W_f \pm CI_{95}$ (phút) | Ý nghĩa thống kê |
|---:|---:|---:|---:|---:|---:|---|
| 0.4 | 30 cặp (`1..30`) | `+1.605 ± 0.033` | `+0.362 ± 0.078` | `+29.564 ± 0.278` | `-0.8817 ± 0.0129` | Có (CI > 0) |
| 0.6 | 30 cặp (`1..30`) | `+3.308 ± 0.054` | `+5.513 ± 0.222` | `+39.781 ± 0.298` | `-1.0092 ± 0.0181` | Có (CI > 0) |
| 0.7 | 40 cặp (`1..40`) | `+4.148 ± 0.049` | `+11.610 ± 0.244` | `+39.996 ± 0.227` | `-1.1026 ± 0.0175` | Có (CI > 0) |

* Mọi khoảng tin cậy ghép cặp của $\Delta \overline{T}$, $\Delta P_b$, $\Delta U_1$ đều nằm hoàn toàn trên 0, khẳng định ở mức ý nghĩa 95% rằng giao tiếp không chặn cắt giảm **37.9%** thời gian $\overline{T}$ tại Peak ($\lambda=0.6$) và **41.8%** tại Heavy ($\lambda=0.7$), đồng thời kéo $P_b$ từ 5.65% xuống 0.14% tại Peak.

### 9.4. Kiểm toán Định luật Little
* **Trên trung bình cấu hình (Ensemble Mean):** **53/53 cấu hình** đều đạt sai số Little dưới 1% (cực đại toàn cục **0.312%**).
* **Trên từng lượt đơn lẻ (`reports/exp_c_little_audit.csv`):** Một số ít lượt đơn lẻ ở tải nặng ($\lambda=0.7, c_2=1$, nơi $\overline{L}_{sys} \approx 9$–$10$ xe) có sai số đơn lẻ tối đa **1.83%**, khớp với hiệu ứng xe còn sót tại hai biên cửa sổ $[2\,000, 10\,000]$ bậc $2L/(\lambda_{eff} T_m)$ đã phân tích ở Mục 2.4.7 Thiết kế V2 và `pe7`.

| Cấu hình | $\lambda$ | $c_2$ | $K_1$ | R | $\overline{L}_{sys}$ | Little trung bình (%) | Max 1 lượt (%) | Số lượt > 1% | Cận biên $2L/(X T_m)$ (%) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `C_lam7_c2_1_K1_8` | 0.7 | 1 | 8 | 60 | 9.02 | **0.312%** | 1.835% (seed 48) | 2/60 | 0.324% |

---

## Bước 10: Trình bày Kết quả & Hạn chế Đã biết
_Liên kết Thiết kế V2: Mục 1.9 (4 hạn chế đã biết) và Mục 3.4 (5 biểu đồ dự kiến)._

### 10.1. Danh mục Biểu đồ Phần Lõi (`reports/`)
* **5 biểu đồ dự kiến theo Thiết kế §3.4:** `fig1_e2e_time_by_lambda_c2.png`, `fig2_blocking_prob_by_K1.png`, `fig3_utilization_bottleneck.png`, `fig4_exp_a_validation.png`, `fig5_exp_d_blocking_vs_nonblocking.png`.
* **3 biểu đồ bổ sung cho Bước 8–9:** `fig0_welch_warmup.png` (Welch $R=60$), `fig9_pareto_T_vs_Pb.png` (đánh đổi $\overline{T}$–$P_b$), `fig10_allocation_of_variation.png` (phân bổ phương sai có `SSE`).

### 10.2. Hạn chế Đã biết (Nguyên văn §1.9 Thiết kế V2 & Bổ sung Phase 2)
**Bốn hạn chế của mô hình theo Mục 1.9 Thiết kế V2:**
1. Đệm không giới hạn ở Payment, Kitchen, Pickup và bãi chờ đồ loại bỏ blocking sau phục vụ; làn và bãi thực tế hữu hạn nên kết quả lạc quan khi các hàng đó dài.
2. Thời gian phục vụ phân phối mũ cần cho công thức đóng, nhưng thực tế thường ít biến động hơn, nên thời gian chờ có lẽ bị ước lượng cao.
3. Bếp chỉ được mô hình hóa như hàng đợi $M/M/c_3$ với một phân phối thời gian chuẩn bị chung, không phân biệt loại món, kích thước đơn, hay hình thức thanh toán.
4. Ngưỡng dịch vụ và thời gian phục vụ là giả định của nhóm (không có dữ liệu đo thực tế từ cửa hàng Drive-thru).

**Hạn chế bổ sung ghi nhận ở Phase 2:**
5. *Hiệu ứng xe còn sót (leftover entities) trên cửa sổ đo hữu hạn:* Ở cấu hình tải nặng ($\lambda=0.7, c_2=1$), một vài lượt chạy đơn lẻ có sai số Little lên tới 1.83% (dù trung bình cấu hình $\le 0.31\%$).
6. *Phạm vi kiểm chứng thực nghiệm:* Toàn bộ kết quả đo thực hiện trên một cấu hình máy tính duy nhất (Windows 11, CPU 4-core/8-thread, CPython 3.12.10).

---

# PHỤ LỤC A — PHẦN MỞ RỘNG TÙY CHỌN: SO SÁNH 3 KIẾN TRÚC THỰC THI DES (M5)

_Ghi chú phạm vi: Đây là phần mở rộng tùy chọn (theo gợi ý `BkSysCoLogicalProcess`/`BkSysFuture` ở Thiết kế §1.7–1.8 và tài liệu PDES), tách riêng khỏi 10 bước đánh giá lõi của mạng Drive-thru. Chi tiết kỹ thuật xem thêm tại `ROADMAP_M5_MULTITHREAD.md`._

### A.1. Kiến trúc Ba Engine & Hạn chế Đã biết của M5
* **Single-thread (`sequential_engine.py`):** Thực thi trực tiếp 6 LP từ `drivethru/models/` trên `SequentialEventDispatcher`.
* **Virtual Multi-thread (`coroutine_engine.py` — Mô hình lai):** Dùng lớp bọc mỏng Composition (`CoCarSourceLP`, `CoStationLP`, `CoPickupLP`, `CoMonitorLP` kế thừa `SafeCoLogicalProcess`) ủy quyền xử lý event-handler sang `models/` bên trong, kết hợp `BkSysCoEventLoop` và **`BkSysFuture` + `asyncio.Task` tại điểm Join của `CoPickupLP`**.
* **OS Multi-thread (`multithread_engine.py`):** Thực thi trực tiếp 6 LP từ `drivethru/models/` trên 6 `threading.Thread` với `ThreadedClockCoordinator` (đồng bộ bảo thủ không có lookahead — *zero-lookahead conservative barrier*).
* **Hạn chế đã biết của phần mở rộng M5:** (i) Biến thể Coroutine là **mô hình lai** (event-handler + `BkSysFuture` ở Join), không phải mô hình hướng tiến trình thuần (mỗi xe một coroutine dùng `asyncio.gather`); (ii) Bộ nhớ báo cáo là **Python Heap Peak** đo bằng `tracemalloc` (chưa gồm stack cấp phát ở mức hệ điều hành của 6 OS threads); (iii) Số tuyệt đối (`wall_time`, `events/s`) đo trên 1 máy Windows 11, CPython 3.12.10 (có GIL).

### A.2. Kết quả Benchmark 1-Core trên Mạng Drive-thru (`reports/exp_m5_benchmark.csv`, `fig6`, `fig7`)

| Kịch bản | Kiến trúc | $\lambda$ | $t_{end}$ | Events | Wall (s) ± CI95 | Slowdown | Thr (ev/s) | Heap (MB) | 1LP% | ActLP | Car Err |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `scale_t2000_lam06` | **sequential** | 0.6 | 2,000 | 17,633 | `0.4455 ± 0.0597` | **1.00x** | 40,854 | 0.111 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t2000_lam06` | **coroutine** | 0.6 | 2,000 | 17,633 | `1.0894 ± 0.0947` | **2.45x** | 16,405 | 0.138 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t2000_lam06` | **multithread** | 0.6 | 2,000 | 17,633 | `1.9139 ± 0.0710` | **4.30x** | 9,226 | 0.136 | 82.1% | 1.20 | `0.0e+00` |
| `scale_t5000_lam06` | **sequential** | 0.6 | 5,000 | 44,257 | `0.9857 ± 0.0810` | **1.00x** | 45,399 | 0.241 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t5000_lam06` | **coroutine** | 0.6 | 5,000 | 44,257 | `2.5797 ± 0.1207` | **2.62x** | 17,217 | 0.257 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t5000_lam06` | **multithread** | 0.6 | 5,000 | 44,257 | `4.9923 ± 0.1973` | **5.06x** | 8,891 | 0.266 | 82.1% | 1.20 | `0.0e+00` |
| `scale_t10000_lam06` | **sequential** | 0.6 | 10,000 | 89,157 | `2.0005 ± 0.1103` | **1.00x** | 44,788 | 0.453 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t10000_lam06` | **coroutine** | 0.6 | 10,000 | 89,157 | `5.4773 ± 0.3016` | **2.74x** | 16,362 | 0.469 | 100.0% | 1.00 | `0.0e+00` |
| `scale_t10000_lam06` | **multithread** | 0.6 | 10,000 | 89,157 | `10.1176 ± 0.3972` | **5.06x** | 8,832 | 0.478 | 82.1% | 1.20 | `0.0e+00` |
| `load_lam02_t5000` | **sequential** | 0.2 | 5,000 | 14,797 | `0.3350 ± 0.0467` | **1.00x** | 45,440 | 0.107 | 100.0% | 1.00 | `0.0e+00` |
| `load_lam02_t5000` | **coroutine** | 0.2 | 5,000 | 14,797 | `0.9221 ± 0.0634` | **2.75x** | 16,157 | 0.131 | 100.0% | 1.00 | `0.0e+00` |
| `load_lam02_t5000` | **multithread** | 0.2 | 5,000 | 14,797 | `1.6462 ± 0.0643` | **4.91x** | 9,003 | 0.134 | 84.3% | 1.16 | `0.0e+00` |
| `load_lam07_t5000` | **sequential** | 0.7 | 5,000 | 51,439 | `1.2793 ± 0.1915` | **1.00x** | 41,514 | 0.273 | 100.0% | 1.00 | `0.0e+00` |
| `load_lam07_t5000` | **coroutine** | 0.7 | 5,000 | 51,439 | `3.2134 ± 0.3170` | **2.51x** | 16,233 | 0.290 | 100.0% | 1.00 | `0.0e+00` |
| `load_lam07_t5000` | **multithread** | 0.7 | 5,000 | 51,439 | `5.8156 ± 0.3943` | **4.55x** | 8,897 | 0.299 | 81.3% | 1.21 | `0.0e+00` |

### A.3. Thí nghiệm Đối chứng Điều kiện Tăng tốc OS-Thread (`reports/exp_m5_speedup_probe.csv`, `fig8`)

| Chế độ kiểm chứng | Kiến trúc | Wall (s) ± CI95 | Speedup vs Single | CPU/Wall | ActLP | 1LP% | Checksum |
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

* **Kết luận Phụ lục A:** Cả 3 kiến trúc khớp tuyệt đối trên từng xe (`Car Err = 0.0e+00`, 0 causality error, 0 deadlock). Trên mạng Drive-thru, OS Multi-thread chậm ~4.3–5.1x chủ yếu do kiến trúc **zero-lookahead** (~82% nhịp chỉ có 1 LP chạy, trần song song hóa ~1.2x) cộng hưởng với độ hạt sự kiện siêu nhẹ và CPython GIL; thí nghiệm đối chứng (Chế độ 3) xác nhận chính `ThreadedClockCoordinator` đạt tăng tốc đa nhân thật khi có lookahead dương kết hợp tác vụ giải phóng GIL.
