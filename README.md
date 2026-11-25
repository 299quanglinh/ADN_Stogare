# Hệ thống Mô phỏng Lưu trữ Dữ liệu bằng Phân tử ADN (`dna-storage`)

> **Trạng thái hiện tại:** Đã hoàn tất tích hợp và kiểm chứng **100% lõi mô phỏng (`backends = real`)** giữa **Thái + Trung + Linh** (`48/48` ca kiểm thử tự động PASS, `24/24` ca chuẩn T01–T08 PASS, `2.160` lượt benchmark định lượng thật). Hệ thống sẵn sàng cho **Dũng** ghép giao diện Streamlit (`app.py`) và hoàn thiện các bước cuối để chốt nộp bài (chi tiết xem [CONGVIECCANLAM.md](./CONGVIECCANLAM.md)).

---

## 1. Tổng quan dự án

- **Tên đề tài:** Nghiên cứu kiến trúc và mô hình hóa hệ thống lưu trữ dữ liệu bằng phân tử ADN *(trọng tâm: mô phỏng sai lệch và khả năng tái tạo chính xác dữ liệu)*.
- **Nhóm thực hiện (4 thành viên, khung thời gian 14 ngày D1–D14):** **Thái – Trung – Linh – Dũng**.
- **Câu hỏi nghiên cứu trọng tâm:**
  > *"Trong một mô hình lưu trữ ADN số, việc bổ sung dữ liệu dự phòng làm thay đổi khả năng tái tạo tệp như thế nào khi xảy ra lỗi mất đoạn (dropout) hoặc thay thế nucleotide (substitution)?"*

### Phạm vi triển khai & Giới hạn học thuật

| Đã triển khai trong phạm vi 14 ngày | Ngoài phạm vi 14 ngày *(chỉ nêu ở phần giới hạn / hướng mở rộng)* |
| :--- | :--- |
| - Đọc tệp nhỏ (`TXT`/`PNG`/`PDF`, dữ liệu byte) thành dãy byte.<br>- Chia khối cố định (`chunk_size = 32 B`), đệm `0x00` khối cuối.<br>- Mã hóa 2 bit/nucleotide sang `{A, T, G, C}` (từ chối tuyệt đối ký tự lạ như `'X'`, `'?'`).<br>- Quản lý packet/metadata và lưu kho ADN giả lập (bộ nhớ trong & JSON trên đĩa, ghi nguyên tử).<br>- Mô phỏng 2 cơ chế lỗi **dropout** và **substitution** với `random.Random(seed)` cục bộ (kèm `force_drop` xác định).<br>- Phục hồi bằng đồng thuận đa số (*majority vote consensus*), kiểm tra **CRC-32** (kèm **CRC-32 fallback** giải quyết hòa phiếu 1–1), đánh dấu erasure và **XOR parity** theo nhóm (`4+1`).<br>- Xác minh toàn vẹn độc lập bằng đối chiếu byte và **SHA-256**.<br>- Chạy thực nghiệm định lượng xuất CSV/đồ thị và giao diện CLI/Streamlit demo. | - Tổng hợp và giải trình tự ADN vật lý thật.<br>- Mã Reed–Solomon hoặc DNA Fountain hoàn chỉnh.<br>- Lỗi chèn/xóa nucleotide (*Insertion/Deletion – InDel*).<br>- Primer PCR thật.<br>- Cơ chế Cache/LRU.<br>- Ép cân bằng GC-content 45–55% hoặc triệt tiêu homopolymer (chỉ tính chỉ số GC quan sát qua `compute_gc_content`).<br>- Bảo vệ metadata/header bằng mã sửa lỗi riêng. |

---

## 2. Kiến trúc 9 bước & Đường đi của dữ liệu gốc

Toàn bộ luồng thực thi do `dnastore.orchestrator.run_simulation()` điều phối nhằm bảo đảm **tách bạch tuyệt đối giữa dữ liệu gốc và tầng phục hồi** (`PASS_HASH_TO_RECOVERY = False`):

