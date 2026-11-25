"""Hợp đồng dữ liệu dùng chung (DNAPacket, RunConfig, Reason, kiểm tra schema kết quả).
Kiến trúc: Thái; đã đồng bộ các mục chốt OI-01..OI-15 với Trung và Linh.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .errors import ValidationError

ALPHABET = "ATGC"  # 00->A, 01->T, 10->G, 11->C (tuyệt đối không dùng chữ 'X')
KINDS = ("DATA", "PARITY")
SUPPORTED_ECC_MODES = ("NONE", "XOR_PARITY", "REPLICATION_3X", "HYBRID")

PACKET_FIELDS = (
    "file_id",
    "packet_id",
    "total_packets",
    "kind",
    "group_id",
    "dna_sequence",
    "payload_len",
    "copy_id",
)
METADATA_REQUIRED = (
    "file_id",
    "filename",
    "file_size",
    "chunk_size",
    "total_packets",
    "expected_sha256",
    "ecc_mode",
)
_CRC32_RE = re.compile(r"^[0-9a-fA-F]{8}$")


class Reason:
    """Mã lý do chuẩn cho trường `reason` (chốt OI-14)."""
    OK_CLEAN = "OK_CLEAN"                       # Không có lỗi nào được gây ra và tệp trùng gốc
    OK_RECOVERED = "OK_RECOVERED"               # Có lỗi và đã khôi phục trùng gốc
    FAIL_UNRECOVERABLE = "FAIL_UNRECOVERABLE"   # Vượt khả năng dự phòng (vd mất >= 2 khối/nhóm)
    FAIL_HASH_MISMATCH = "FAIL_HASH_MISMATCH"   # Có byte trả về nhưng khác tệp gốc / SHA-256
    FAIL_INVALID_INPUT = "FAIL_INVALID_INPUT"   # Tệp rỗng, config sai, metadata/packet sai
    FAIL_ENCODER_ERROR = "FAIL_ENCODER_ERROR"
    FAIL_STORAGE_ERROR = "FAIL_STORAGE_ERROR"
    FAIL_NOISE_ERROR = "FAIL_NOISE_ERROR"
    FAIL_INTERNAL_ERROR = "FAIL_INTERNAL_ERROR"


@dataclass(frozen=True)
class DNAPacket:
    """Đối tượng bất biến kiểm tra hợp lệ cho một packet.
    Dạng trao đổi chính thức giữa các module là dict (chốt OI-01).
    Các trường mở rộng hợp lệ của codec (như `crc32`, `covered_packet_ids`) được giữ nguyên khi lưu kho.
    """
    file_id: str
    packet_id: int
    total_packets: int
    kind: str
    group_id: int
    dna_sequence: str
    payload_len: int
    copy_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in PACKET_FIELDS}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DNAPacket":
        if not isinstance(d, dict):
            raise ValidationError(f"packet phải là dict, nhận {type(d).__name__}")
        missing = [f for f in PACKET_FIELDS if f not in d]
        if missing:
            raise ValidationError(f"packet thiếu trường: {missing}")
        return cls(**{f: d[f] for f in PACKET_FIELDS})

    def validate(self) -> "DNAPacket":
        def is_int(x: Any) -> bool:
            return isinstance(x, int) and not isinstance(x, bool)

        if not isinstance(self.file_id, str) or not self.file_id:
            raise ValidationError("file_id phải là chuỗi không rỗng")
        for name in ("packet_id", "group_id", "payload_len", "copy_id"):
            v = getattr(self, name)
            if not is_int(v) or v < 0:
                raise ValidationError(f"{name} phải là số nguyên >= 0, nhận {v!r}")
        if not is_int(self.total_packets) or self.total_packets < 1:
            raise ValidationError(f"total_packets phải >= 1, nhận {self.total_packets!r}")
        if self.kind not in KINDS:
            raise ValidationError(f"kind phải thuộc {KINDS}, nhận {self.kind!r}")
        if not isinstance(self.dna_sequence, str) or not self.dna_sequence:
            raise ValidationError("dna_sequence phải là chuỗi không rỗng")
        bad = set(self.dna_sequence) - set(ALPHABET)
        if bad:
            raise ValidationError(f"dna_sequence chứa ký tự ngoài {ALPHABET}: {sorted(bad)}")
        if self.payload_len * 4 > len(self.dna_sequence):
            raise ValidationError("payload_len vượt sức chứa của dna_sequence (2 bit/nucleotide)")
        return self


def validate_packet_extra_fields(d: dict[str, Any]) -> None:
    """Kiểm tra các trường mở rộng của Trung (crc32, covered_packet_ids) nếu xuất hiện trong packet dict."""
    if "crc32" in d and d["crc32"] is not None:
        if not isinstance(d["crc32"], str) or not _CRC32_RE.match(d["crc32"]):
            raise ValidationError(f"crc32 phải là chuỗi 8 ký tự hex, nhận {d['crc32']!r}")
    if "covered_packet_ids" in d and d["covered_packet_ids"] is not None:
        cov = d["covered_packet_ids"]
        if not isinstance(cov, list) or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in cov):
            raise ValidationError("covered_packet_ids phải là danh sách số nguyên >= 0")


@dataclass
class RunConfig:
    """Cấu hình một lần chạy (phẳng, tiện cho Streamlit/benchmark truyền vào)."""
    chunk_size: int = 32
    ecc_mode: str = "XOR_PARITY"  # Chốt OI-05: NONE / XOR_PARITY / REPLICATION_3X / HYBRID
    group_size: int = 4
    copies: int = 1
    dropout_rate: float = 0.0
    substitution_rate: float = 0.0
    read_count: int = 1
    force_drop: list[Any] = field(default_factory=list)  # Chốt OI-11: [[kind, packet_id], ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RunConfig":
        d = dict(d or {})
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValidationError(f"config có khóa lạ: {sorted(unknown)}")
        return cls(**d).validate()

    def validate(self) -> "RunConfig":
        def is_int(x: Any) -> bool:
            return isinstance(x, int) and not isinstance(x, bool)

        for name in ("chunk_size", "group_size", "copies", "read_count"):
            v = getattr(self, name)
            if not is_int(v) or v < 1:
                raise ValidationError(f"{name} phải là số nguyên >= 1, nhận {v!r}")
        for name in ("dropout_rate", "substitution_rate"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                raise ValidationError(f"{name} phải nằm trong [0, 1], nhận {v!r}")
            setattr(self, name, float(v))
        if not isinstance(self.ecc_mode, str) or not self.ecc_mode:
            raise ValidationError("ecc_mode phải là chuỗi không rỗng")
        self.ecc_mode = self.ecc_mode.upper()
        if not isinstance(self.force_drop, list):
            raise ValidationError("force_drop phải là danh sách (list)")
        return self

    def ecc_params(self) -> dict[str, Any]:
        return {"group_size": self.group_size, "copies": self.copies}

    def noise_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "dropout_rate": self.dropout_rate,
            "substitution_rate": self.substitution_rate,
            "read_count": self.read_count,
        }
        if self.force_drop:
            cfg["force_drop"] = [list(x) for x in self.force_drop]
        return cfg


RESULT_CORE_FIELDS: dict[str, tuple[type, ...]] = {
    "success": (bool,),
    "reason": (str,),
    "recovered_bytes": (bytes, type(None)),
    "original_size": (int,),
    "recovered_size": (int,),
    "sha256_match": (bool,),
    "dropout_rate": (float,),
    "substitution_rate": (float,),
    "seed": (int,),
    "elapsed_ms": (float,),
}

RESULT_EXTENSION_FIELDS = (
    "file_id",
    "filename",
    "file_type",
    "ecc_mode",
    "chunk_size",
    "n_packets",
    "n_packets_lost",
    "n_substituted_bases",
    "n_nucleotides",
    "reason_detail",
    "backends",
)


def check_result_schema(result: dict[str, Any]) -> list[str]:
    """Trả về danh sách lỗi schema (rỗng = hợp lệ). Dùng trong test và khi chốt API."""
    problems: list[str] = []
    for name, types in RESULT_CORE_FIELDS.items():
        if name not in result:
            problems.append(f"thiếu trường {name}")
        elif not isinstance(result[name], types) or (types == (int,) and isinstance(result[name], bool)):
            problems.append(f"{name}: kiểu {type(result[name]).__name__} không hợp lệ")
    if result.get("success") is True and result.get("recovered_bytes") is None:
        problems.append("success=True nhưng recovered_bytes=None")
    if result.get("success") is False and result.get("recovered_bytes") is not None:
        problems.append("success=False nhưng recovered_bytes khác None")
    return problems
