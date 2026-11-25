# Dự thảo Báo cáo Phần 4 — Giao diện Ứng dụng Streamlit & Trình bày Kết quả Thực nghiệm (Thành viên Dũng)

> **Lưu ý đồng bộ báo cáo:** Toàn bộ bảng số liệu và biểu đồ dưới đây sử dụng thống nhất **100% dữ liệu chạy thật (`backends = {'encode_file': 'real', 'apply_noise': 'real', 'decode_or_recover': 'real'}`)** từ `results/benchmark_summary.csv` (`2.160` lượt chạy), `results/test_cases.csv` (`24/24` ca T01–T08) và `results/experiment_conditions.json`, sẵn sàng để Thái ghép trực tiếp cùng phần phân tích của Linh vào **Phần 4** Báo cáo cuối kỳ.

---

## 4.1. Thiết kế Giao diện Ứng dụng Streamlit (`app.py`) & Tích hợp `api-v1.0`

Để giảng viên và người dùng có thể kiểm chứng trực quan toàn bộ vòng đời lưu trữ dữ liệu trên phân tử ADN mà không cần chỉnh sửa mã nguồn, nhóm xây dựng ứng dụng web tương tác bằng **Streamlit** (`app.py`), kết nối trực tiếp vào gói lõi `dnastore` theo đúng hợp đồng đóng băng **`api-v1.0`** (`docs/api_contract.md`).

- **Nguyên tắc kiến trúc tách lớp:** `app.py` không tự viết lại logic mã hóa, gây lỗi hay phục hồi mà gọi hoàn toàn qua API công khai của nhóm (`dnastore.encode_file` cho bước xem trước cấu trúc packet/ADN và `dnastore.run_simulation` cho chu trình 9 bước chính thức).
- **Kiểm soát cấu hình chặt chẽ (`RunConfig`):** Thanh cấu hình bên trái gom tham số thành dict gồm đúng **8 khóa hợp lệ** (`chunk_size`, `ecc_mode`, `group_size`, `copies`, `dropout_rate`, `substitution_rate`, `read_count`, `force_drop`), tự động thiết lập `copies = 3` khi người dùng chọn `REPLICATION_3X` hoặc `HYBRID` và không truyền khóa lạ (như `dropout_scope`) để bảo đảm tương thích 100% với bộ kiểm tra `RunConfig.from_dict()`.
- **Quản trị trạng thái & Bảo đảm tính trung thực học thuật:**
  - Dùng `@st.cache_data` để cache bước xem trước `encode_file()`, giúp kéo thanh trượt nhiễu mượt mà không mã hóa lại tệp.
  - Duy trì 1 phiên `StorageController()` bộ nhớ trong (chốt `OI-18`) và lưu kết quả chạy trong `st.session_state` để thao tác tải tệp không làm mất màn hình đối chiếu kết quả.
  - Hiển thị công khai trường `backends` (`real`/`mock`) trên mọi kết quả và **chỉ mở khóa nút `st.download_button`** khi đồng thời thỏa mãn `success=True`, `sha256_match=True` và `recovered_bytes is not None`.
- **Tổ chức 4 Tab trực quan:** (1) *Mô phỏng toàn luồng* (hỗ trợ upload `TXT`/`PNG`/`PDF` hoặc chọn nhanh `data/samples/`, xem Metadata, bảng packet kèm `crc32` và chuỗi `A/T/G/C`); (2) *Preset Demo Trực tiếp 3 ca* (khớp 100% `dnastore/cli.py`: `OK_CLEAN`, `OK_RECOVERED`, `FAIL_UNRECOVERABLE`); (3) *Thực nghiệm & Đồ thị* (hiển thị 3 biểu đồ thật và bảng lọc CSV); (4) *Kiến trúc & Hợp đồng `api-v1.0`* (nhúng `docs/architecture.png`, `docs/ui_wireframe.png` và danh sách tệp trong kho phiên hiện tại).

---

## 4.2. Tổng quan Thiết lập Thực nghiệm & Trình bày Kết quả Định lượng (2.160 lượt `backends = real`)

Theo `results/experiment_conditions.json`, bộ thực nghiệm chính thức thực hiện **2.160 lượt mô phỏng** qua `dnastore.orchestrator.run_simulation()` trên 3 tệp văn bản tiếng Việt UTF-8 trong `data/samples/`: `sample_short.txt` (`166 B`), `sample_medium.txt` (`800 B`, `25 DATA packets`) và `sample_long.txt` (`1.955 B`), với cấu hình cơ sở `chunk_size = 32 B`, `group_size = 4`, `copies = 3` (cho `REPLICATION_3X`/`HYBRID`) và `30 random seeds / mức nhiễu`. Song song, bộ kiểm thử kịch bản `results/test_cases.csv` đạt **24/24 ca PASS** (phủ đầy đủ `T01–T08`) và toàn bộ unit/integration tests trong `tests/` đạt **100%**.

### Bảng 4.1. Tổng hợp tỷ lệ tái tạo toàn tệp (%), Overhead (%) và thời gian xử lý trung bình (ms) trên `sample_medium.txt` (800 B, 30 seeds/mức)

