# Hợp đồng API & Dữ liệu Dùng chung (`api-v1.0`)

- **Phiên bản đóng băng:** `api-v1.0`
- **Chủ trì kiến trúc & tích hợp:** Thái *(đồng bộ với Trung – Linh; bàn giao cho Dũng dựng `app.py`)*
- **Phạm vi:** Mô tả chính xác hợp đồng dữ liệu, chữ ký 6 hàm API chính thức, schema đầu ra 21 trường, mã trạng thái `Reason` và quy ước làm việc Git/môi trường (`OI-17`, `OI-19`).

---

## 1. Quy ước Môi trường & Git (OI-17, OI-19)

### 1.1. Môi trường & Phụ thuộc (OI-17)
- **Python yêu cầu:** `Python 3.10+` *(lõi `dnastore/` và toàn bộ 48 unit/integration tests sử dụng 100% thư viện chuẩn Python)*.
- **Phụ thuộc tùy chọn chuẩn hóa trong `requirements.txt`:**
  - `matplotlib>=3.7` *(vẽ biểu đồ trong `benchmark.py`)*
  - `pytest>=7.4` *(chạy kiểm thử bằng `pytest` song song với `unittest`)*
  - `streamlit>=1.32` *(giao diện web `app.py`)*
  - `pandas>=2.0` *(đọc và xử lý bảng CSV trong `app.py`)*
- **Quy tắc cho UI (`app.py`):** Ưu tiên sử dụng đúng các thư viện đã chốt trong `requirements.txt`. Chỉ mở đề xuất cập nhật `requirements.txt` nếu phát sinh thư viện bắt buộc mới. Không dùng `pip freeze` từ môi trường cá nhân.

### 1.2. Quy ước Nhánh & Tag phát hành (OI-19)
- Nhánh `main` là nhánh ổn định, luôn bảo đảm `48/48` test PASS.
- Mốc **`api-v1.0`** là Git tag đóng băng toàn bộ hợp đồng dữ liệu và chữ ký API trong gói `dnastore/`.
- **Quy ước phát triển tiếp cho Dũng:**
  - Tạo nhánh riêng từ `main` hoặc từ tag `api-v1.0` (gợi ý: `feat/streamlit-ui`).
  - Không chỉnh sửa chữ ký hàm, tên trường packet/metadata hay logic lõi trong `dnastore/` trên nhánh UI; chỉ gọi qua API công khai (`dnastore.run_simulation`, `dnastore.encode_file`).

---

## 2. Đường dẫn Import chính thức (OI-16)

Theo `dnastore/backends.py` và `dnastore/__init__.py`:

| Vai trò | Đường dẫn import chính thức | Thành viên phụ trách |
| :--- | :--- | :--- |
| Mã hóa & đóng gói packet | `dnastore.dna_encoder:encode_file` | Trung |
| Kho lưu trữ ADN giả lập | `dnastore.storage_controller:StorageController` | Thái |
| Mô phỏng kênh nhiễu | `dnastore.noise_simulator:apply_noise` | Linh |
| Pipeline khôi phục (adapter) | `dnastore.recovery_pipeline:decode_or_recover` | Linh + Trung |
| Bộ điều phối toàn luồng | `dnastore.orchestrator:run_simulation` | Thái |

> **Import ngắn gọn cho UI (`app.py`):**
> ```python
> from dnastore import run_simulation, encode_file, Reason
> ```

---

## 3. Hợp đồng Cấu trúc Dữ liệu

### 3.1. Quy tắc ánh xạ nhị phân ↔ ADN
- Bảng ánh xạ: `00 → A`, `01 → T`, `10 → G`, `11 → C` (`dnastore.models.ALPHABET = "ATGC"`).
- Mật độ cơ sở: `2,0 bit/nucleotide` (`1 byte = 4 nucleotide`).
- Từ chối tuyệt đối mọi ký tự ngoài `{A, T, G, C}` (bao gồm `'X'`, `'?'`, số, khoảng trắng).

