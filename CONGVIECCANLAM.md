# Công việc cần làm tiếp theo để chốt nộp bài (Mục 4.4)

Tài liệu này tổng hợp các hạng mục còn lại cần hoàn thành tính từ thời điểm **đã tích hợp xong 100% lõi mô phỏng `dnastore/` (`backends = real`, 48/48 test PASS, 2.160 lượt benchmark thật)** cho đến khi đóng gói nộp bài và demo hoàn chỉnh.

---

## Hiện trạng kiểm tra trực tiếp trên gói `dna-storage/`

| Hạng mục | Trạng thái hiện tại | Ghi chú |
| :--- | :---: | :--- |
| Lõi `dnastore/` (Thái + Trung + Linh) | **Đã xong** | 14 file trong `dnastore/`, 48/48 test PASS, `cli.py demo` chạy chuẩn 3 ca. |
| Thực nghiệm định lượng `results/` | **Đã xong** | Đã có `test_cases.csv` (24/24), `benchmark_results.csv` (2.160 lượt), `benchmark_summary.csv`, `experiment_conditions.json`, và 2 biểu đồ PNG. |
| Kho Git chung & Tag `api-v1.0` | **Đã xong** | Đã đẩy mã nguồn lên nhánh `main` tại `https://github.com/299quanglinh/ADN_Stogare`, chốt OI-17 (`requirements.txt`), quy ước nhánh và gắn tag `api-v1.0` (OI-19). |
| Giao diện Streamlit (`app.py`) | **Chưa có** | Chưa có tệp `app.py` trong `dna-storage/` (Dũng phát triển trên nhánh riêng dựa trên tag `api-v1.0`). |
| Thư mục tài liệu `docs/` | **Đang hoàn thiện** | Đã có `docs/api_contract.md` và `docs/architecture.png`; còn bổ sung `docs/user_guide.md` (Dũng) và `docs/noise_spec.md` (Linh). |
| Tệp mẫu nhị phân (`PNG` / `PDF`) | **Chưa có** | `data/samples/` mới có 3 tệp `.txt` (hiện `test_orchestrator.py` kiểm thử nhị phân bằng `PNGLIKE` trong bộ nhớ). |

---

## Kế hoạch triển khai chi tiết theo từng thành viên

### 1. Thái — Làm ngay *(ưu tiên mở đường bàn giao cho Dũng)*

- [x] **Đưa gói `dna-storage/` lên kho Git chung:**
  - Đã khởi tạo Git và push mã nguồn lên nhánh `main` tại `https://github.com/299quanglinh/ADN_Stogare`.
- [x] **Chốt OI-17 (`requirements.txt`):**
  - Đã kiểm chứng cài đặt sạch trên môi trường `.venv` mới (`pip install -r requirements.txt` -> `pip check` không lỗi, `pytest` đạt `48 passed, 40 subtests passed`, `dnastore.cli demo` 3/3 OK, `Streamlit 1.67.0`), hỗ trợ Python 3.10+.
- [x] **Chốt OI-19 (Quy ước nhánh & Tag `api-v1.0`):**
  - Đã thống nhất quy ước nhánh (`main` ổn định; Dũng tạo nhánh `feat/streamlit-ui` và không sửa logic lõi `dnastore/`), đồng thời đóng băng API bằng Git tag `api-v1.0`.
- [x] **Bổ sung tài liệu kiến trúc vào `docs/`:**
  - Đã tạo [docs/api_contract.md](./docs/api_contract.md) và [docs/architecture.png](./docs/architecture.png) và đẩy lên repo.
- [ ] **Gửi bàn giao trực tiếp cho Dũng:** Gửi link repo, tag `api-v1.0`, tài liệu [docs/api_contract.md](./docs/api_contract.md) và 3 ca preset demo chuẩn để Dũng bắt tay code `app.py`.

---

### 2. Dũng — Ưu tiên cao nhất *(Giao diện Streamlit & Tài liệu hướng dẫn)*