| Chế độ ECC | Overhead (%) | A. Chỉ Dropout 0 / 5 / 10 / 15 / 20% | B. Dropout + Sub 0,1% (0 / 5 / 10 / 15 / 20%) | C. Quét Sub 0 / 0,1 / 0,5 / 1,0 / 2,0% (Drop 0%) | Thời gian TB Kịch bản B (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **NONE** | +0,00% | 100% / 30,0% / 6,7% / 0% / 0% | 6,7% / 0% / 0% / 0% / 0% | 100% / 0% / 0% / 0% / 0% | 7,03 ms |
| **XOR_PARITY (4+1)** | +28,00% | 100% / 83,3% / 70,0% / 33,3% / 13,3% | 56,7% / 20,0% / 20,0% / 10,0% / 0% | 100% / 36,7% / 0% / 0% / 0% | 10,00 ms |
| **REPLICATION_3X (3x)** | +200,00% | 100% / 100% / 100% / 90,0% / 80,0% | 100% / 90,0% / 76,7% / 70,0% / 60,0% | 100% / 100% / 100% / 43,3% / 13,3% | 31,64 ms |
| **HYBRID (XOR + 3x)** | +284,00% | 100% / 100% / 100% / 100% / 100% | 100% / 100% / 100% / 100% / 96,7% | 100% / 100% / 100% / 96,7% / 53,3% | 41,41 ms |

### Bảng 4.2. Ảnh hưởng của kích thước tệp TXT tại mức nhiễu 5% Dropout + 0,1% Substitution (Kịch bản D, 30 seeds/mức)

| Tệp mẫu | Kích thước | NONE | XOR_PARITY (4+1) | REPLICATION_3X | HYBRID (XOR + 3x) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `sample_short.txt` | 166 B | 36,67% (ov +15,66%) | 80,00% (ov +54,22%) | 96,67% (ov +246,99%) | 100,00% (ov +362,65%) |
| `sample_medium.txt` | 800 B | 0,00% (ov +0,00%) | 40,00% (ov +28,00%) | 83,33% (ov +200,00%) | 100,00% (ov +284,00%) |
| `sample_long.txt` | 1.955 B | 0,00% (ov +1,48%) | 10,00% (ov +27,67%) | 76,67% (ov +204,45%) | 100,00% (ov +283,02%) |

### Phân tích các trục đánh đổi qua 3 biểu đồ thực nghiệm (`results/chart_*.png`)

1. **Hiệu quả cứu lỗi mất đoạn (`chart_dropout_recovery.png`):** Khi chỉ có lỗi dropout `10%` trên `sample_medium.txt`, `XOR_PARITY (4+1)` chỉ tốn thêm **+28,0% overhead** nhưng nâng tỷ lệ tái tạo toàn tệp từ **6,67%** (`NONE`) lên **70,0%**. Tuy nhiên, khi cộng thêm lỗi thay thế `0,1%/base`, `NONE` gần như thất bại tuyệt đối (**0%–6,67%**), còn `XOR_PARITY` giảm xuống **20,0%** tại dropout `10%` vì chỉ cần 2 packet trong cùng nhóm bị mất hoặc sai CRC-32 là vượt giới hạn 1 ẩn của parity đơn.
2. **Sức chống chịu substitution & quy mô tệp (`chart_substitution_scaling.png`):** Nhờ kết hợp biểu quyết đa số trên 3 bản sao và cơ chế CRC-32 fallback giải quyết hòa phiếu `1–1`, `REPLICATION_3X` giữ được **100%** tới mức substitution `0,5%/base`, còn `HYBRID` đạt **96,67%** tại mức khắc nghiệt `1,0%/base` (hoặc `20% dropout + 0,1% sub`). Khi kích thước tệp tăng từ `166 B` lên `1.955 B` (số nhóm XOR tăng mạnh), tỷ lệ tái tạo của `XOR_PARITY` giảm từ **80,0%** xuống **10,0%** tại mức `5% drop + 0,1% sub`, trong khi `HYBRID` vẫn giữ trọn **100,0%** trên cả 3 kích thước.
3. **Đánh đổi chi phí lưu trữ & thời gian xử lý (`chart_overhead_runtime.png`):** Độ tin cậy cao nhất của `HYBRID` đi kèm mức overhead **+283% đến +284%** (cho tệp vừa/dài) và thời gian chạy trung bình tăng từ **6,5–7,2 ms** (`NONE`) và **9,4–10,7 ms** (`XOR_PARITY`) lên **31,6–32,8 ms** (`REPLICATION_3X`) và **41,4–47,4 ms** (`HYBRID`) trên `sample_medium.txt` do số lượng bản đọc cần duyệt biểu quyết đa số theo từng vị trí nucleotide tăng gấp `3–3,84` lần.

---

## 4.3. Minh họa 3 kịch bản Demo chuẩn & Lưu ý giới hạn mô hình

- **3 kịch bản chạy trực tiếp trên Tab 2 `app.py` (tệp `sample_medium.txt`, 800 B, `seed=42`, `backends=real`):**
  1. *Không lỗi:* `success=True`, `reason=OK_CLEAN`, `n_packets=32`, `n_packets_lost=0`, `sha256_match=True`.
  2. *Mất 1 DATA packet (`force_drop=[["DATA", 1]]`):* `success=True`, `reason=OK_RECOVERED`, `n_packets_lost=1`, `sha256_match=True` — XOR parity khôi phục chính xác không dùng bản gốc.
  3. *Mất 2 DATA packet cùng nhóm (`force_drop=[["DATA", 0], ["DATA", 1]]`):* `success=False`, `reason=FAIL_UNRECOVERABLE`, `n_packets_lost=2`, `sha256_match=False`, `recovered_bytes=None` — nút tải tệp bị khóa hoàn toàn.
- **Giới hạn học thuật cần nêu rõ khi trình bày:** Mô hình là mô phỏng phần mềm (không tổng hợp ADN thật); trường `crc32` và địa chỉ `packet_id`/`group_id` hiện lưu trong cấu trúc `dict` ngoài chuỗi ADN nên chưa tính vào Overhead thực tế; kênh nhiễu chưa mô phỏng lỗi chèn/xóa nucleotide (`InDel`); chưa áp dụng mã Reed–Solomon/DNA Fountain, cân bằng GC ép buộc hay bảo vệ metadata bằng ECC riêng.