```text
[1. Đọc tệp gốc] ──► [2. Mã hóa & ECC] ──► [3. Lưu kho (V01–V10)] ──► [4. Đọc kho (deepcopy)]
   (orchestrator)     (dna_encoder +          (StorageController)       (StorageController)
   Tính SHA-256 gốc    ecc_codec)                                               │
                                                                                ▼
[9. Chuẩn hóa 21 trường] ◄── [8. Quyết định] ◄── [7. Đối chiếu cuối] ◄── [5. Kênh nhiễu]
   (orchestrator)             (orchestrator)      (byte + SHA-256)        (noise_simulator)
                                                         ▲                      │
                                                         │                      ▼
                                                  [6. Phục hồi] ◄─────── (reads + recovery_view,
                                               (recovery_pipeline          giữ nguyên crc32 cũ,
                                                → ecc_codec)               ẩn expected_sha256)
```

1. **Đọc tệp gốc (`orchestrator`):** Nạp `bytes` (hỗ trợ `bytes`, đường dẫn tệp, hoặc tuple `(filename, bytes)`) và tự tính mã băm SHA-256 gốc một lần duy nhất.
2. **Mã hóa & sinh dự phòng (`dna_encoder` + `ecc_codec`):** Chia chunk `32 byte`, đệm `0x00` ở khối cuối, sinh gói `PARITY` / bản sao `REPLICATION` trước khi lưu kho, rồi chuyển sang chuỗi `A/T/G/C` kèm `crc32` và `metadata`.
3. **Lưu kho (`StorageController`):** Kiểm tra toàn bộ quy tắc hợp lệ V01–V10 (bằng `DNAPacket.validate()`, `validate_packet_extra_fields()`, `validate_metadata()`), bảo toàn các trường mở rộng (`crc32`, `covered_packet_ids`), và lưu nguyên tử (*atomic write*) theo `file_id` tuần tự (`F01`, `F02`, ...).
4. **Đọc kho (`StorageController`):** Trả về bản sao sâu (`copy.deepcopy`) để kênh nhiễu tuyệt đối không làm hỏng dữ liệu trong kho.
5. **Kênh nhiễu (`noise_simulator`):** Áp dụng dropout và substitution theo cấu hình và `seed` cố định, **giữ nguyên mã `crc32` cũ** để tầng phục hồi tự phát hiện sai lệch.
6. **Phục hồi (`recovery_pipeline` → `ecc_codec`):** Chỉ nhận `reads` sau nhiễu và bản `recovery_view(metadata)` đã xóa `expected_sha256`; thực hiện gom nhóm theo `packet_id`, majority vote consensus, kiểm tra CRC-32 / CRC-32 fallback, đánh dấu erasure, giải XOR parity theo nhóm và ghép bytes.
7. **Đối chiếu cuối (`orchestrator`):** Nơi duy nhất so sánh `bytes` khôi phục với tệp gốc và đối chiếu SHA-256.
8. **Quyết định trạng thái (`orchestrator`):** Chỉ gán `success=True` khi trùng cả byte lẫn SHA-256; mọi ca vượt khả năng sửa hoặc sai hash đều trả `success=False`, `recovered_bytes=None`.
9. **Chuẩn hóa đầu ra (`orchestrator`):** Đóng gói `dict` theo schema chuẩn 21 trường kèm thời gian thực thi `elapsed_ms` và nhãn `backends` (`real` hoặc `mock`).

---

## 3. Phân công & Tiến độ hiện tại