### 3.2. Cấu trúc Packet (`dict` — OI-01)
Dạng trao đổi chính thức giữa các module là `dict`, được kiểm định bằng `DNAPacket.from_dict(d).validate()` và `validate_packet_extra_fields(d)`:

| Nhóm | Tên trường | Kiểu | Quy ước / Ràng buộc |
| :--- | :--- | :---: | :--- |
| Lõi | `file_id` | `str` | Chuỗi không rỗng khớp `^[A-Za-z0-9_-]{1,64}$` (vd `"F01"`). |
| Lõi | `packet_id` | `int` | `>= 0`. Với `kind="DATA"`: `0 .. total_packets - 1`. Với `kind="PARITY"`: `total_packets + group_id`. |
| Lõi | `total_packets` | `int` | `>= 1`. Tổng số `DATA` packet logic của tệp gốc. |
| Lõi | `kind` | `str` | `"DATA"` hoặc `"PARITY"`. |
| Lõi | `group_id` | `int` | `>= 0`. Chỉ số nhóm XOR (`packet_id // group_size` cho DATA). |
| Lõi | `dna_sequence` | `str` | Chuỗi không rỗng chỉ chứa `A/T/G/C`, độ dài `>= payload_len * 4` (mặc định `128 nt` khi `chunk_size=32`). |
| Lõi | `payload_len` | `int` | `>= 0` và `payload_len * 4 <= len(dna_sequence)`. Độ dài byte thực trước khi đệm `0x00`. |
| Lõi | `copy_id` | `int` | `>= 0` (mặc định `0`). Khóa duy nhất của một packet lưu kho là `(kind, packet_id, copy_id)`. |
| Mở rộng | `crc32` | `str` *(tùy chọn)* | Chuỗi đúng 8 ký tự hex (`^[0-9a-fA-F]{8}$`) tính trên chunk đã đệm trước nhiễu; **giữ nguyên qua kênh nhiễu**. |
| Mở rộng | `covered_packet_ids` | `list[int]` *(tùy chọn)* | Danh sách các `packet_id` DATA thuộc nhóm mà packet `PARITY` bảo vệ. |

### 3.3. Cấu trúc Metadata & `recovery_view` (OI-10)
- **7 trường bắt buộc (`METADATA_REQUIRED`):**
  - `file_id` (`str`, không rỗng)
  - `filename` (`str`, không rỗng)
  - `file_size` (`int >= 1`, kích thước gốc theo byte)
  - `chunk_size` (`int >= 1`, mặc định `32`)
  - `total_packets` (`int >= 1`, số `DATA` packet logic)
  - `expected_sha256` (`str`, đúng 64 ký tự hex thường `^[0-9a-f]{64}$`)
  - `ecc_mode` (`str`: `"NONE"`, `"XOR_PARITY"`, `"REPLICATION_3X"`, `"HYBRID"` — OI-05)
- **Trường mở rộng từ `encode_file`:** `total_stored_packets`, `group_size`, `replication_factor`, `ecc_params` (`{"group_size": ..., "copies": ...}`).
- **Cách ly bảo mật (`recovery_view` — OI-10):** `orchestrator` đặt `PASS_HASH_TO_RECOVERY = False` và gọi `metadata_manager.recovery_view(md)` để **xóa bỏ `expected_sha256`** trước khi truyền vào `decode_or_recover(reads, metadata)`.

### 3.4. Cấu hình chạy `RunConfig` (`dnastore/models.py`)
`RunConfig.from_dict(config)` kiểm tra chặt danh sách khóa hợp lệ gồm đúng **8 trường**:

| Tham số | Kiểu | Miền giá trị | Mặc định | Ghi chú |
| :--- | :---: | :---: | :---: | :--- |
| `chunk_size` | `int` | `>= 1` | `32` | Kích thước mỗi khối dữ liệu (bytes). |
| `ecc_mode` | `str` | `NONE` \| `XOR_PARITY` \| `REPLICATION_3X` \| `HYBRID` | `"XOR_PARITY"` | Tự động chuẩn hóa chữ hoa (OI-05). |
| `group_size` | `int` | `>= 1` | `4` | Số DATA packet trong một nhóm XOR parity. |
| `copies` | `int` | `>= 1` | `1` | Nên truyền `3` khi dùng `REPLICATION_3X` hoặc `HYBRID`. |
| `dropout_rate` | `float` | `[0.0, 1.0]` | `0.0` | Xác suất mất từng packet lưu kho (`copy_id` độc lập). |
| `substitution_rate` | `float` | `[0.0, 1.0]` | `0.0` | Xác suất mỗi base trong mỗi read đổi sang 1 trong 3 base còn lại. |
| `read_count` | `int` | `>= 1` | `1` | Số bản đọc sinh ra cho mỗi packet sống sót. |
| `force_drop` | `list` | `[[kind, packet_id], ...]` | `[]` | Ép mất chính xác packet (hỗ trợ thêm `[kind, pid, copy_id]` — OI-11). |

> **Lưu ý quan trọng cho UI:** Không truyền khóa lạ (như `dropout_scope`) vào `config` của `run_simulation()`, vì `RunConfig.from_dict()` sẽ ném `ValidationError` → trả `FAIL_INVALID_INPUT`. Khi chạy qua `run_simulation()`, kênh nhiễu mặc định dùng `dropout_scope="packet"`.

---

## 4. Hợp đồng 6 Hàm API chính thức

### 4.1. `encode_file` (`dnastore.dna_encoder`) — OI-03, OI-04
```python
encode_file(
    data: bytes,
    file_id: str,
    chunk_size: int = 32,
    filename: str = "unknown.bin",
    ecc_mode: str = "NONE",
    group_size: int = 4,
    replication_factor: int = 1,
    ecc_params: dict | None = None,
) -> tuple[list[dict], dict]
```
- Trả về `(packets, metadata)`. Hỗ trợ đồng thời tham số rời (`group_size`, `replication_factor`) và `ecc_params={"group_size": ..., "copies": ...}`.

### 4.2 & 4.3. `StorageController` (`dnastore.storage_controller`)
```python
store = StorageController(root: str | Path | None = None)
file_id = store.new_file_id()  # Cấp "F01", "F02", ... tuần tự
summary = store.store_packets(file_id, packets, metadata, overwrite: bool = False)
packets_copy = store.read_packets(file_id, kind: str | None = None)
metadata_copy = store.read_metadata(file_id)
```
- `root=None`: kho bộ nhớ trong (mặc định của `run_simulation()` và `benchmark.py` — OI-18).
- `root=<dir>`: lưu nguyên tử ra đĩa (`packets.json` + `metadata.json` via file tạm + `os.replace`).
- Kiểm tra toàn bộ hợp lệ packet/metadata (V01–V10), chống path traversal `file_id`, giữ nguyên `crc32` và `covered_packet_ids`, trả `copy.deepcopy(...)` khi đọc.

### 4.4. `apply_noise` (`dnastore.noise_simulator`) — OI-08, OI-11
```python
apply_noise(
    packets: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    seed: int,
) -> tuple[list[dict], dict]
```
- Dùng `random.Random(seed)` cục bộ (không đụng RNG toàn cục), không mutate `packets` đầu vào, **không tính lại `crc32`**.
- `stats` trả về đầy đủ cả khóa chuẩn (`n_packets_in`, `n_dropped_packets`, `n_substituted_bases`, `n_reads` — OI-08) và khóa thống kê chi tiết (`logical_packets_*`, `source_packets_*`, `bases_processed`, `bases_substituted`, `observed_*`).

### 4.5. `decode_or_recover` (`dnastore.recovery_pipeline`) — OI-09, OI-10
```python
decode_or_recover(reads: list[dict], metadata: dict) -> bytes
```
- Chỉ nhận `reads` sau nhiễu và `metadata` (đã xóa `expected_sha256` qua `recovery_view()`).
- **Thành công:** trả về `bytes` khôi phục.
- **Thất bại:** ném `ValidationError` (metadata sai) hoặc `RecoveryFailure` (vượt khả năng sửa lỗi / mất quá ngưỡng).

