"""MOCK tạm thời của Thái dùng đối chiếu hoặc chạy thử khi bật DNASTORE_USE_MOCK=1."""
from __future__ import annotations

from collections import Counter
import math
import random

from .errors import RecoveryFailure
from .metadata_manager import sha256_hex
from .models import ALPHABET


def bytes_to_dna(data: bytes) -> str:
    return "".join(ALPHABET[(b >> s) & 3] for b in data for s in (6, 4, 2, 0))


def dna_to_bytes(seq: str) -> bytes:
    if len(seq) % 4:
        raise ValueError("độ dài chuỗi ADN phải chia hết cho 4")
    idx = {c: i for i, c in enumerate(ALPHABET)}
    return bytes(
        (idx[seq[i]] << 6) | (idx[seq[i + 1]] << 4) | (idx[seq[i + 2]] << 2) | idx[seq[i + 3]]
        for i in range(0, len(seq), 4)
    )


def _xor(blocks: list[bytes]) -> bytes:
    out = bytearray(len(blocks[0]))
    for b in blocks:
        for i, x in enumerate(b):
            out[i] ^= x
    return bytes(out)


def mock_encode_file(
    data: bytes,
    file_id: str,
    chunk_size: int,
    ecc_mode: str = "XOR_PARITY",
    ecc_params: dict | None = None,
):
    ecc_params = ecc_params or {}
    gs = int(ecc_params.get("group_size", 4))
    if ecc_mode not in ("NONE", "XOR_PARITY"):
        raise ValueError(f"mock encoder không hỗ trợ ecc_mode={ecc_mode!r}")
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    padded = [c + bytes(chunk_size - len(c)) for c in chunks]
    n_data = len(chunks)
    n_groups = math.ceil(n_data / gs)
    total = n_data + (n_groups if ecc_mode == "XOR_PARITY" else 0)
    packets = [
        {
            "file_id": file_id,
            "packet_id": i,
            "total_packets": total,
            "kind": "DATA",
            "group_id": i // gs,
            "dna_sequence": bytes_to_dna(padded[i]),
            "payload_len": len(chunks[i]),
            "copy_id": 0,
        }
        for i in range(n_data)
    ]
    if ecc_mode == "XOR_PARITY":
        for g in range(n_groups):
            members = padded[g * gs : (g + 1) * gs]
            packets.append(
                {
                    "file_id": file_id,
                    "packet_id": n_data + g,
                    "total_packets": total,
                    "kind": "PARITY",
                    "group_id": g,
                    "dna_sequence": bytes_to_dna(_xor(members)),
                    "payload_len": chunk_size,
                    "copy_id": 0,
                }
            )
    metadata = {
        "file_id": file_id,
        "filename": "",
        "file_size": len(data),
        "chunk_size": chunk_size,
        "total_packets": total,
        "expected_sha256": sha256_hex(data),
        "ecc_mode": ecc_mode,
        "ecc_params": {"group_size": gs},
    }
    return packets, metadata


def mock_apply_noise(packets: list[dict], config: dict, seed: int):
    rng = random.Random(seed)
    drop_p = config.get("dropout_rate", 0.0)
    sub_p = config.get("substitution_rate", 0.0)
    n_reads = config.get("read_count", 1)
    forced = {(k, i) for k, i in config.get("force_drop", [])}
    reads, dropped, subs = [], 0, 0
    for p in packets:
        if (p["kind"], p["packet_id"]) in forced or rng.random() < drop_p:
            dropped += 1
            continue
        for r in range(n_reads):
            seq = list(p["dna_sequence"])
            for j, c in enumerate(seq):
                if rng.random() < sub_p:
                    seq[j] = rng.choice([x for x in ALPHABET if x != c])
                    subs += 1
            read = dict(p)
            read["dna_sequence"] = "".join(seq)
            read["read_id"] = r
            reads.append(read)
    stats = {
        "n_packets_in": len(packets),
        "n_dropped_packets": dropped,
        "n_substituted_bases": subs,
        "n_reads": len(reads),
    }
    return reads, stats


def _consensus(seqs: list[str]) -> str:
    if len(seqs) == 1 or len({len(s) for s in seqs}) != 1:
        return seqs[0]
    return "".join(Counter(col).most_common(1)[0][0] for col in zip(*seqs))


def mock_decode_or_recover(reads: list[dict], metadata: dict) -> bytes:
    cs, size = metadata["chunk_size"], metadata["file_size"]
    gs = metadata.get("ecc_params", {}).get("group_size", 4)
    n_data = math.ceil(size / cs)
    by_key: dict[tuple, list[str]] = {}
    for r in reads:
        by_key.setdefault((r["kind"], r["packet_id"]), []).append(r["dna_sequence"])
    blocks = {k: dna_to_bytes(_consensus(v)) for k, v in by_key.items()}
    chunks: list[bytes] = []
    for g in range(math.ceil(n_data / gs)):
        ids = list(range(g * gs, min((g + 1) * gs, n_data)))
        missing = [i for i in ids if ("DATA", i) not in blocks]
        if missing:
            parity = blocks.get(("PARITY", n_data + g))
            if metadata["ecc_mode"] != "XOR_PARITY" or parity is None or len(missing) > 1:
                raise RecoveryFailure(
                    f"nhóm {g}: mất {len(missing)} chunk DATA, "
                    f"parity {'còn' if parity is not None else 'mất'}; vượt khả năng sửa của parity đơn"
                )
            known = [blocks[("DATA", i)] for i in ids if i not in missing]
            blocks[("DATA", missing[0])] = _xor(known + [parity])
        chunks.extend(blocks[("DATA", i)] for i in ids)
    return b"".join(chunks)[:size]