| Thành viên | Vai trò chính | Tiến độ | Trạng thái chi tiết hiện tại |
| :--- | :--- | :---: | :--- |
| **Trung** | Mã hóa/Giải mã ADN & ECC | **100%** *(lõi)* | Hoàn thiện `dna_encoder.py`, `dna_decoder.py`, `ecc_codec.py`, bộ test `test_codec.py`; hỗ trợ `ecc_params` (OI-03/OI-04) và `expected_sha256` tùy chọn cho `recovery_view` (OI-10). |
| **Linh** | Kênh nhiễu, Recovery Pipeline & Thực nghiệm | **100%** *(lõi & benchmark)* | Hoàn thiện `noise_simulator.py`, `recovery_pipeline.py`, bộ test `test_noise_simulator.py` và `test_recovery.py` (T01–T08), thực thi `benchmark.py` (2.160 lượt chạy thật) và sinh toàn bộ CSV/biểu đồ trong `results/`. |
| **Thái** | Kiến trúc, Storage Controller & Tích hợp | **~95%** | Hoàn thiện khung `dnastore/` (`models.py`, `errors.py`, `metadata_manager.py`, `storage_controller.py`, `backends.py`, `mocks.py`, `orchestrator.py`, `cli.py`), kiểm thử `test_storage.py` và `test_orchestrator.py`, hợp nhất gói `dna-storage/`. Còn đưa lên Git chung, chốt tag `api-v1.0` và ghép báo cáo cuối kỳ. |
| **Dũng** | Giao diện Streamlit, Trình bày Benchmark & Demo | **Chờ triển khai** | Chưa có `app.py` và `docs/user_guide.md` trong gói hiện tại. Toàn bộ hàm backend `run_simulation()` cùng dữ liệu/biểu đồ thật trong `results/` đã sẵn sàng để nối trực tiếp. |

### 7 sai lệch kiến trúc đã xử lý triệt để khi hợp nhất gói `dna-storage/`

1. Sửa `StorageController` bảo toàn nguyên vẹn các trường mở rộng `crc32` và `covered_packet_ids` từ encoder của Trung khi lưu/đọc (cả bộ nhớ trong và JSON trên đĩa).
2. Sửa `ecc_codec.py` hoạt động bình thường khi `orchestrator` ẩn `expected_sha256` qua `recovery_view(metadata)` (`PASS_HASH_TO_RECOVERY = False`, OI-10).
3. Xây dựng `recovery_pipeline.decode_or_recover()` làm adapter trả `bytes` hoặc ném `RecoveryFailure`/`ValidationError` đúng hợp đồng `orchestrator` (OI-09).
4. Bổ sung hỗ trợ `ecc_params` trong `dna_encoder.py` và truyền `filename` từ `orchestrator` (OI-03, OI-04).
5. Bổ sung `force_drop` vào `noise_simulator.py` để chạy xác định T03–T05 và 3 kịch bản demo CLI (OI-11).
6. Xuất song song khóa thống kê của Thái (`n_packets_in`, `n_dropped_packets`, `n_substituted_bases`, `n_reads`) và khóa chi tiết của Linh trong `noise_simulator.py` để gắn đúng nhãn `OK_RECOVERED` (OI-08).
7. Đặt mặc định `dropout_scope="packet"` (rút thăm dropout độc lập cho từng bản sao `copy_id` lưu kho) để `REPLICATION_3X` và `HYBRID` phát huy tác dụng chống dropout, đồng thời chuẩn hóa lại bộ T01–T08.

---

## 4. Cấu trúc thư mục hiện tại

Dưới đây là cấu trúc **thực tế hiện có** trên đĩa trong `dna-storage/` (các tệp chưa triển khai như `app.py` và `docs/` được theo dõi trong [CONGVIECCANLAM.md](./CONGVIECCANLAM.md)):

