"""dna_encoder.py
Module mã hóa dữ liệu nhị phân (bytes) sang trình tự ADN (A, T, G, C),
chia khối (chunking), đóng gói Packet và tạo Metadata theo quy ước nhóm.

Tác giả gốc: Lương Việt Trung (Phụ trách DNA Encoder/Decoder & ECC).
Bản tích hợp đã bổ sung hỗ trợ `ecc_params` (chốt OI-03/OI-04) để tương thích hoàn toàn
với `RunConfig` và `orchestrator.py` của Thái.
"""
from __future__ import annotations

import hashlib
import zlib
from typing import Any, Dict, List, Optional, Tuple

BITS_TO_BASE: Dict[str, str] = {
    "00": "A",
    "01": "T",
    "10": "G",
    "11": "C",
}

BYTE_TO_DNA: List[str] = [
    "".join(BITS_TO_BASE[f"{b:08b}"[i:i + 2]] for i in range(0, 8, 2))
    for b in range(256)
]


def bytes_to_dna(data: bytes) -> str:
    """Chuyển đổi dãy bytes bất kỳ thành chuỗi ký tự A/T/G/C (1 byte = 4 nucleotide)."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Đầu vào 'data' phải có kiểu bytes hoặc bytearray.")
    return "".join(BYTE_TO_DNA[b] for b in data)


def compute_sha256(data: bytes) -> str:
    """Tính giá trị băm SHA-256 dạng chuỗi hex chữ thường."""
    return hashlib.sha256(data).hexdigest()


def compute_crc32(data: bytes) -> str:
    """Tính mã kiểm tra CRC-32 dạng 8 ký tự hex để phát hiện lỗi mức packet."""
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def compute_gc_content(dna_sequence: str) -> float:
    """Đo tỷ lệ phần trăm nucleotide G và C (chỉ số quan sát sinh học)."""
    if not dna_sequence:
        return 0.0
    gc_count = dna_sequence.count("G") + dna_sequence.count("C")
    return round((gc_count / len(dna_sequence)) * 100.0, 2)


def encode_file(
    data: bytes,
    file_id: str,
    chunk_size: int = 32,
    filename: str = "unknown.bin",
    ecc_mode: str = "NONE",
    group_size: int = 4,
    replication_factor: int = 1,
    ecc_params: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Chia tệp bytes thành các chunk, đệm 0x00 cho chunk cuối (lưu payload_len),
    mã hóa thành DNA packet và tạo metadata chuẩn hóa.

    Chốt OI-03/OI-04: hỗ trợ đồng thời tham số rời (`group_size`, `replication_factor`)
    và dict `ecc_params` (`{"group_size": ..., "copies": ...}`) do orchestrator của Thái truyền vào.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("Dữ liệu đầu vào phải là bytes.")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size phải là số nguyên dương.")
    if len(data) == 0:
        raise ValueError("Không hỗ trợ mã hóa tệp rỗng (0 byte).")

    if ecc_params is not None:
        if not isinstance(ecc_params, dict):
            raise TypeError("ecc_params phải là kiểu dict hoặc None.")
        if "group_size" in ecc_params:
            group_size = ecc_params["group_size"]
        if "replication_factor" in ecc_params:
            replication_factor = ecc_params["replication_factor"]
        elif "copies" in ecc_params:
            replication_factor = ecc_params["copies"]

    if isinstance(group_size, bool) or not isinstance(group_size, int) or group_size <= 0:
        raise ValueError("group_size phải là số nguyên dương.")
    if isinstance(replication_factor, bool) or not isinstance(replication_factor, int) or replication_factor <= 0:
        raise ValueError("replication_factor phải là số nguyên dương.")

    mode_raw = "" if ecc_mode is None else str(ecc_mode).upper()
    if mode_raw == "REPLICATION":
        mode_raw = "REPLICATION_3X"
    if mode_raw not in ("NONE", "REPLICATION_3X", "XOR_PARITY", "HYBRID"):
        raise ValueError(
            f"ecc_mode='{ecc_mode}' không hợp lệ; chỉ hỗ trợ NONE, REPLICATION_3X, XOR_PARITY, HYBRID."
        )

    raw_bytes = bytes(data)
    file_size = len(raw_bytes)
    expected_sha256 = compute_sha256(raw_bytes)

    chunks: List[Tuple[bytes, int]] = []
    for offset in range(0, file_size, chunk_size):
        chunk = raw_bytes[offset : offset + chunk_size]
        payload_len = len(chunk)
        padded_chunk = chunk + b"\x00" * (chunk_size - payload_len)
        chunks.append((padded_chunk, payload_len))

    total_data_packets = len(chunks)
    base_packets: List[Dict[str, Any]] = []
    for idx, (padded_chunk, payload_len) in enumerate(chunks):
        group_id = idx // group_size
        dna_seq = bytes_to_dna(padded_chunk)
        packet = {
            "file_id": file_id,
            "packet_id": idx,
            "total_packets": total_data_packets,
            "kind": "DATA",
            "group_id": group_id,
            "dna_sequence": dna_seq,
            "payload_len": payload_len,
            "copy_id": 0,
            "crc32": compute_crc32(padded_chunk),
        }
        base_packets.append(packet)

    if mode_raw == "NONE":
        packets = base_packets
        eff_rep = 1
    else:
        from .ecc_codec import add_redundancy
        packets, eff_rep = add_redundancy(
            base_packets=base_packets,
            chunk_size=chunk_size,
            ecc_mode=mode_raw,
            group_size=group_size,
            replication_factor=replication_factor,
        )

    metadata: Dict[str, Any] = {
        "file_id": file_id,
        "filename": filename or "unknown.bin",
        "file_size": file_size,
        "chunk_size": chunk_size,
        "total_packets": total_data_packets,
        "total_stored_packets": len(packets),
        "expected_sha256": expected_sha256,
        "ecc_mode": mode_raw,
        "group_size": group_size,
        "replication_factor": eff_rep,
        "ecc_params": {"group_size": group_size, "copies": eff_rep},
    }
    return packets, metadata