### 4.6. `run_simulation` (`dnastore.orchestrator`) — OI-15 *(Entry point chính cho UI & Benchmark)*
```python
run_simulation(
    file: bytes | str | Path | tuple[str, bytes],
    config: dict | None = None,
    seed: int = 0,
    *,
    filename: str | None = None,
    storage: StorageController | None = None,
    backends: Backends | None = None,
) -> dict[str, Any]
```
- **Cam kết cho UI:** **Không bao giờ ném exception ra ngoài**; mọi lỗi đầu vào, mã hóa, kho, nhiễu hoặc phục hồi đều được bắt và chuẩn hóa vào dict trả về theo schema 21 trường.
- Chỉ trả `success=True` và `recovered_bytes=<bytes>` khi `out == data` **và** `sha256(out) == original_hash`. Mọi trường hợp còn lại đều trả `success=False` và `recovered_bytes=None`.

---

## 5. Schema Kết quả 21 Trường & 9 Mã `Reason`

### 5.1. Schema trả về của `run_simulation()` (kiểm định bởi `check_result_schema`)

| Nhóm | Trường | Kiểu | Ý nghĩa |
| :--- | :--- | :---: | :--- |
| Lõi (10) | `success` | `bool` | `True` chỉ khi khôi phục khớp 100% byte và SHA-256. |
| Lõi | `reason` | `str` | Một trong 9 mã chuẩn của `Reason` (OI-14). |
| Lõi | `recovered_bytes` | `bytes \| None` | Dữ liệu tệp sau khôi phục nếu `success=True`, ngược lại là `None`. |
| Lõi | `original_size` | `int` | Kích thước tệp gốc (bytes). |
| Lõi | `recovered_size` | `int` | Kích thước khôi phục nếu thành công (`0` nếu thất bại). |
| Lõi | `sha256_match` | `bool` | Kết quả đối chiếu SHA-256 tại `orchestrator`. |
| Lõi | `dropout_rate` | `float` | Giá trị `dropout_rate` cấu hình (`0.0..1.0`). |
| Lõi | `substitution_rate` | `float` | Giá trị `substitution_rate` cấu hình (`0.0..1.0`). |
| Lõi | `seed` | `int` | Seed đã dùng cho lượt mô phỏng (`-1` nếu `seed` đầu vào sai kiểu). |
| Lõi | `elapsed_ms` | `float` | Tổng thời gian thực thi toàn luồng (ms). |
| Mở rộng (11, OI-12) | `file_id` | `str \| None` | Mã định danh tệp trong `StorageController` (vd `"F01"`). |
| Mở rộng | `filename` | `str \| None` | Tên tệp đầu vào. |
| Mở rộng | `file_type` | `str \| None` | Phần mở rộng tệp (vd `"txt"`, `"png"`, `"pdf"`, `"bin"`). |
| Mở rộng | `ecc_mode` | `str \| None` | Chế độ ECC thực tế (`NONE`, `XOR_PARITY`, `REPLICATION_3X`, `HYBRID`). |
| Mở rộng | `chunk_size` | `int \| None` | Kích thước chunk (bytes). |
| Mở rộng | `n_packets` | `int` | Tổng số packet lưu kho (gồm DATA, PARITY và các bản sao). |
| Mở rộng | `n_packets_lost` | `int \| None` | Số packet lưu kho bị mất sau kênh nhiễu. |
| Mở rộng | `n_substituted_bases` | `int \| None` | Số nucleotide bị thay thế trên toàn bộ reads. |
| Mở rộng | `n_nucleotides` | `int` | Tổng số nucleotide lưu kho trước kênh nhiễu. |
| Mở rộng | `reason_detail` | `str` | Thông báo chi tiết nguyên nhân (hữu ích khi báo lỗi trên UI). |
| Mở rộng | `backends` | `dict[str, str]` | Nguồn các backend đã nạp: `{"encode_file": "real", "apply_noise": "real", "decode_or_recover": "real"}`. |

