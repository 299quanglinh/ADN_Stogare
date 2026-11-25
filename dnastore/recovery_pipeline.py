"""recovery_pipeline.py
Lớp nối (adapter) pipeline khôi phục của Linh gọi trực tiếp `ecc_codec.decode_or_recover` của Trung,
đồng bộ hoàn toàn với hợp đồng API của Thái (chốt OI-09 & OI-10).

- `decode_or_recover(reads, metadata) -> bytes`:
    Chuẩn tích hợp cho `orchestrator.run_simulation()` của Thái.
    Trả về `bytes` khi khôi phục được; ném `ValidationError` nếu metadata sai
    hoặc `RecoveryFailure` nếu vượt quá khả năng sửa lỗi.
- `decode_or_recover_report(reads, metadata, ...) -> dict`:
    Hàm chi tiết trả về dict đầy đủ thống kê (consensus/CRC fallback/XOR parity/elapsed_ms)
    phục vụ gỡ lỗi và báo cáo chi tiết của Linh.

Nguyên tắc học thuật: Cả hai hàm chỉ nhận `reads` sau nhiễu và `metadata` (không cần `expected_sha256`),
tuyệt đối không nhận dữ liệu gốc hay packet gốc.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .ecc_codec import decode_or_recover as _decode_or_recover_trung
from .errors import RecoveryFailure, ValidationError
from .models import Reason


def _validate_rate(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} phải là số trong [0, 1].")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} phải hữu hạn và nằm trong [0, 1].")
    return float(value)


def decode_or_recover(reads: List[Dict[str, Any]], metadata: Dict[str, Any]) -> bytes:
    """API chuẩn tích hợp với `dnastore/orchestrator.py` của Thái (OI-09 & OI-10).

    Chỉ nhận 2 tham số `(reads, metadata)` — không nhận tệp gốc.
    Trả `bytes` khi khôi phục hoàn tất; ném `ValidationError` / `RecoveryFailure` khi thất bại.
    """
    result = _decode_or_recover_trung(reads, metadata)
    if result.get("success") and isinstance(result.get("recovered_bytes"), (bytes, bytearray)):
        return bytes(result["recovered_bytes"])

    reason = str(result.get("reason", "Không thể khôi phục dữ liệu."))
    err_type = result.get("error_type")
    if err_type == "INVALID_METADATA":
        raise ValidationError(reason)
    if err_type == "HASH_MISMATCH":
        raise RecoveryFailure(reason, code=Reason.FAIL_HASH_MISMATCH)
    raise RecoveryFailure(reason, code=Reason.FAIL_UNRECOVERABLE)


def decode_or_recover_report(
    reads: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    *,
    dropout_rate: float = 0.0,
    substitution_rate: float = 0.0,
    seed: int = 0,
) -> Dict[str, Any]:
    """Hàm mở rộng trả dict chi tiết của codec Trung kèm tham số nhiễu."""
    dropout_rate = _validate_rate(dropout_rate, "dropout_rate")
    substitution_rate = _validate_rate(substitution_rate, "substitution_rate")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed phải là số nguyên.")

    result = dict(_decode_or_recover_trung(reads, metadata))
    result["dropout_rate"] = dropout_rate
    result["substitution_rate"] = substitution_rate
    result["seed"] = seed
    return result
