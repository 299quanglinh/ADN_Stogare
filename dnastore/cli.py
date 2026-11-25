"""Lệnh dòng lệnh chạy 3 ca demo dự phòng và chạy mô phỏng từng tệp.
    python -m dnastore.cli demo [--mock]
    python -m dnastore.cli run data/samples/sample_medium.txt --ecc XOR_PARITY --dropout 0.05 --seed 42
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .backends import load_backends
from .orchestrator import run_simulation

DEFAULT_SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_medium.txt"


def _line(title: str, r: dict) -> None:
    print(
        f"[{'OK ' if r['success'] else 'FAIL'}] {title:<38} reason={r['reason']:<20} "
        f"sha256_match={r['sha256_match']!s:<5} packets={r['n_packets']:<3} "
        f"lost={r['n_packets_lost']} time={r['elapsed_ms']:.2f}ms"
    )
    if r["reason_detail"]:
        print(f"       -> {r['reason_detail']}")


def demo(use_mock: bool) -> int:
    be = load_backends(use_mock=use_mock)
    print("=" * 92)
    print("DEMO HỆ THỐNG LƯU TRỮ DỮ LIỆU BẰNG ADN (THÁI – TRUNG – LINH)")
    print("backends:", be.sources)
    sample_input = str(DEFAULT_SAMPLE) if DEFAULT_SAMPLE.exists() else (
        "demo.txt",
        ("Lưu trữ dữ liệu bằng phân tử ADN: A, T, G, C. " * 6).encode("utf-8"),
    )
    print("sample  :", DEFAULT_SAMPLE.name if DEFAULT_SAMPLE.exists() else "in-memory demo.txt")
    print("-" * 92)
    base = {"chunk_size": 32, "ecc_mode": "XOR_PARITY", "group_size": 4}
    cases = [
        ("1. Không lỗi", {}),
        ("2. Mất 1 packet (XOR parity sửa được)", {"force_drop": [["DATA", 1]]}),
        ("3. Mất 2 packet cùng nhóm (thất bại)", {"force_drop": [["DATA", 0], ["DATA", 1]]}),
    ]
    for title, extra in cases:
        r = run_simulation(sample_input, {**base, **extra}, seed=42, backends=be)
        _line(title, r)
    print("=" * 92)
    return 0


def main(argv=None) -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="dnastore")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--mock", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--ecc", default="XOR_PARITY")
    r.add_argument("--chunk-size", type=int, default=32)
    r.add_argument("--group-size", type=int, default=4)
    r.add_argument("--copies", type=int, default=1)
    r.add_argument("--dropout", type=float, default=0.0)
    r.add_argument("--subst", type=float, default=0.0)
    r.add_argument("--read-count", type=int, default=1)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--mock", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "demo":
        return demo(a.mock or os.environ.get("DNASTORE_USE_MOCK") == "1")
    cfg = {
        "ecc_mode": a.ecc,
        "chunk_size": a.chunk_size,
        "group_size": a.group_size,
        "copies": a.copies,
        "dropout_rate": a.dropout,
        "substitution_rate": a.subst,
        "read_count": a.read_count,
    }
    res = run_simulation(a.file, cfg, a.seed, backends=load_backends(use_mock=a.mock or None))
    res["recovered_bytes"] = None if res["recovered_bytes"] is None else f"<{len(res['recovered_bytes'])} bytes>"
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