```text
dna-storage/
├── README.md                         # Tài liệu tổng quan dự án & API hiện hành
├── CONGVIECCANLAM.md                 # Danh sách công việc tiếp theo cần chốt để nộp bài
├── requirements.txt                  # Phụ thuộc tối thiểu (lõi chạy stdlib Python 3.10+; tùy chọn streamlit/matplotlib/pandas/pytest)
├── .gitignore
├── benchmark.py                      # Chạy thực nghiệm 2.160 lượt qua run_simulation() (backends=real)
├── dnastore/                         # Gói lõi dùng chung (100% thư viện chuẩn Python)
│   ├── __init__.py                   # Export các API công khai của gói
│   ├── errors.py                     # [Thái] Ngoại lệ chuẩn gắn mã Reason
│   ├── models.py                     # [Thái] DNAPacket, RunConfig, Reason, check_result_schema
│   ├── metadata_manager.py           # [Thái] Validate metadata, lưu nguyên tử, recovery_view ẩn hash
│   ├── storage_controller.py         # [Thái] Lưu/đọc bộ nhớ & JSON trên đĩa, chống path traversal, giữ crc32
│   ├── backends.py                   # [Thái] Nạp 100% module thật (hỗ trợ DNASTORE_USE_MOCK=1 để đối chiếu)
│   ├── mocks.py                      # [Thái] Mock dự phòng đối chiếu
│   ├── orchestrator.py               # [Thái] Hàm lõi run_simulation() điều phối 9 bước
│   ├── cli.py                        # [Thái] Demo dòng lệnh 3 kịch bản dự phòng & chạy từng tệp
│   ├── dna_encoder.py                # [Trung] Mã hóa 2 bit/nt, chunking, padding 0x00, CRC-32, ecc_params
│   ├── dna_decoder.py                # [Trung] Giải mã & từ chối ký tự lạ ngoài A/T/G/C
│   ├── ecc_codec.py                  # [Trung] NONE / XOR_PARITY / REPLICATION_3X / HYBRID + CRC fallback
│   ├── noise_simulator.py            # [Linh] Kênh nhiễu có seed, force_drop, giữ nguyên crc32 cũ
│   └── recovery_pipeline.py          # [Linh] Adapter nối ecc_codec với orchestrator (OI-09/OI-10)
├── data/samples/                     # 3 tệp TXT tiếng Việt UTF-8 tự tạo
│   ├── sample_short.txt              # 166 bytes (6 DATA chunks @ 32 B, 2 nhóm XOR)
│   ├── sample_medium.txt             # 800 bytes (25 DATA chunks @ 32 B, không dư padding, 7 nhóm XOR)
│   └── sample_long.txt               # 1.955 bytes (62 DATA chunks @ 32 B, 16 nhóm XOR)
├── tests/                            # 48 ca kiểm thử tự động (48/48 PASS)
│   ├── test_storage.py               # [Thái] 11 test kho lưu trữ, metadata & hồi quy crc32
│   ├── test_orchestrator.py          # [Thái] 19 test toàn luồng (cả mock & real) & chống gian lận
│   ├── test_codec.py                 # [Trung] 9 test ánh xạ 2 bit, XOR, CRC fallback, OI-10
│   ├── test_noise_simulator.py       # [Linh] 8 test kênh nhiễu, seed, force_drop, bất biến
│   └── test_recovery.py              # [Linh] 1 test tích hợp chạy đủ 24 lượt T01–T08 trên 3 TXT -> test_cases.csv
└── results/                          # Kết quả chạy thật (backends = real)
    ├── test_cases.csv                # 24 lượt T01–T08 (24/24 PASS)
    ├── benchmark_results.csv         # 2.160 lượt chạy qua run_simulation()
    ├── benchmark_summary.csv         # Bảng tổng hợp tỷ lệ tái tạo, overhead & thời gian
    ├── experiment_conditions.json    # Điều kiện chạy, phiên bản Python & SHA-256 tệp mẫu
    ├── chart_dropout_recovery.png    # Biểu đồ tỷ lệ tái tạo theo Dropout (thuần & hỗn hợp)
    └── chart_substitution_scaling.png# Biểu đồ chống Substitution & ảnh hưởng kích thước tệp TXT
```

---

## 5. Thông số kỹ thuật & Hợp đồng dữ liệu (v1.0)

### 5.1. Mã hóa, cấu trúc Packet, Metadata & Chế độ ECC

