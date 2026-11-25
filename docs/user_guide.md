# Hướng dẫn Sử dụng Giao diện Streamlit & Kịch bản Demo 3–5 phút (`app.py`)

**Phụ trách:** Thành viên Dũng *(đồng bộ hợp đồng `api-v1.0` với Thái – Trung – Linh)*

---

## 1. Cài đặt môi trường & Khởi chạy

- **Yêu cầu:** Python **3.10 trở lên** (đã kiểm chứng trên Python 3.10 và 3.12).
- **Bước 1 — Cài đặt thư viện dùng chung từ `requirements.txt`:**
  ```bash
  pip install -r requirements.txt
  ```
  *(Gồm `matplotlib>=3.7`, `pytest>=7.4`, `streamlit>=1.32`, `pandas>=2.0`; lõi `dnastore/` và toàn bộ unit/integration tests chạy bằng 100% thư viện chuẩn Python.)*
- **Bước 2 — Khởi chạy ứng dụng web Streamlit:**
  ```bash
  streamlit run app.py
  ```
  *(Trên Windows nếu dùng đường dẫn Python cụ thể: `& "C:/Program Files/Python312/python.exe" -m streamlit run app.py`.)*
- Trình duyệt sẽ mở tại địa chỉ `http://localhost:8501`. Nhấn `Ctrl + C` trong cửa sổ Terminal để dừng ứng dụng.

---

## 2. Ý nghĩa các tham số trên thanh cấu hình (Sidebar)

Tất cả tham số được chuyển thành dict `RunConfig` gồm đúng **8 khóa hợp lệ** theo `docs/api_contract.md` (không truyền khóa lạ như `dropout_scope`):

| Khu vực | Tham số trên UI | Miền giá trị / Mặc định | Ý nghĩa kỹ thuật |
| :--- | :--- | :--- | :--- |
| **1. Nạp tệp** | Chọn mẫu `data/samples/` hoặc Upload từ máy | `TXT` / `PNG` / `PDF` (khuyến nghị `<= 100 KB`) | Truyền trực tiếp `(filename, raw_bytes)` vào `dnastore.run_simulation()`. |
| **2. ECC** | `ecc_mode` | `NONE`, `XOR_PARITY`, `REPLICATION_3X`, `HYBRID` | Chế độ dự phòng; UI tự động gán `copies=3` khi chọn `REPLICATION_3X` / `HYBRID` và `copies=1` cho 2 chế độ còn lại. |
| **2. ECC** | `chunk_size` | `16` / `32` / `64` bytes (mặc định `32`) | Kích thước mỗi khối byte trước khi mã hóa 2 bit/nt (`32 B = 128 nt`). |
| **2. ECC** | `group_size` | `2 – 8` (mặc định `4`) | Số DATA packet trong mỗi nhóm XOR parity (`4 DATA + 1 PARITY`). |
| **3. Kênh nhiễu** | `dropout_rate` (%) | `0% – 30%` (mặc định `5%`) | Xác suất mất từng packet lưu kho (`copy_id` độc lập); UI chia `100.0` trước khi gọi API. |
| **3. Kênh nhiễu** | `substitution_rate` (%/base) | `0.0% – 2.0%`, bước `0.1%` (mặc định `0.0%`) | Xác suất đổi 1 nucleotide sang 1 trong 3 base còn lại; UI chia `100.0` trước khi gọi API. |
| **3. Kênh nhiễu** | `read_count` | `1 – 5` (mặc định `1`) | Số bản đọc sinh ra cho mỗi packet sống sót sau dropout. |
| **3. Kênh nhiễu** | `seed` | Số nguyên `>= 0` (mặc định `42`) | Hạt giống ngẫu nhiên cố định để tái lập chính xác cùng một lần thử (`T08`). |

---

## 3. Cấu trúc 4 Tab của giao diện `app.py`