### 5.2. 9 mã `Reason` chuẩn (`dnastore.models.Reason` — OI-14)
1. `OK_CLEAN`: Không mất packet, không lỗi substitution, tệp khôi phục trùng gốc 100%.
2. `OK_RECOVERED`: Có mất packet hoặc sai base nhưng tầng ECC đã khôi phục trùng gốc 100%.
3. `FAIL_UNRECOVERABLE`: Vượt ngưỡng sửa lỗi (vd mất `>= 2` khối cùng nhóm XOR, hoặc mất sạch bản đọc).
4. `FAIL_HASH_MISMATCH`: Tầng giải mã trả về `bytes` nhưng sai lệch nội dung hoặc SHA-256 so với tệp gốc.
5. `FAIL_INVALID_INPUT`: Tệp rỗng (0 byte), sai định dạng đầu vào, hoặc `config`/`seed` không hợp lệ.
6. `FAIL_ENCODER_ERROR`: Bộ mã hóa gặp lỗi hoặc trả `expected_sha256` không khớp dữ liệu gốc.
7. `FAIL_STORAGE_ERROR`: Lỗi đọc/ghi `StorageController` (trùng `file_id`, không tìm thấy `file_id`, ...).
8. `FAIL_NOISE_ERROR`: Bộ mô phỏng nhiễu gặp lỗi cấu hình hoặc ngoại lệ khi chạy.
9. `FAIL_INTERNAL_ERROR`: Ngoại lệ không mong đợi trong điều phối nội bộ.

---

## 6. Hướng dẫn nhanh cho Dũng khi dựng `app.py`

### 6.1. Cách gọi `run_simulation()` từ Streamlit
```python
from dnastore import encode_file, run_simulation

raw_bytes = uploaded_file.getvalue()
filename = uploaded_file.name

# (Tùy chọn) Gọi encode_file nếu cần hiển thị bảng packet & chuỗi ADN mẫu trước khi gây nhiễu:
preview_packets, preview_meta = encode_file(
    raw_bytes,
    file_id="PREVIEW",
    chunk_size=32,
    filename=filename,
    ecc_mode=ecc_mode,
    ecc_params={"group_size": 4, "copies": 3 if ecc_mode in ("REPLICATION_3X", "HYBRID") else 1},
)

# Gọi mô phỏng chính thức qua orchestrator:
result = run_simulation(
    (filename, raw_bytes),
    config={
        "chunk_size": 32,
        "ecc_mode": ecc_mode,
        "group_size": 4,
        "copies": 3 if ecc_mode in ("REPLICATION_3X", "HYBRID") else 1,
        "dropout_rate": dropout_pct / 100.0,
        "substitution_rate": substitution_pct / 100.0,
        "read_count": int(read_count),
        # Với 3 nút preset demo, thêm "force_drop": force_drop_list
    },
    seed=int(seed),
)
```

### 6.2. 3 Kịch bản Preset Demo chuẩn (khớp `dnastore/cli.py`)
1. **Preset 1 — Không lỗi (`OK_CLEAN`):**
   `ecc_mode="XOR_PARITY"`, `dropout_rate=0.0`, `substitution_rate=0.0`, `force_drop=[]`, `seed=42`
2. **Preset 2 — Mất 1 DATA packet (`OK_RECOVERED`):**
   `ecc_mode="XOR_PARITY"`, `dropout_rate=0.0`, `substitution_rate=0.0`, `force_drop=[["DATA", 1]]`, `seed=42`
3. **Preset 3 — Mất 2 DATA packet cùng nhóm (`FAIL_UNRECOVERABLE`):**
   `ecc_mode="XOR_PARITY"`, `dropout_rate=0.0`, `substitution_rate=0.0`, `force_drop=[["DATA", 0], ["DATA", 1]]`, `seed=42`