| Nhóm thông số | Giá trị / Quy ước | Chi tiết cài đặt trong mã nguồn |
| :--- | :--- | :--- |
| **Ánh xạ nhị phân ↔ ADN** | `00→A`, `01→T`, `10→G`, `11→C` | Mật độ 2,0 bit/nt (1 byte = 4 nt); từ chối mọi ký tự ngoài `{A, T, G, C}` (gồm `'X'`, `'?'`). |
| **Kích thước khối (`chunk_size`)** | `32` bytes (`128` nt/packet) | Khối cuối ngắn hơn `32 B` được đệm `0x00`; lưu độ dài thực trong `payload_len` và cắt đệm theo `file_size`. |
| **8 trường lõi Packet (`dict`)** | `file_id`, `packet_id`, `total_packets`, `kind`, `group_id`, `dna_sequence`, `payload_len`, `copy_id` | `total_packets` = số DATA packet logic (`0..n-1`); `PARITY` đánh số `n + group_id`; khóa duy nhất `(kind, packet_id, copy_id)`. |
| **Trường mở rộng Packet** | `crc32` (8 hex), `covered_packet_ids` (`list[int]`) | Sinh tại `dna_encoder` / `ecc_codec`; `StorageController` kiểm định và bảo toàn nguyên vẹn khi lưu/đọc. |
| **Metadata chuẩn** | 7 trường bắt buộc + 4 trường mở rộng | Bắt buộc (`METADATA_REQUIRED`): `file_id`, `filename`, `file_size`, `chunk_size`, `total_packets`, `expected_sha256` (64 hex thường), `ecc_mode`. Mở rộng: `total_stored_packets`, `group_size`, `replication_factor`, `ecc_params`. |
| **4 chế độ ECC** | `NONE`, `XOR_PARITY`, `REPLICATION_3X`, `HYBRID` | Mặc định `group_size = 4` (`4 DATA + 1 PARITY`); `REPLICATION_3X` & `HYBRID` tạo 3 bản sao (`copies = 3`, `ecc_codec` tự ép tối thiểu 3 bản sao nếu `replication_factor <= 1`). |

### 5.2. Tham số cấu hình `RunConfig` & Kênh nhiễu

| Tham số trong `RunConfig` | Kiểu & Miền giá trị | Mặc định | Ý nghĩa & Lưu ý cho UI (`app.py`) |
| :--- | :--- | :---: | :--- |
| `chunk_size` | `int >= 1` | `32` | Kích thước khối dữ liệu (bytes). |
| `ecc_mode` | `str` | `"XOR_PARITY"` | Một trong `NONE`, `XOR_PARITY`, `REPLICATION_3X`, `HYBRID`. |
| `group_size` | `int >= 1` | `4` | Số DATA packet mỗi nhóm XOR parity. |
| `copies` | `int >= 1` | `1` | Số bản sao; nên truyền rõ `3` khi chọn `REPLICATION_3X` hoặc `HYBRID`. |
| `dropout_rate` | `float` trong `[0.0, 1.0]` | `0.0` | Xác suất mất từng packet lưu kho. UI nên dùng slider `0%–30%` rồi chia `100`. |
| `substitution_rate` | `float` trong `[0.0, 1.0]` | `0.0` | Xác suất đổi mỗi base sang 1 trong 3 base còn lại. UI nên dùng slider `0.0%–2.0%`, bước `0.1%`, rồi chia `100`. |
| `read_count` | `int >= 1` | `1` | Số bản đọc sinh ra từ mỗi packet sống sót. UI gợi ý `1–5`. |
| `force_drop` | `list` | `[]` | Ép mất chính xác packet, ví dụ `[["DATA", 1]]` hoặc `[["DATA", 0], ["DATA", 1]]` cho các nút preset Demo. |
| `seed` *(tham số riêng của `run_simulation`)* | `int` | `0` *(UI/demo gợi ý `42`)* | Khởi tạo `random.Random(seed)` cục bộ trong `noise_simulator` để tái lập 100% mẫu nhiễu. |

> **Lưu ý tích hợp:** `RunConfig` hiện kiểm tra chặt danh sách khóa hợp lệ gồm 8 trường nêu trên (không nhận `dropout_scope`). Khi đi qua `run_simulation()`, `noise_simulator.apply_noise()` luôn dùng giá trị mặc định `dropout_scope="packet"` (rút thăm dropout độc lập theo từng bản sao `copy_id`). Tùy chọn `dropout_scope="logical"` khả dụng khi gọi trực tiếp `apply_noise()`.

