"""dna_decoder.py
Module giải mã trình tự ADN (A, T, G, C) ngược về dữ liệu nhị phân (bytes),
ghép các packet theo đúng thứ tự, cắt bỏ byte đệm theo payload_len và xác minh SHA-256.
Tác giả: Lương Việt Trung.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

BASE_TO_BITS: Dict[str, str] = {
    "A": "00",
    "T": "01",
    "G": "10",
    "C": "11",
}
VALID_BASES = set(BASE_TO_BITS.keys())


def dna_to_bytes(dna_sequence: str) -> bytes:
    """Chuyển chuỗi ADN (A/T/G/C) có độ dài chia hết cho 4 thành dãy bytes."""
    if not isinstance(dna_sequence, str):
        raise TypeError("dna_sequence phải là chuỗi ký tự (str).")
    if len(dna_sequence) % 4 != 0:
        raise ValueError(f"Độ dài chuỗi ADN ({len(dna_sequence)}) không chia hết cho 4.")
    invalid = set(dna_sequence) - VALID_BASES
    if invalid:
        raise ValueError(
            f"Chuỗi ADN chứa ký tự không hợp lệ: {sorted(invalid)} (chỉ chấp nhận A, T, G, C)."
        )
    out = bytearray(len(dna_sequence) // 4)
    for i in range(0, len(dna_sequence), 4):
        b0 = BASE_TO_BITS[dna_sequence[i]]
        b1 = BASE_TO_BITS[dna_sequence[i + 1]]
        b2 = BASE_TO_BITS[dna_sequence[i + 2]]
        b3 = BASE_TO_BITS[dna_sequence[i + 3]]
        out[i // 4] = int(b0 + b1 + b2 + b3, 2)
    return bytes(out)


def verify_sha256(data: bytes, expected_sha256: str) -> bool:
    """Đối chiếu giá trị băm SHA-256 ở bước xác minh cuối cùng."""
    actual = hashlib.sha256(data).hexdigest()
    return actual == expected_sha256


def decode_file(
    packets: List[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Tuple[Optional[bytes], bool, str]:
    """Giải mã trực tiếp danh sách packet DATA (không qua sửa lỗi ECC) thành bytes gốc."""
    if not metadata or "total_packets" not in metadata or "file_size" not in metadata:
        return None, False, "Metadata không hợp lệ hoặc thiếu trường bắt buộc."

    total_data_packets = metadata["total_packets"]
    chunk_size = metadata.get("chunk_size", 32)
    expected_len_nt = chunk_size * 4
    expected_sha256 = metadata.get("expected_sha256")
    file_size = metadata["file_size"]

    data_map: Dict[int, Dict[str, Any]] = {}
    for pkt in packets:
        if pkt.get("kind", "DATA") == "DATA":
            pid = pkt.get("packet_id")
            if pid is not None and pid not in data_map:
                data_map[pid] = pkt

    missing_ids = [i for i in range(total_data_packets) if i not in data_map]
    if missing_ids:
        return None, False, f"Thiếu {len(missing_ids)} DATA packet (packet_id={missing_ids}); không thể ghép tệp."

    assembled = bytearray()
    for pid in range(total_data_packets):
        pkt = data_map[pid]
        seq = pkt.get("dna_sequence", "")
        if len(seq) != expected_len_nt:
            return None, False, f"Packet {pid} có chiều dài ADN sai ({len(seq)} != {expected_len_nt})."
        try:
            padded_bytes = dna_to_bytes(seq)
        except ValueError as exc:
            return None, False, f"Lỗi giải mã ADN tại packet {pid}: {exc}"
        payload_len = pkt.get("payload_len", chunk_size)
        if not (0 < payload_len <= chunk_size):
            return None, False, f"payload_len không hợp lệ ({payload_len}) tại packet {pid}."
        assembled.extend(padded_bytes[:payload_len])

    recovered = bytes(assembled)
    if len(recovered) != file_size:
        return None, False, f"Kích thước sau ghép ({len(recovered)} B) không khớp metadata ({file_size} B)."

    sha_ok = verify_sha256(recovered, expected_sha256) if expected_sha256 else True
    if not sha_ok:
        return None, False, "Giải mã xong nhưng SHA-256 không khớp (dữ liệu có lỗi nucleotide chưa được sửa)."
    return recovered, True, "OK"