- [ ] **Xây dựng giao diện web `dna-storage/app.py` (Streamlit):**
  - **Khu vực nạp tệp:** Hỗ trợ upload tệp (`TXT`/`PNG`/`PDF` nhỏ) hoặc chọn nhanh từ `data/samples/`.
  - **Hiển thị dữ liệu mã hóa:** Hiển thị kích thước tệp gốc, số packet, bảng thông tin packet (`packet_id`, `kind`, `group_id`, `copy_id`, `payload_len`, `crc32`) và đoạn chuỗi ADN mẫu (`A/T/G/C`) *(lưu ý: gọi qua hàm `dnastore.encode_file` hoặc hiển thị thống kê từ kết quả chạy để người dùng quan sát được packet/chuỗi ADN)*.
  - **Bảng điều khiển thông số kênh nhiễu & ECC:**
    - Ô chọn `ecc_mode`: `NONE`, `XOR_PARITY`, `REPLICATION_3X`, `HYBRID` *(nhớ truyền `copies=3` khi chọn `REPLICATION_3X` hoặc `HYBRID`, và không truyền `dropout_scope` vào dict `config` của `RunConfig`)*.
    - Thanh trượt `dropout_rate`: `0% – 30%` *(chia `100.0` trước khi truyền vào `run_simulation`)*.
    - Thanh trượt `substitution_rate`: `0.0% – 2.0%`, bước `0.1%` *(chia `100.0` trước khi truyền vào `run_simulation`)*.
    - Ô nhập `read_count`: `1 – 5`.
    - Ô nhập `seed`: mặc định `42`.
  - **3 nút Preset cho kịch bản Demo trực tiếp:**
    1. *Kịch bản 1 (Không lỗi):* `ecc_mode="XOR_PARITY"`, `dropout_rate=0.0`, `substitution_rate=0.0`, `seed=42` → kỳ vọng `OK_CLEAN`.
    2. *Kịch bản 2 (Mất 1 packet, parity sửa được):* `ecc_mode="XOR_PARITY"`, `force_drop=[["DATA", 1]]`, `seed=42` → kỳ vọng `OK_RECOVERED`.
    3. *Kịch bản 3 (Mất 2 packet cùng nhóm, vượt ngưỡng sửa):* `ecc_mode="XOR_PARITY"`, `force_drop=[["DATA", 0], ["DATA", 1]]`, `seed=42` → kỳ vọng `FAIL_UNRECOVERABLE`.
  - **Thực thi & hiển thị kết quả:**
    - Gọi trực tiếp `run_simulation((file.name, file.getvalue()), config, seed=seed)`.
    - Hiển thị rõ `success`, `reason`, `reason_detail`, `sha256_match`, `n_packets`, `n_packets_lost`, `n_substituted_bases`, `n_nucleotides`, `elapsed_ms`, `backends`.
    - Khi `success=True` và `recovered_bytes is not None`, cung cấp nút tải tệp khôi phục (`st.download_button`).
  - **Trình bày tối thiểu 2 biểu đồ định lượng thật:**
    - Đọc dữ liệu chạy thật từ `results/benchmark_results.csv` / `results/benchmark_summary.csv` (từ `backends=real`) và/hoặc nhúng trực quan 2 biểu đồ [results/chart_dropout_recovery.png](./results/chart_dropout_recovery.png) và [results/chart_substitution_scaling.png](./results/chart_substitution_scaling.png).
- [ ] **Soạn hướng dẫn sử dụng `docs/user_guide.md`:**
  - Hướng dẫn cài đặt thư viện, lệnh khởi chạy `streamlit run app.py`, ý nghĩa từng tham số trên giao diện và các bước bấm 3 kịch bản demo.
- [ ] **Viết báo cáo Phần 4 (Giao diện & Benchmark) và chuẩn bị demo trực tiếp 3–5 phút.**

---

### 3. Linh + Trung — Bổ sung dữ liệu nhị phân & Rà soát học thuật