### 5.3. Hợp đồng API & Schema kết quả chuẩn hóa

- **Đường dẫn import chính thức (`dnastore/backends.py`, OI-16):**
  - `dnastore.dna_encoder:encode_file`
  - `dnastore.storage_controller:StorageController.store_packets` & `.read_packets`
  - `dnastore.noise_simulator:apply_noise`
  - `dnastore.recovery_pipeline:decode_or_recover` *(trả `bytes` hoặc ném `RecoveryFailure` / `ValidationError`)*
  - `dnastore.orchestrator:run_simulation` *(nhận `bytes`, đường dẫn tệp, hoặc `(filename, bytes)`; không bao giờ ném exception ra UI)*
- **Schema kết quả `run_simulation()` (21 trường):**
  - **10 trường lõi:** `success`, `reason`, `recovered_bytes`, `original_size`, `recovered_size`, `sha256_match`, `dropout_rate`, `substitution_rate`, `seed`, `elapsed_ms`.
  - **11 trường mở rộng:** `file_id`, `filename`, `file_type`, `ecc_mode`, `chunk_size`, `n_packets`, `n_packets_lost`, `n_substituted_bases`, `n_nucleotides`, `reason_detail`, `backends`.
- **9 mã `Reason` chuẩn (`dnastore/models.py`):**
  `OK_CLEAN`, `OK_RECOVERED`, `FAIL_UNRECOVERABLE`, `FAIL_HASH_MISMATCH`, `FAIL_INVALID_INPUT`, `FAIL_ENCODER_ERROR`, `FAIL_STORAGE_ERROR`, `FAIL_NOISE_ERROR`, `FAIL_INTERNAL_ERROR`.

---

## 6. Kết quả kiểm chứng & Thực nghiệm (`backends = real`)

### 6.1. Kiểm thử tự động & CLI Demo

- **Unit & Integration Tests:** `48/48` test PASS (`python -m unittest discover -s tests -v`, xác minh đạt 100% trên gói hiện tại).
- **Bộ ca chuẩn T01–T08 trên 3 tệp TXT (`results/test_cases.csv`):** `24/24` PASS (`8` kịch bản × `3` tệp mẫu).
- **CLI Demo (`python -m dnastore.cli demo`):** `3/3` ca trên `sample_medium.txt` (800 B, `XOR_PARITY`):
  1. Không lỗi → `OK_CLEAN` (`sha256_match=True`, `lost=0`)
  2. Mất 1 DATA packet (`force_drop=[["DATA", 1]]`) → `OK_RECOVERED` (`sha256_match=True`, `lost=1`)
  3. Mất 2 DATA packet cùng nhóm (`force_drop=[["DATA", 0], ["DATA", 1]]`) → `FAIL_UNRECOVERABLE` (`sha256_match=False`, `lost=2`)

### 6.2. Số liệu benchmark chính thức (`2.160` lượt qua `run_simulation()`, 30 seeds/mức)

Tổng hợp từ [results/benchmark_summary.csv](./results/benchmark_summary.csv) trên tệp `sample_medium.txt` (800 B, `chunk_size=32`, `group_size=4`, `copies=3` với `REPLICATION_3X`/`HYBRID`):

| Chế độ ECC | Overhead | A. Chỉ Dropout (0 / 5 / 10 / 15 / 20%) | B. Drop + Sub 0,1% (0 / 5 / 10 / 15 / 20%) | C. Quét Sub (0 / 0,1 / 0,5 / 1 / 2%) | T/g TB KB B *(TB A–C)* |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `NONE` | +0,0% | 100% / 30,0% / 6,67% / 0% / 0% | 6,67% / 0% / 0% / 0% / 0% | 100% / 0% / 0% / 0% / 0% | 7,03 ms *(6,91 ms)* |
| `XOR_PARITY` | +28,0% | 100% / 83,33% / 70,0% / 33,33% / 13,33% | 56,67% / 20,0% / 20,0% / 10,0% / 0% | 100% / 36,67% / 0% / 0% / 0% | 10,00 ms *(10,03 ms)* |
| `REPLICATION_3X` | +200,0% | 100% / 100% / 100% / 90,0% / 80,0% | 100% / 90,0% / 76,67% / 70,0% / 60,0% | 100% / 100% / 100% / 43,33% / 13,33% | 31,64 ms *(32,14 ms)* |
| `HYBRID` | +284,0% | 100% / 100% / 100% / 100% / 100% | 100% / 100% / 100% / 100% / 96,67% | 100% / 100% / 100% / 96,67% / 53,33% | 41,41 ms *(45,25 ms)* |

