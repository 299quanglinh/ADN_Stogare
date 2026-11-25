"""noise_simulator.py
Mô phỏng mất packet (dropout) và thay base (substitution) bằng bộ sinh số giả ngẫu nhiên có seed.

Tác giả gốc: Nguyễn Quang Linh.
Bản tích hợp đã đồng bộ với kiến trúc của Thái và ECC của Trung:
  - Sửa lỗi tích hợp #5a (OI-11): hỗ trợ `force_drop` dạng `[["DATA", 1], ...]` (hoặc `["DATA", 1, copy_id]`)
    để chạy xác định các ca T03/T04/T05 và 3 kịch bản demo CLI.
  - Sửa lỗi tích hợp #5b (OI-08): trả đầy đủ cả khóa chuẩn của Thái (`n_packets_in`, `n_dropped_packets`,
    `n_substituted_bases`, `n_reads`) lẫn khóa chi tiết của Linh (`logical_packets_*`, `source_packets_*`,
    `bases_processed`, `bases_substituted`, `observed_*`).
  - Sửa lỗi tích hợp #5c: mặc định `dropout_scope="packet"` rút thăm dropout độc lập theo từng bản sao lưu kho
    (source packet có copy_id riêng) để REPLICATION_3X và HYBRID phát huy đúng cơ chế dự phòng dropout
    (với NONE và XOR_PARITY chỉ có 1 bản sao nên kết quả đồng nhất với dropout logic). Hỗ trợ thêm
    `dropout_scope="logical"` nếu cần khảo sát dropout tương quan mất sạch mọi bản sao.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
import random
from typing import Any

BASES = "ATGC"
ALTERNATIVES = {base: tuple(other for other in BASES if other != base) for base in BASES}
CONFIG_KEYS = {"dropout_rate", "substitution_rate", "read_count", "force_drop", "dropout_scope"}


def _rate(config: Mapping[str, Any], name: str) -> float:
    value = config.get(name, 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in [0, 1]")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite and in [0, 1]")
    return float(value)


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _parse_force_drop(raw_force_drop: Any) -> tuple[set[tuple[str, int]], set[tuple[str, int, int]]]:
    """Kiểm tra và chuẩn hóa force_drop: [[kind, packet_id]] hoặc [[kind, packet_id, copy_id]]."""
    if raw_force_drop is None:
        return set(), set()
    if not isinstance(raw_force_drop, Sequence) or isinstance(raw_force_drop, (str, bytes)):
        raise ValueError("force_drop must be a sequence of [kind, packet_id] entries")
    drop_logical: set[tuple[str, int]] = set()
    drop_copy: set[tuple[str, int, int]] = set()
    for item in raw_force_drop:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) not in (2, 3):
            raise ValueError(f"invalid force_drop entry: {item!r}")
        kind = str(item[0]).upper()
        if kind not in ("DATA", "PARITY"):
            raise ValueError(f"force_drop kind must be DATA or PARITY, got {kind!r}")
        pid = _nonnegative_int(item[1], "force_drop packet_id")
        if len(item) == 2:
            drop_logical.add((kind, pid))
        else:
            cid = _nonnegative_int(item[2], "force_drop copy_id")
            drop_copy.add((kind, pid, cid))
    return drop_logical, drop_copy


def _prepare(packets: Sequence[Mapping[str, Any]]) -> list[tuple[tuple[Any, ...], tuple[Any, ...], dict[str, Any]]]:
    """Kiểm tra và sao chép sâu toàn bộ packet trước lần rút thăm đầu tiên."""
    if not isinstance(packets, Sequence) or isinstance(packets, (str, bytes)):
        raise ValueError("packets must be a sequence of packet dictionaries")
    prepared = []
    source_keys = set()
    for position, packet in enumerate(packets):
        if not isinstance(packet, Mapping):
            raise ValueError(f"packet {position} must be a mapping")
        if not isinstance(packet.get("file_id"), str) or not packet["file_id"]:
            raise ValueError(f"packet {position}: file_id must be a nonempty string")
        packet_id = _nonnegative_int(packet.get("packet_id"), "packet_id")
        group_id = _nonnegative_int(packet.get("group_id", 0), "group_id")
        copy_id = _nonnegative_int(packet.get("copy_id", 0), "copy_id")
        kind = packet.get("kind", "DATA")
        if kind not in ("DATA", "PARITY"):
            raise ValueError("kind must be DATA or PARITY")
        sequence = packet.get("dna_sequence")
        if not isinstance(sequence, str) or not sequence or any(b not in BASES for b in sequence):
            raise ValueError("dna_sequence must be nonempty and contain only A/T/G/C")

        logical_key = (packet["file_id"], kind, group_id, packet_id)
        source_key = (*logical_key, copy_id)
        if source_key in source_keys:
            raise ValueError("duplicate source packet identity including copy_id")
        source_keys.add(source_key)

        source = deepcopy(dict(packet))
        source.update(kind=kind, group_id=group_id, copy_id=copy_id)
        prepared.append((logical_key, source_key, source))
    return prepared


def apply_noise(
    packets: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Trả về (reads, stats) và bảo toàn nguyên vẹn dữ liệu nguồn (không mutate `packets`)."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping")
    unknown = set(config) - CONFIG_KEYS
    if unknown:
        raise ValueError(f"unknown noise config keys: {sorted(unknown)}")

    dropout_rate = _rate(config, "dropout_rate")
    substitution_rate = _rate(config, "substitution_rate")
    read_count = config.get("read_count", 1)
    if isinstance(read_count, bool) or not isinstance(read_count, int) or read_count < 1:
        raise ValueError("read_count must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    dropout_scope = config.get("dropout_scope", "packet")
    if dropout_scope not in ("packet", "logical"):
        raise ValueError("dropout_scope must be 'packet' or 'logical'")

    force_logical, force_copy = _parse_force_drop(config.get("force_drop"))
    prepared = _prepare(packets)
    rng = random.Random(seed)

    logical_survived: dict[tuple[Any, ...], bool] = {lk: False for lk, _, _ in prepared}
    logical_dropout_draw: dict[tuple[Any, ...], bool] = {}

    if dropout_scope == "logical":
        for lk, _, _ in prepared:
            if lk not in logical_dropout_draw:
                logical_dropout_draw[lk] = rng.random() < dropout_rate

    reads: list[dict[str, Any]] = []
    source_dropped = 0
    bases_processed = 0
    bases_substituted = 0

    for logical_key, _source_key, source in prepared:
        kind = source["kind"]
        pid = source["packet_id"]
        cid = source["copy_id"]
        is_forced = ((kind, pid) in force_logical) or ((kind, pid, cid) in force_copy)
        if dropout_scope == "logical":
            is_random_drop = logical_dropout_draw[logical_key]
        else:
            is_random_drop = (rng.random() < dropout_rate) if dropout_rate > 0.0 else False

        if is_forced or is_random_drop:
            source_dropped += 1
            continue

        logical_survived[logical_key] = True
        for read_id in range(read_count):
            mutated = []
            for base in source["dna_sequence"]:
                bases_processed += 1
                if substitution_rate > 0.0 and rng.random() < substitution_rate:
                    mutated.append(rng.choice(ALTERNATIVES[base]))
                    bases_substituted += 1
                else:
                    mutated.append(base)
            read = deepcopy(source)
            # Giữ nguyên crc32 cũ — tuyệt đối không tính lại sau khi gây lỗi!
            read.update(dna_sequence="".join(mutated), read_id=read_id)
            reads.append(read)

    logical_total = len(logical_survived)
    logical_dropped = sum(1 for survived in logical_survived.values() if not survived)
    source_total = len(prepared)

    stats: dict[str, Any] = {
        "seed": seed,
        "dropout_rate": dropout_rate,
        "substitution_rate": substitution_rate,
        "read_count": read_count,
        "dropout_scope": dropout_scope,
        # Khóa chuẩn theo hợp đồng của Thái (OI-08)
        "n_packets_in": source_total,
        "n_dropped_packets": source_dropped,
        "n_substituted_bases": bases_substituted,
        "n_reads": len(reads),
        # Khóa chi tiết của Linh
        "logical_packets_total": logical_total,
        "logical_packets_dropped": logical_dropped,
        "source_packets_total": source_total,
        "source_packets_dropped": source_dropped,
        "reads_generated": len(reads),
        "bases_processed": bases_processed,
        "bases_substituted": bases_substituted,
        "observed_dropout_rate": (source_dropped / source_total) if source_total else None,
        "observed_logical_dropout_rate": (logical_dropped / logical_total) if logical_total else None,
        "observed_substitution_rate": (bases_substituted / bases_processed) if bases_processed else None,
    }
    return reads, stats
