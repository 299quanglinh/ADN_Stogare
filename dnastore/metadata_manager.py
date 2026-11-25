"""Quản lý metadata của tệp: kiểm tra, lưu/đọc tệp riêng, và bản 'an toàn cho phục hồi'.
Tác giả kiến trúc: Thái.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .models import METADATA_REQUIRED

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_metadata(md: dict[str, Any]) -> dict[str, Any]:
    """Kiểm tra các trường bắt buộc; trả về bản sao sâu (giữ nguyên trường mở rộng như ecc_params, group_size)."""
    if not isinstance(md, dict):
        raise ValidationError(f"metadata phải là dict, nhận {type(md).__name__}")
    missing = [f for f in METADATA_REQUIRED if f not in md]
    if missing:
        raise ValidationError(f"metadata thiếu trường: {missing}")

    def is_int(x: Any) -> bool:
        return isinstance(x, int) and not isinstance(x, bool)

    if not isinstance(md["file_id"], str) or not md["file_id"]:
        raise ValidationError("metadata.file_id phải là chuỗi không rỗng")
    if not isinstance(md["filename"], str) or not md["filename"]:
        raise ValidationError("metadata.filename phải là chuỗi không rỗng")
    if not is_int(md["file_size"]) or md["file_size"] < 1:
        raise ValidationError("metadata.file_size phải là số nguyên >= 1")
    if not is_int(md["chunk_size"]) or md["chunk_size"] < 1:
        raise ValidationError("metadata.chunk_size phải là số nguyên >= 1")
    if not is_int(md["total_packets"]) or md["total_packets"] < 1:
        raise ValidationError("metadata.total_packets phải là số nguyên >= 1")
    if not isinstance(md["expected_sha256"], str) or not _SHA_RE.match(md["expected_sha256"]):
        raise ValidationError("metadata.expected_sha256 phải là 64 ký tự hex thường")
    if not isinstance(md["ecc_mode"], str) or not md["ecc_mode"]:
        raise ValidationError("metadata.ecc_mode phải là chuỗi không rỗng")
    return copy.deepcopy(md)


def recovery_view(md: dict[str, Any]) -> dict[str, Any]:
    """Bản metadata đưa cho bộ phục hồi (chốt OI-10): BỎ expected_sha256
    để đảm bảo bộ phục hồi không bao giờ dùng hash gốc làm dữ liệu suy đoán.
    """
    view = copy.deepcopy(md)
    view.pop("expected_sha256", None)
    return view


def save_metadata(path: str | Path, md: dict[str, Any]) -> None:
    """Ghi nguyên tử (tệp tạm + os.replace) để không bao giờ để lại tệp ghi dở."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(md, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_metadata(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return validate_metadata(json.load(fh))