- **Kịch bản D (Ảnh hưởng kích thước tệp TXT tại 5% dropout + 0,1% substitution):**
  Khi tăng kích thước từ `sample_short.txt` (166 B) → `sample_medium.txt` (800 B) → `sample_long.txt` (1.955 B):
  - `NONE`: **36,67% → 0% → 0%**
  - `XOR_PARITY`: **80,0% → 40,0% → 10,0%**
  - `REPLICATION_3X`: **96,67% → 83,33% → 76,67%**
  - `HYBRID`: **100% → 100% → 100%** *(overhead 362,65% → 284,0% → 283,02%; thời gian TB 10,51 ms → 45,89 ms → 109,95 ms)*.

- **Biểu đồ kết quả đã xuất:**
  - [results/chart_dropout_recovery.png](./results/chart_dropout_recovery.png)
  - [results/chart_substitution_scaling.png](./results/chart_substitution_scaling.png)

---

## 7. Hướng dẫn chạy nhanh & Tích hợp giao diện Streamlit (`app.py`)

### 7.1. Lệnh chạy kiểm thử, CLI & Benchmark

```bash
# Chạy từ thư mục gốc dự án (dna-storage/ hoặc ADN_Stogare/ sau khi git clone)

# 1. Chạy toàn bộ 48 ca kiểm thử tự động (chỉ cần thư viện chuẩn Python 3.10+)
python -m unittest discover -s tests -v

# 2. Chạy 3 kịch bản demo dự phòng trên 100% module thật (OK_CLEAN / OK_RECOVERED / FAIL_UNRECOVERABLE)
python -m dnastore.cli demo

# 3. Chạy mô phỏng một tệp tùy chọn
python -m dnastore.cli run data/samples/sample_medium.txt --ecc XOR_PARITY --dropout 0.05 --subst 0.001 --seed 42

# 4. Xuất lại bảng 24 ca T01-T08 ra results/test_cases.csv
python -m tests.test_recovery

# 5. Chạy lại toàn bộ 2.160 lượt benchmark & vẽ lại 2 biểu đồ PNG (cần matplotlib)
python benchmark.py --trials 30
```

### 7.2. Mẫu gọi API từ giao diện Streamlit của Dũng (`app.py`)

```python
from dnastore import run_simulation

ecc_mode = "HYBRID"  # NONE | XOR_PARITY | REPLICATION_3X | HYBRID
result = run_simulation(
    (uploaded_file.name, uploaded_file.getvalue()),
    config={
        "chunk_size": 32,
        "ecc_mode": ecc_mode,
        "group_size": 4,
        "copies": 3 if ecc_mode in ("REPLICATION_3X", "HYBRID") else 1,
        "dropout_rate": dropout_pct / 100.0,           # UI 0..30 (%) -> API 0.0..0.30
        "substitution_rate": substitution_pct / 100.0, # UI 0.0..2.0 (%) -> API 0.0..0.02
        "read_count": int(read_count),                 # 1..5
        # Dùng thêm "force_drop": [["DATA", 1]] cho các nút preset Demo
    },
    seed=int(seed),
)

# Hiển thị trạng thái & cho phép tải tệp khôi phục:
if result["success"] and result["recovered_bytes"] is not None:
    # st.download_button(..., data=result["recovered_bytes"], file_name=f"recovered_{result['filename']}")
    pass
```