1. **Tab 1 — Mô phỏng Toàn luồng:**
   - Gọi `dnastore.encode_file()` (cache bằng `@st.cache_data`) để hiển thị kích thước gốc, số DATA packet, tổng packet lưu kho, tổng nucleotide, Overhead (%), mật độ `bit/nt`, `GC-content`, Metadata JSON, bảng packet kèm mã `crc32` và xem đầy đủ chuỗi `A/T/G/C` của từng packet.
   - Bấm **"Chạy Mô phỏng"** để gọi `dnastore.run_simulation()` lưu kết quả vào `st.session_state`, hiển thị đầy đủ 21 trường chuẩn (`success`, `reason`, `reason_detail`, `sha256_match`, `n_packets`, `n_packets_lost`, `n_substituted_bases`, `n_nucleotides`, `elapsed_ms`, `backends`) và đối chiếu SHA-256 gốc với SHA-256 phục hồi.
   - Nút tải tệp (`st.download_button`) **chỉ hiển thị** khi `success=True`, `sha256_match=True` và `recovered_bytes is not None`.
2. **Tab 2 — Preset Demo Trực tiếp (3 ca):** Cung cấp 3 nút bấm một chạm khớp tuyệt đối `dnastore/cli.py` (kèm nút chạy liên tiếp cả 3 ca) và tự kiểm chứng verdict thật.
3. **Tab 3 — Thực nghiệm & Đồ thị (2.160 lượt):** Trình bày 3 biểu đồ định lượng từ dữ liệu chạy thật `backends=real` (`chart_dropout_recovery.png`, `chart_substitution_scaling.png`, `chart_overhead_runtime.png`), bảng lọc tương tác trên `benchmark_summary.csv` (72 cấu hình), nút tải CSV và bảng `test_cases.csv` (24/24 ca T01–T08).
4. **Tab 4 — Kiến trúc & Hợp đồng `api-v1.0`:** Hiển thị sơ đồ `docs/architecture.png`, phác thảo `docs/ui_wireframe.png`, danh sách tệp trong `StorageController` phiên hiện tại và lệnh CLI dự phòng.

---

## 4. Kịch bản vận hành Demo trực tiếp 3–5 phút

1. **0:00 – 0:45 (Tab 1 — Mã hóa & Kho ADN):** Chọn `sample_medium.txt` (`800 B`), chế độ `XOR_PARITY (4+1)`. Chỉ rõ tệp chia thành `25 DATA + 7 PARITY = 32 packet` (`4.096 nt`, Overhead `+28,0%`, GC `46,56%`), mở bảng xem `crc32` và chuỗi `A/T/G/C` (không có chữ `'X'`).
2. **0:45 – 1:30 (Tab 2 — Preset 1: Không lỗi):** Bấm **Chạy Kịch bản 1** (`dropout=0%`, `sub=0%`, `seed=42`) → kết quả `success=True`, `reason=OK_CLEAN`, `sha256_match=True`, `backends=100% real`, tải xuống tệp trùng từng byte.
3. **1:30 – 2:30 (Tab 2 — Preset 2: Mất 1 packet):** Bấm **Chạy Kịch bản 2** (`force_drop=[["DATA", 1]]`, `seed=42`) → kết quả `success=True`, `reason=OK_RECOVERED`, `n_packets_lost=1`, `sha256_match=True`. Giải thích cơ chế XOR parity 4+1 giải duy nhất 1 khối mất trong nhóm 0 mà không truy cập tệp gốc hay `expected_sha256`.
4. **2:30 – 3:15 (Tab 2 — Preset 3: Mất 2 packet cùng nhóm):** Bấm **Chạy Kịch bản 3** (`force_drop=[["DATA", 0], ["DATA", 1]]`, `seed=42`) → hệ thống báo thất bại trung thực (`success=False`, `reason=FAIL_UNRECOVERABLE`, `sha256_match=False`, `recovered_bytes=None`), nút tải tệp bị khóa hoàn toàn.
5. **3:15 – 4:30 (Tab 3 — Đồ thị thực nghiệm):** Mở 3 biểu đồ thật từ `2.160` lượt chạy `backends=real` để trình bày sự đánh đổi giữa độ tin cậy, Overhead (`0%` → `+28%` → `+200%` → `+284%`) và thời gian xử lý.

---

## 5. Phương án dự phòng & Kiểm tra máy sạch trước giờ bảo vệ

Nếu trình duyệt hoặc máy trình chiếu gặp sự cố với Streamlit, chạy ngay lệnh dự phòng của hệ thống:
```bash
python -m dnastore.cli demo
```
Bộ lệnh kiểm chứng nhanh trên máy sạch:
```bash
python -m unittest discover -s tests -v
python -m pytest -q
python -m dnastore.cli demo
streamlit run app.py
```
