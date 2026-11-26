# Tiêu đề hình: bản ngắn (trong ảnh) và bản đầy đủ (dùng làm caption LaTeX)

Từ phiên bản này, tiêu đề **bên trong ảnh** được rút gọn để không trùng với caption trong báo cáo. Mỗi hình có bản `.png` (xem nhanh) và bản `.pdf` vector (chèn vào LaTeX). Tiêu đề đầy đủ dưới đây là nội dung gốc trước khi rút gọn; dùng làm gợi ý caption.

| Hình | Tiêu đề trong ảnh (ngắn) | Tiêu đề gốc (đầy đủ, dùng làm caption) |
|---|---|---|
| fig0 | Kiểm tra warm-up bằng phương pháp Welch | Kiểm chứng độ đủ Warm-up bằng Phương pháp Welch (R=60 seeds, Δt=50p, w=5, bỏ w bin mép phải) |
| fig1 | T và P95(T) theo λ và c2 | Biểu đồ 1: Thời gian end-to-end T và P95(T) theo λ và số cửa Payment c2 (95% CI) |
| fig2 | Xác suất từ chối P_b theo K1 | Biểu đồ 2: Xác suất từ chối P_b (%) theo sức chứa làn Order K1 (95% CI) |
| fig3 | Độ sử dụng U_i theo λ | Biểu đồ 3: Độ sử dụng U_i của bốn trạm theo λ nhằm xác định nút cổ chai (95% CI) |
| fig4 | Lý thuyết và mô phỏng — Exp A | Biểu đồ 4: So sánh Lý thuyết Giải tích và Mô phỏng cho 6 mô hình đơn (Exp A, R=30) |
| fig5 | Không chặn và có chặn — Exp D | Biểu đồ 5: So sánh Giao tiếp Không chặn vs. Có chặn giữa Order và Kitchen (Exp D, c2=2, K1=8) |
| fig6 | M5: Wall-time và throughput của 3 kiến trúc | M5 Benchmark (Windows, CPython 3.12 GIL, 1-Core): So sánh 3 Kiến trúc DES (Car-by-Car Error = 0.0) |
| fig7 | M5: Bộ nhớ và overhead | M5 Benchmark: Python Heap (tracemalloc) và Phân rã Overhead trên Windows (CPython 3.12) |
| fig8 | M5: Zero-lookahead và GIL | Thí nghiệm Đối chứng M5: Tách biệt Tác động của Zero-Lookahead và CPython GIL trên CPU 4-Core |
| fig9 | Đánh đổi giữa T và P_b | Biểu đồ 9 (Bước 9): Đánh đổi (Trade-off / Pareto) giữa Thời gian E2E (T) và Xác suất Từ chối (P_b) |
| fig10 | Phân bổ phương sai — Exp C | Biểu đồ 10 (Bước 9): Phân bổ Phương sai (Allocation of Variation) trên 1,440 lượt Exp C |

Các tiêu đề con của từng panel, ví dụ "(a) Kịch bản Peak (λ = 0.6)...", giữ nguyên.

## Ghi chú về fig9 (sửa ở phiên bản này)
- Vùng xanh "đạt SLA" trước đây vẽ lên quá đường T = 8 (dùng tỉ lệ trục thay vì giá trị dữ liệu); nay chỉ phủ T ≤ 8 và P_b ≤ 5%.
- Đường Pareto nay dùng dung sai (P_b chênh dưới 0,05 điểm %, T chênh dưới 0,02 phút coi là hoà), vì CRN làm P_b gần như trùng nhau giữa các c2 nhưng không giống hệt từng bit. Kết quả: đường Pareto chạy theo c2 = 3 (T thấp nhất ở mọi K1). Đây là Pareto theo hai chỉ số (T, P_b), chưa tính chi phí thêm cửa Payment.
