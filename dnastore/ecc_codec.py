"""ecc_codec.py
Module tạo dữ liệu dự phòng (Replication 3x, XOR Parity theo nhóm, và Hybrid)
và thực thi chuỗi khôi phục chuẩn:
    consensus (majority vote) -> kiểm CRC-32 & fallback / đánh dấu erasure -> XOR parity -> ghép bytes -> (xác minh SHA-256 nếu có).

Tác giả gốc: Lương Việt Trung.
Bản tích hợp đã sửa lỗi tích hợp #2 (chốt OI-10 với Thái):
  - Cho phép `metadata` không chứa `expected_sha256` (khi gọi qua `recovery_view(md)` của
    `orchestrator.py` với `PASS_HASH_TO_RECOVERY = False`). Khi đó `ecc_codec` trả bytes khôi phục
    để `orchestrator` tự thực hiện đối chiếu byte + SHA-256 ở bước cuối.
  - Nếu `expected_sha256` được truyền vào (khi chạy độc lập), vẫn giữ nguyên kiểm tra SHA-256 như cũ.
  - Đọc `group_size` linh hoạt từ `metadata['group_size']` hoặc `metadata['ecc_params']['group_size']`.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import time
from typing import Any, Dict, List, Optional, Tuple

from .dna_decoder import VALID_BASES, dna_to_bytes, verify_sha256
from .dna_encoder import bytes_to_dna, compute_crc32

SUPPORTED_ECC_MODES = ("NONE", "REPLICATION_3X", "XOR_PARITY", "HYBRID")


def xor_bytes_list(chunks: List[bytes]) -> bytes:
    """Tính phép XOR từng byte (bitwise XOR) của một danh sách các chunk cùng độ dài."""
    if not chunks:
        raise ValueError("Danh sách chunk để tính XOR không được rỗng.")
    length = len(chunks[0])
    result = bytearray(length)
    for chunk in chunks:
        if len(chunk) != length:
            raise ValueError("Tất cả các chunk trong phép XOR phải có cùng độ dài.")
        for i in range(length):
            result[i] ^= chunk[i]
    return bytes(result)


def add_redundancy(
    base_packets: List[Dict[str, Any]],
    chunk_size: int,
    ecc_mode: str = "XOR_PARITY",
    group_size: int = 4,
    replication_factor: int = 3,
) -> Tuple[List[Dict[str, Any]], int]:
    """Sinh dữ liệu dự phòng TRƯỚC khi đưa vào kho lưu trữ / kênh nhiễu."""
    mode = ecc_mode.upper()
    if mode == "REPLICATION":
        mode = "REPLICATION_3X"
    if mode == "NONE":
        return [dict(p) for p in base_packets], 1

    logical_packets: List[Dict[str, Any]] = [dict(p) for p in base_packets]
    if mode in ("XOR_PARITY", "HYBRID"):
        groups: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for pkt in base_packets:
            groups[pkt["group_id"]].append(pkt)
        next_packet_id = len(base_packets)
        file_id = base_packets[0]["file_id"]
        total_data = base_packets[0]["total_packets"]
        for gid in sorted(groups.keys()):
            group_pkts = sorted(groups[gid], key=lambda x: x["packet_id"])
            group_bytes = [dna_to_bytes(p["dna_sequence"]) for p in group_pkts]
            parity_bytes = xor_bytes_list(group_bytes)
            parity_dna = bytes_to_dna(parity_bytes)
            parity_pkt = {
                "file_id": file_id,
                "packet_id": next_packet_id,
                "total_packets": total_data,
                "kind": "PARITY",
                "group_id": gid,
                "dna_sequence": parity_dna,
                "payload_len": chunk_size,
                "copy_id": 0,
                "crc32": compute_crc32(parity_bytes),
                "covered_packet_ids": [p["packet_id"] for p in group_pkts],
            }
            logical_packets.append(parity_pkt)
            next_packet_id += 1

    if mode in ("REPLICATION_3X", "HYBRID"):
        rep = max(2, replication_factor) if replication_factor > 1 else 3
        replicated_packets: List[Dict[str, Any]] = []
        for pkt in logical_packets:
            for c_id in range(rep):
                copy_pkt = dict(pkt)
                copy_pkt["copy_id"] = c_id
                replicated_packets.append(copy_pkt)
        return replicated_packets, rep
    return logical_packets, 1


def majority_vote_consensus(reads: List[str], expected_len: int) -> Tuple[Optional[str], str]:
    """Thực hiện đồng thuận theo đa số (majority vote) cho các bản đọc cùng chiều dài."""
    valid_reads = [
        r for r in reads
        if isinstance(r, str)
        and len(r) == expected_len
        and set(r).issubset(VALID_BASES)
    ]
    if not valid_reads:
        return None, "Không còn bản đọc hợp lệ nào (dropout hoặc sai chiều dài/ký tự)."
    if len(valid_reads) == 1:
        return valid_reads[0], "OK (1 read)"

    consensus_chars: List[str] = []
    ties = 0
    for pos in range(expected_len):
        col = [r[pos] for r in valid_reads]
        counts = Counter(col).most_common()
        if len(counts) > 1 and counts[0][1] == counts[1][1]:
            ties += 1
            consensus_chars.append(counts[0][0])
        else:
            consensus_chars.append(counts[0][0])
    if ties > 0 and len(valid_reads) == 2:
        return None, f"Hòa phiếu giữa 2 bản đọc tại {ties} vị trí base."
    return "".join(consensus_chars), f"OK (consensus từ {len(valid_reads)} reads)"


def _fail(reason: str, metadata: Any, stats: Optional[Dict[str, Any]] = None, error_type: str = "UNRECOVERABLE") -> Dict[str, Any]:
    file_size = metadata.get("file_size", 0) if isinstance(metadata, dict) else 0
    return {
        "success": False,
        "reason": reason,
        "error_type": error_type,
        "recovered_bytes": None,
        "original_size": file_size if isinstance(file_size, int) and not isinstance(file_size, bool) else 0,
        "recovered_size": 0,
        "sha256_match": False,
        "stats": stats or {},
    }


def decode_or_recover(
    reads: List[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """API lõi ECC (chỉ nhận đúng 2 tham số: reads, metadata — không bao giờ nhận tệp gốc)."""
    t0 = time.perf_counter()
    result = _validate_and_recover(reads, metadata)
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    return result


def _validate_and_recover(reads: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    if not metadata or not isinstance(metadata, dict):
        return _fail("Metadata rỗng hoặc không đúng định dạng dict.", metadata, error_type="INVALID_METADATA")

    # Sửa lỗi tích hợp #2 (OI-10): expected_sha256 là tùy chọn khi orchestrator dùng recovery_view(md)
    required_keys = ["file_size", "chunk_size", "total_packets"]
    missing_meta = [k for k in required_keys if k not in metadata]
    if missing_meta:
        return _fail(
            f"Metadata thiếu các trường bắt buộc: {missing_meta}.",
            metadata,
            error_type="INVALID_METADATA",
        )

    file_size, chunk_size, total_data = metadata["file_size"], metadata["chunk_size"], metadata["total_packets"]
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (file_size, chunk_size, total_data)):
        return _fail(
            "Metadata không hợp lệ: file_size/chunk_size/total_packets phải là số nguyên.",
            metadata,
            error_type="INVALID_METADATA",
        )
    if chunk_size <= 0 or file_size <= 0:
        return _fail(
            f"Metadata không hợp lệ: chunk_size={chunk_size}, file_size={file_size} phải > 0.",
            metadata,
            error_type="INVALID_METADATA",
        )

    expected_total = (file_size + chunk_size - 1) // chunk_size
    if total_data != expected_total:
        return _fail(
            f"Metadata không phù hợp: file_size={file_size} B với chunk_size={chunk_size} B cần "
            f"{expected_total} DATA packet, nhưng metadata ghi total_packets={total_data}.",
            metadata,
            error_type="INVALID_METADATA",
        )

    ecc_mode = str(metadata.get("ecc_mode", "NONE")).upper()
    if ecc_mode == "REPLICATION":
        ecc_mode = "REPLICATION_3X"
    if ecc_mode not in SUPPORTED_ECC_MODES:
        return _fail(
            f"Metadata không hợp lệ: ecc_mode='{ecc_mode}' không được hỗ trợ {SUPPORTED_ECC_MODES}.",
            metadata,
            error_type="INVALID_METADATA",
        )

    ecc_params = metadata.get("ecc_params") if isinstance(metadata.get("ecc_params"), dict) else {}
    group_size = metadata.get("group_size", ecc_params.get("group_size", 4))
    if isinstance(group_size, bool) or not isinstance(group_size, int) or group_size <= 0:
        return _fail(
            f"Metadata không hợp lệ: group_size={group_size} phải là số nguyên > 0.",
            metadata,
            error_type="INVALID_METADATA",
        )

    file_id = metadata.get("file_id")
    reads = list(reads or [])
    valid_reads = [r for r in reads if isinstance(r, dict) and (file_id is None or r.get("file_id") == file_id)]
    rejected = len(reads) - len(valid_reads)
    if reads and not valid_reads:
        return _fail(
            f"Không có read nào thuộc file_id='{file_id}' ({rejected} read bị loại do sai file_id/định dạng).",
            metadata,
            {"rejected_reads": rejected},
            error_type="UNRECOVERABLE",
        )
    result = _decode_or_recover_core(valid_reads, metadata, ecc_mode=ecc_mode, group_size=group_size)
    result.setdefault("stats", {})["rejected_reads"] = rejected
    return result


def _decode_or_recover_core(
    reads: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    *,
    ecc_mode: str,
    group_size: int,
) -> Dict[str, Any]:
    file_size: int = metadata["file_size"]
    chunk_size: int = metadata["chunk_size"]
    total_data: int = metadata["total_packets"]
    expected_sha256: Optional[str] = metadata.get("expected_sha256")
    expected_len_nt = chunk_size * 4

    if not reads:
        return {
            "success": False,
            "reason": "Danh sách bản đọc (reads) rỗng; toàn bộ packet đã bị mất.",
            "error_type": "UNRECOVERABLE",
            "recovered_bytes": None,
            "original_size": file_size,
            "recovered_size": 0,
            "sha256_match": False,
            "stats": {"erased_data_packets": total_data, "parity_recovered": 0},
        }

    grouped_reads: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in reads:
        pid = r.get("packet_id")
        if pid is not None:
            grouped_reads[pid].append(r)

    num_groups = (total_data + group_size - 1) // group_size
    group_to_data_ids: Dict[int, List[int]] = {
        gid: list(range(gid * group_size, min((gid + 1) * group_size, total_data)))
        for gid in range(num_groups)
    }
    group_to_parity_id: Dict[int, int] = {gid: total_data + gid for gid in range(num_groups)}

    recovered_chunks: Dict[int, Optional[bytes]] = {}
    erasure_reasons: Dict[int, str] = {}
    consensus_fixes = 0
    crc_fallback_fixes: List[int] = []

    def process_packet_id(pid: int) -> None:
        nonlocal consensus_fixes
        pkt_reads = grouped_reads.get(pid, [])
        if not pkt_reads:
            recovered_chunks[pid] = None
            erasure_reasons[pid] = "Dropout (không còn bản đọc nào)."
            return
        seqs = [r.get("dna_sequence", "") for r in pkt_reads]
        consensus_seq, c_msg = majority_vote_consensus(seqs, expected_len_nt)
        crc_candidates = [r.get("crc32") for r in pkt_reads if r.get("crc32")]
        expected_crc = Counter(crc_candidates).most_common(1)[0][0] if crc_candidates else None

        def crc_fallback() -> Optional[bytes]:
            if expected_crc is None:
                return None
            for s in dict.fromkeys(seqs):
                if isinstance(s, str) and len(s) == expected_len_nt and set(s).issubset(VALID_BASES):
                    b = dna_to_bytes(s)
                    if compute_crc32(b) == expected_crc:
                        return b
            return None

        if consensus_seq is None:
            fb = crc_fallback()
            if fb is not None:
                recovered_chunks[pid] = fb
                crc_fallback_fixes.append(pid)
                return
            recovered_chunks[pid] = None
            erasure_reasons[pid] = c_msg
            return

        if len(set(seqs)) > 1:
            consensus_fixes += 1

        try:
            chunk_bytes = dna_to_bytes(consensus_seq)
        except ValueError as exc:
            recovered_chunks[pid] = None
            erasure_reasons[pid] = f"Lỗi giải mã ADN: {exc}"
            return

        if expected_crc is not None:
            actual_crc = compute_crc32(chunk_bytes)
            if actual_crc != expected_crc:
                fb = crc_fallback()
                if fb is not None:
                    recovered_chunks[pid] = fb
                    crc_fallback_fixes.append(pid)
                    return
                recovered_chunks[pid] = None
                erasure_reasons[pid] = (
                    f"Sai CRC-32 (actual={actual_crc} != expected={expected_crc}) -> đánh dấu erasure."
                )
                return

        recovered_chunks[pid] = chunk_bytes

    for pid in range(total_data):
        process_packet_id(pid)

    has_parity = ecc_mode in ("XOR_PARITY", "HYBRID")
    if has_parity:
        for gid in range(num_groups):
            process_packet_id(group_to_parity_id[gid])

    parity_recovered_ids: List[int] = []
    unrecoverable_groups: List[str] = []
    for gid in range(num_groups):
        data_ids = group_to_data_ids[gid]
        missing_data = [pid for pid in data_ids if recovered_chunks.get(pid) is None]
        if not missing_data:
            continue
        if not has_parity:
            unrecoverable_groups.append(
                f"Nhóm {gid} thiếu DATA packet {missing_data} (chế độ {ecc_mode} không có XOR parity)"
            )
            continue
        parity_id = group_to_parity_id[gid]
        parity_missing = recovered_chunks.get(parity_id) is None
        total_missing_in_group = len(missing_data) + (1 if parity_missing else 0)
        if total_missing_in_group == 1 and len(missing_data) == 1:
            target_pid = missing_data[0]
            surviving_bytes = [recovered_chunks[pid] for pid in data_ids if pid != target_pid]
            surviving_bytes.append(recovered_chunks[parity_id])
            recovered_chunks[target_pid] = xor_bytes_list(surviving_bytes)
            parity_recovered_ids.append(target_pid)
        else:
            lost_list = missing_data + ([f"PARITY({parity_id})"] if parity_missing else [])
            unrecoverable_groups.append(
                f"Nhóm {gid} mất {total_missing_in_group} khối ({lost_list}); "
                f"XOR parity đơn chỉ khôi phục tối đa 1 khối mất/nhóm."
            )

    if unrecoverable_groups:
        return {
            "success": False,
            "reason": "Khôi phục thất bại: " + " | ".join(unrecoverable_groups),
            "error_type": "UNRECOVERABLE",
            "recovered_bytes": None,
            "original_size": file_size,
            "recovered_size": 0,
            "sha256_match": False,
            "stats": {
                "consensus_fixes": consensus_fixes,
                "crc_fallback_fixes": crc_fallback_fixes,
                "parity_recovered_ids": parity_recovered_ids,
                "erasure_reasons": erasure_reasons,
            },
        }

    assembled = bytearray()
    for pid in range(total_data):
        chunk_bytes = recovered_chunks[pid]
        if chunk_bytes is None:
            return {
                "success": False,
                "reason": f"Lỗi nội bộ: packet {pid} vẫn rỗng sau bước khôi phục.",
                "error_type": "UNRECOVERABLE",
                "recovered_bytes": None,
                "original_size": file_size,
                "recovered_size": 0,
                "sha256_match": False,
                "stats": {},
            }
        if pid < total_data - 1:
            p_len = chunk_size
        else:
            remainder = file_size % chunk_size
            p_len = chunk_size if remainder == 0 else remainder
        assembled.extend(chunk_bytes[:p_len])

    recovered_data = bytes(assembled)
    stats_out = {
        "consensus_fixes": consensus_fixes,
        "crc_fallback_fixes": crc_fallback_fixes,
        "parity_recovered_ids": parity_recovered_ids,
        "erasure_reasons": erasure_reasons,
    }

    # Nếu expected_sha256 có trong metadata (chạy độc lập): đối chiếu tại đây.
    # Nếu expected_sha256 bị ẩn bởi recovery_view(md) của Thái (OI-10): trả bytes để orchestrator đối chiếu.
    if expected_sha256 is not None:
        sha_match = verify_sha256(recovered_data, expected_sha256)
        if not sha_match:
            return {
                "success": False,
                "reason": (
                    "Các packet đủ số lượng nhưng SHA-256 không khớp bản gốc "
                    "(lỗi substitution chưa phát hiện/vượt khả năng sửa)."
                ),
                "error_type": "HASH_MISMATCH",
                "recovered_bytes": None,
                "original_size": file_size,
                "recovered_size": len(recovered_data),
                "sha256_match": False,
                "stats": stats_out,
            }
        return {
            "success": True,
            "reason": "Khôi phục thành công, SHA-256 trùng khớp 100%.",
            "error_type": None,
            "recovered_bytes": recovered_data,
            "original_size": file_size,
            "recovered_size": len(recovered_data),
            "sha256_match": True,
            "stats": stats_out,
        }

    return {
        "success": True,
        "reason": "Khôi phục dữ liệu hoàn tất (chờ orchestrator xác minh byte và SHA-256).",
        "error_type": None,
        "recovered_bytes": recovered_data,
        "original_size": file_size,
        "recovered_size": len(recovered_data),
        "sha256_match": False,
        "stats": stats_out,
    }
