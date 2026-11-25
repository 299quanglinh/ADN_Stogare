"""run_simulation: bộ điều phối toàn luồng (Thái).

Luồng: [tệp] -> encode (Trung) -> lưu kho (Thái) -> đọc kho -> kênh lỗi (Linh)
       -> phục hồi (Linh + Trung, không có hash) -> đối chiếu byte & SHA-256 (Thái) -> kết quả chuẩn hóa.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import time
from typing import Any

from .backends import Backends, load_backends
from .errors import DNAStoreError, RecoveryFailure, ValidationError
from .metadata_manager import recovery_view, sha256_hex, validate_metadata
from .models import Reason, RunConfig
from .storage_controller import StorageController

# Chốt OI-10: KHÔNG đưa expected_sha256 cho bộ phục hồi; orchestrator tự xác minh ở Bước 6.
PASS_HASH_TO_RECOVERY = False


def _load_input(file: Any, filename: str | None) -> tuple[bytes, str]:
    """Chấp nhận bytes | đường dẫn | (tên, bytes) (chốt OI-15)."""
    if isinstance(file, tuple) and len(file) == 2:
        filename, file = file
    if isinstance(file, (bytes, bytearray)):
        return bytes(file), filename or "unnamed.bin"
    if isinstance(file, (str, Path)):
        p = Path(file)
        try:
            return p.read_bytes(), filename or p.name
        except OSError as exc:
            raise ValidationError(f"không đọc được tệp {p}: {exc}") from exc
    raise ValidationError(f"kiểu đầu vào tệp không hỗ trợ: {type(file).__name__}")


def _call_encoder(encode_file, data: bytes, file_id: str, cfg: RunConfig, filename: str):
    """Adapter gọi encode_file tương thích cả bản mock lẫn bản thật của Trung (OI-03)."""
    params = inspect.signature(encode_file).parameters
    extra: dict[str, Any] = {}
    if "filename" in params:
        extra["filename"] = filename
    if "ecc_mode" in params:
        extra["ecc_mode"] = cfg.ecc_mode
    if "ecc_params" in params:
        extra["ecc_params"] = cfg.ecc_params()
    elif "group_size" in params:
        extra["group_size"] = cfg.group_size
        if "replication_factor" in params:
            extra["replication_factor"] = cfg.copies
    return encode_file(data, file_id, cfg.chunk_size, **extra)


def _split_noise_output(out: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], dict(out[1] or {})
    return out, {}


def run_simulation(
    file: Any,
    config: dict[str, Any] | None = None,
    seed: int = 0,
    *,
    filename: str | None = None,
    storage: StorageController | None = None,
    backends: Backends | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    res: dict[str, Any] = {
        "success": False,
        "reason": Reason.FAIL_INTERNAL_ERROR,
        "recovered_bytes": None,
        "original_size": 0,
        "recovered_size": 0,
        "sha256_match": False,
        "dropout_rate": 0.0,
        "substitution_rate": 0.0,
        "seed": seed if isinstance(seed, int) and not isinstance(seed, bool) else -1,
        "elapsed_ms": 0.0,
        # --- trường mở rộng (OI-12) ---
        "file_id": None,
        "filename": None,
        "file_type": None,
        "ecc_mode": None,
        "chunk_size": None,
        "n_packets": 0,
        "n_packets_lost": None,
        "n_substituted_bases": None,
        "n_nucleotides": 0,
        "reason_detail": "",
        "backends": {},
    }
    try:
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValidationError(f"seed phải là số nguyên, nhận {seed!r}")
        cfg = RunConfig.from_dict(config)
        res.update(
            dropout_rate=cfg.dropout_rate,
            substitution_rate=cfg.substitution_rate,
            ecc_mode=cfg.ecc_mode,
            chunk_size=cfg.chunk_size,
        )
        data, name = _load_input(file, filename)
        if not data:
            raise ValidationError("tệp rỗng")
        res.update(
            original_size=len(data),
            filename=name,
            file_type=Path(name).suffix.lower().lstrip(".") or "bin",
        )
        be = backends or load_backends()
        res["backends"] = dict(be.sources)
        store = storage if storage is not None else StorageController()
        original_hash = sha256_hex(data)

        # 1) ENCODE (Trung)
        file_id = store.new_file_id()
        res["file_id"] = file_id
        try:
            packets, metadata = _call_encoder(be.encode_file, data, file_id, cfg, name)
        except DNAStoreError:
            raise
        except Exception as exc:
            raise DNAStoreError(f"encoder lỗi: {exc}", Reason.FAIL_ENCODER_ERROR) from exc
        metadata = dict(metadata)
        metadata.setdefault("filename", name)
        metadata["filename"] = metadata["filename"] or name
        md = validate_metadata(metadata)
        if md["expected_sha256"] != original_hash:
            raise DNAStoreError(
                "expected_sha256 trong metadata khác SHA-256 của tệp gốc",
                Reason.FAIL_ENCODER_ERROR,
            )

        # 2) LƯU KHO & 3) ĐỌC BẢN SAO SÂU TỪ KHO (Thái)
        summary = store.store_packets(file_id, packets, md)
        res.update(n_packets=summary["n_packets"], n_nucleotides=summary["n_nucleotides"])
        stored = store.read_packets(file_id)
        stored_md = store.read_metadata(file_id)

        # 4) KÊNH NHIỄU (Linh)
        try:
            reads, nstats = _split_noise_output(be.apply_noise(stored, cfg.noise_config(), seed))
        except Exception as exc:
            raise DNAStoreError(f"kênh lỗi gặp sự cố: {exc}", Reason.FAIL_NOISE_ERROR) from exc
        res["n_packets_lost"] = nstats.get("n_dropped_packets", nstats.get("source_packets_dropped"))
        res["n_substituted_bases"] = nstats.get("n_substituted_bases", nstats.get("bases_substituted"))

        # 5) PHỤC HỒI (Linh + Trung, không truyền tệp gốc & ẩn expected_sha256)
        md_for_recovery = stored_md if PASS_HASH_TO_RECOVERY else recovery_view(stored_md)
        try:
            out = be.decode_or_recover(reads, md_for_recovery)
        except RecoveryFailure as exc:
            res.update(reason=exc.code, reason_detail=str(exc))
            return res
        if out is None:
            res.update(reason=Reason.FAIL_UNRECOVERABLE, reason_detail="bộ phục hồi trả về None")
            return res
        if not isinstance(out, (bytes, bytearray)):
            raise DNAStoreError(
                f"decode_or_recover trả kiểu {type(out).__name__}, cần bytes",
                Reason.FAIL_INTERNAL_ERROR,
            )
        out = bytes(out)

        # 6) ĐỐI CHIẾU CUỐI CÙNG (byte + SHA-256) — nơi DUY NHẤT dùng tệp gốc
        if out == data and sha256_hex(out) == original_hash:
            clean = (res["n_packets_lost"] in (0, None)) and (res["n_substituted_bases"] in (0, None))
            res.update(
                success=True,
                recovered_bytes=out,
                recovered_size=len(out),
                sha256_match=True,
                reason=Reason.OK_CLEAN if clean else Reason.OK_RECOVERED,
            )
        else:
            res.update(
                reason=Reason.FAIL_HASH_MISMATCH,
                reason_detail=f"khôi phục {len(out)} byte nhưng khác tệp gốc ({len(data)} byte)",
            )
        return res
    except DNAStoreError as exc:
        res.update(success=False, recovered_bytes=None, reason=exc.code, reason_detail=str(exc))
        return res
    except Exception as exc:
        res.update(
            success=False,
            recovered_bytes=None,
            reason=Reason.FAIL_INTERNAL_ERROR,
            reason_detail=f"{type(exc).__name__}: {exc}",
        )
        return res
    finally:
        res["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