- [ ] **Bổ sung tệp mẫu nhị phân vào `data/samples/`:**
  - Thêm **1 tệp ảnh PNG nhỏ** và **1 tệp PDF nhỏ** vào `data/samples/` để nhóm có thể upload và mở lại tệp nhị phân trực tiếp trên giao diện Streamlit cho ca kiểm thử T02.
  - Kiểm tra thêm round-trip thực tế trên 2 tệp mẫu mới qua `run_simulation()`.
- [ ] **Đưa tài liệu đặc tả vào `docs/` (nếu lưu trong repo):**
  - Cập nhật `docs/noise_spec.md` (đặc tả tham số kênh nhiễu, công thức đo tỷ lệ tái tạo toàn tệp).
- [ ] **Rà soát đồng nhất diễn giải giới hạn ECC giữa báo cáo của Trung và Linh:**
  - Thống nhất cách giải thích:
    - Cơ chế `dropout_scope="packet"` (mặc định rút thăm theo từng bản sao `copy_id`) vs `"logical"` (mất đồng thời mọi bản sao).
    - Giới hạn của `XOR_PARITY` nhóm `4+1` (chỉ khôi phục tối đa 1 packet mất trong cùng 1 nhóm; mất ≥ 2 trong cùng nhóm → `FAIL_UNRECOVERABLE`).
    - Cơ chế CRC-32 phát hiện lỗi substitution và CRC-32 fallback giải quyết hòa phiếu 1–1 khi chỉ còn 2 bản đọc.
    - Giới hạn học thuật chung: không mô phỏng InDel, Reed–Solomon, DNA Fountain, GC-balance ép buộc, hay bảo vệ metadata bằng ECC riêng.

---

### 4. Cả nhóm — 2 ngày cuối *(Kiểm tra máy sạch, Ghép báo cáo & Diễn tập)*

- [ ] **Kiểm thử End-to-End trên máy sạch (Clean Machine Verification):**
  1. `git clone` từ repo chung (đúng tag/nhánh nộp bài).
  2. Tạo môi trường ảo mới và cài đặt `pip install -r requirements.txt`.
  3. Chạy `python -m unittest discover -s tests -v` *(xác nhận toàn bộ test PASS, không lỗi phụ thuộc)*.
  4. Chạy `python -m pytest -q` *(xác nhận tương thích pytest)*.
  5. Chạy `python -m dnastore.cli demo` *(xác nhận 3/3 kịch bản CLI dự phòng với `backends=real`)*.
  6. Chạy `streamlit run app.py` *(test upload TXT/PNG/PDF, test 3 nút preset demo, tải tệp khôi phục về máy và mở kiểm tra trực tiếp)*.
- [ ] **Ghép hoàn chỉnh Báo cáo cuối kỳ (Thái chủ trì ghép Phần 1–5):**
  - **Phần 1:** Tổng quan đề tài, câu hỏi nghiên cứu, phạm vi & giới hạn *(Thái)*.
  - **Phần 2:** Kiến trúc 9 bước, Storage Controller, Metadata & hợp đồng dữ liệu *(Thái)* + Mã hóa 2 bit/nt & thuật toán ECC *(Trung)*.
  - **Phần 3:** Thuật toán mã hóa & ECC chi tiết *(Trung)* + Kênh nhiễu & pipeline phục hồi *(Linh)*.
  - **Phần 4:** Phân tích kết quả thực nghiệm định lượng *(Linh)* + Giao diện Streamlit & trình bày benchmark *(Dũng)*.
  - **Phần 5:** Đóng góp, giới hạn học thuật & hướng mở rộng *(Trung + Linh + Thái)*.
  - *Yêu cầu bắt buộc:* Toàn bộ bảng số liệu và biểu đồ trong báo cáo phải dùng thống nhất **100% số liệu `backends = real`** từ `results/benchmark_summary.csv`, `results/test_cases.csv` và `results/experiment_conditions.json`.
- [ ] **Làm slide thuyết trình & Diễn tập Demo (3–5 phút):**
  - Phân công người trình bày từng phần, căn thời gian 3–5 phút, chuẩn bị phương án dự phòng bằng `python -m dnastore.cli demo` nếu gặp sự cố trình duyệt/mạng khi báo cáo.
