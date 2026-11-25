"""Storage Controller: lưu/đọc packet + metadata theo file_id.

Tác giả kiến trúc: Thái.
Bản tích hợp đã sửa lỗi tích hợp #1: giữ nguyên các trường mở rộng hợp lệ của packet
(như `crc32`, `covered_packet_ids` từ encoder của Trung) thay vì cắt mất khi lưu kho.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from .errors import FileAlreadyInStore, FileNotInStore, ValidationError
from .metadata_manager import load_metadata, save_metadata, validate_metadata
from .models import DNAPacket, validate_packet_extra_fields

_ID_RE = re.compile(r"^F(\d+)$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _atomic_write_json(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class StorageController:
    def __init__(self, root: str | Path | None = None):
        self._root = Path(root) if root is not None else None
        self._mem: dict[str, dict[str, Any]] = {}
        self._reserved: set[str] = set()
        self._lock = threading.RLock()
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)

    # ---------- file ID ----------
    def new_file_id(self) -> str:
        """Cấp F01, F02, ... không trùng (kể cả ID đã cấp nhưng chưa lưu)."""
        with self._lock:
            used = set(self._mem) | self._reserved | set(self._ids_on_disk())
            n = max((int(m.group(1)) for i in used if (m := _ID_RE.match(i))), default=0) + 1
            fid = f"F{n:02d}"
            self._reserved.add(fid)
            return fid

    # ---------- ghi ----------
    def store_packets(
        self,
        file_id: str,
        packets: list[Any],
        metadata: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Kiểm tra toàn bộ V01-V10 rồi lưu. Trả về tóm tắt để orchestrator ghi log/benchmark."""
        self._check_id(file_id)
        md = validate_metadata(metadata)
        if md["file_id"] != file_id:
            raise ValidationError(f"metadata.file_id={md['file_id']!r} khác file_id={file_id!r}")
        if not isinstance(packets, (list, tuple)) or not packets:
            raise ValidationError("packets phải là danh sách không rỗng")

        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for i, p in enumerate(packets):
            d = p.to_dict() if isinstance(p, DNAPacket) else p
            try:
                pk = DNAPacket.from_dict(d).validate()
                validate_packet_extra_fields(d)
            except ValidationError as exc:
                raise ValidationError(f"packet #{i}: {exc}") from exc
            if pk.file_id != file_id:
                raise ValidationError(f"packet #{i}: file_id={pk.file_id!r} khác {file_id!r}")
            if pk.total_packets != md["total_packets"]:
                raise ValidationError(
                    f"packet #{i}: total_packets={pk.total_packets} khác metadata ({md['total_packets']})"
                )
            if pk.kind == "DATA" and pk.packet_id >= pk.total_packets:
                raise ValidationError(f"packet #{i}: packet_id={pk.packet_id} ngoài [0,{pk.total_packets})")
            key = (pk.kind, pk.packet_id, pk.copy_id)
            if key in seen:
                raise ValidationError(f"packet #{i}: trùng (kind, packet_id, copy_id)={key}")
            seen.add(key)
            # Sửa lỗi tích hợp #1: giữ bản sao sâu gồm cả trường mở rộng (crc32, covered_packet_ids)
            stored_row = copy.deepcopy(d)
            stored_row.update(pk.to_dict())
            rows.append(stored_row)

        with self._lock:
            if self.exists(file_id) and not overwrite:
                raise FileAlreadyInStore(f"file_id {file_id!r} đã tồn tại (dùng overwrite=True để ghi đè)")
            if self._root is not None:
                d_path = self._root / file_id
                d_path.mkdir(parents=True, exist_ok=True)
                meta_path = d_path / "metadata.json"
                if meta_path.exists():
                    meta_path.unlink()
                _atomic_write_json(d_path / "packets.json", rows)
                save_metadata(meta_path, md)
            self._mem[file_id] = {"metadata": md, "packets": rows}
            self._reserved.discard(file_id)
        return self._summary(file_id, rows)

    # ---------- đọc ----------
    def read_packets(self, file_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        rec = self._record(file_id)
        rows = rec["packets"] if kind is None else [r for r in rec["packets"] if r["kind"] == kind]
        return copy.deepcopy(rows)

    def read_metadata(self, file_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._record(file_id)["metadata"])

    def exists(self, file_id: str) -> bool:
        with self._lock:
            if file_id in self._mem:
                return True
            return (
                self._root is not None
                and _SAFE_ID_RE.match(file_id or "") is not None
                and (self._root / file_id / "metadata.json").exists()
            )

    def list_files(self) -> list[dict[str, Any]]:
        out = []
        for fid in sorted(set(self._mem) | set(self._ids_on_disk())):
            md = self._record(fid)["metadata"]
            out.append({k: md[k] for k in ("file_id", "filename", "file_size", "total_packets", "ecc_mode")})
        return out

    def storage_stats(self, file_id: str) -> dict[str, Any]:
        rec = self._record(file_id)
        return self._summary(file_id, rec["packets"])

    def delete_file(self, file_id: str) -> None:
        with self._lock:
            if not self.exists(file_id):
                raise FileNotInStore(f"không có file_id {file_id!r}")
            self._mem.pop(file_id, None)
            if self._root is not None:
                d_path = self._root / file_id
                for child in d_path.glob("*"):
                    child.unlink()
                d_path.rmdir()

    # ---------- nội bộ ----------
    def _check_id(self, file_id: Any) -> None:
        if not isinstance(file_id, str) or not _SAFE_ID_RE.match(file_id):
            raise ValidationError(f"file_id không hợp lệ: {file_id!r} (chỉ chữ/số/_/-, tối đa 64 ký tự)")

    def _ids_on_disk(self) -> list[str]:
        if self._root is None:
            return []
        return [p.name for p in self._root.iterdir() if p.is_dir() and (p / "metadata.json").exists()]

    def _record(self, file_id: str) -> dict[str, Any]:
        with self._lock:
            if file_id in self._mem:
                return self._mem[file_id]
            if self._root is not None and _SAFE_ID_RE.match(file_id or "") and self.exists(file_id):
                d_path = self._root / file_id
                with open(d_path / "packets.json", encoding="utf-8") as fh:
                    rows = json.load(fh)
                rec = {"metadata": load_metadata(d_path / "metadata.json"), "packets": rows}
                self._mem[file_id] = rec
                return rec
        raise FileNotInStore(f"không có file_id {file_id!r}")

    @staticmethod
    def _summary(file_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        data = [r for r in rows if r["kind"] == "DATA"]
        parity = [r for r in rows if r["kind"] == "PARITY"]
        return {
            "file_id": file_id,
            "n_packets": len(rows),
            "n_data": len(data),
            "n_parity": len(parity),
            "n_nucleotides": sum(len(r["dna_sequence"]) for r in rows),
        }
