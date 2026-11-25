"""Kiểm thử tích hợp toàn hệ thống (T01–T08 theo đúng Mục 9 Kế hoạch 14 ngày)
chạy trực tiếp qua `dnastore.orchestrator.run_simulation()` với 100% module THẬT (Thái + Trung + Linh)
trên bộ 3 tệp TXT mẫu tự tạo.

Chạy độc lập để cập nhật results/test_cases.csv:
    python -m tests.test_recovery
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import unittest

from dnastore.backends import load_backends
from dnastore.models import Reason, check_result_schema
from dnastore.orchestrator import run_simulation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
RESULTS_DIR = PROJECT_ROOT / "results"

SAMPLE_FILES = (
    ("sample_short.txt", "txt"),
    ("sample_medium.txt", "txt"),
    ("sample_long.txt", "txt"),
)


def load_txt_samples() -> list[tuple[str, str, bytes]]:
    return [(name, ftype, (SAMPLES_DIR / name).read_bytes()) for name, ftype in SAMPLE_FILES]


def run_standard_scenarios() -> list[dict]:
    """Chạy đầy đủ T01–T08 theo đúng đánh số Mục 9 kế hoạch trên cả 3 tệp TXT mẫu."""
    be = load_backends(use_mock=False)
    assert all(src == "real" for src in be.sources.values()), f"Expected all real backends, got {be.sources}"

    rows: list[dict] = []
    samples = load_txt_samples()

    for filename, file_type, data in samples:
        sha_in = hashlib.sha256(data).hexdigest()

        def record(case_id: str, scenario: str, cfg: dict, seed: int, expected_success: bool, expected_reason: str | None = None, check_repeat: bool = False):
            r = run_simulation((filename, data), cfg, seed=seed, backends=be)
            schema_errs = check_result_schema(r)
            repeatable = None
            if check_repeat:
                r2 = run_simulation((filename, data), cfg, seed=seed, backends=be)
                repeatable = (
                    r["success"] == r2["success"]
                    and r["reason"] == r2["reason"]
                    and r["n_packets_lost"] == r2["n_packets_lost"]
                    and r["n_substituted_bases"] == r2["n_substituted_bases"]
                    and r["sha256_match"] == r2["sha256_match"]
                )
            ok_bytes = (r["recovered_bytes"] == data) if expected_success else (r["recovered_bytes"] is None)
            ok_reason = True if expected_reason is None else (r["reason"] == expected_reason)
            passed = (
                (r["success"] == expected_success)
                and ok_bytes
                and ok_reason
                and (schema_errs == [])
                and (repeatable is None or repeatable)
            )
            rows.append({
                "case_id": case_id,
                "scenario": scenario,
                "filename": filename,
                "file_type": file_type,
                "input_bytes": len(data),
                "input_sha256": sha_in,
                "ecc_mode": cfg.get("ecc_mode", "XOR_PARITY"),
                "chunk_size": cfg.get("chunk_size", 32),
                "seed": seed,
                "dropout_rate": cfg.get("dropout_rate", 0.0),
                "substitution_rate": cfg.get("substitution_rate", 0.0),
                "read_count": cfg.get("read_count", 1),
                "n_packets": r["n_packets"],
                "n_packets_lost": r["n_packets_lost"],
                "n_substituted_bases": r["n_substituted_bases"],
                "n_nucleotides": r["n_nucleotides"],
                "expected_success": expected_success,
                "actual_success": r["success"],
                "sha256_match": r["sha256_match"],
                "reason": r["reason"],
                "elapsed_ms": round(r["elapsed_ms"], 3),
                "repeatable": "" if repeatable is None else repeatable,
                "passed": passed,
                "reason_detail": r["reason_detail"],
            })

        # T01: TXT tiếng Việt không lỗi
        record("T01", "TXT tiếng Việt không lỗi (round-trip)", {"ecc_mode": "NONE", "chunk_size": 32}, 42, True, Reason.OK_CLEAN)
        # T02: TXT có đầy đủ UTF-8 + ký tự đặc biệt với XOR_PARITY không lỗi
        record("T02", "TXT không lỗi chế độ XOR_PARITY", {"ecc_mode": "XOR_PARITY", "chunk_size": 32, "group_size": 4}, 42, True, Reason.OK_CLEAN)
        # T03: Không dự phòng (NONE), mất 1 packet -> báo thất bại
        record("T03", "NONE mất 1 DATA packet -> báo thất bại", {"ecc_mode": "NONE", "chunk_size": 32, "force_drop": [["DATA", 1]]}, 42, False, Reason.FAIL_UNRECOVERABLE)
        # T04: XOR_PARITY mất đúng 1 DATA chunk trong nhóm -> khôi phục thành công
        record("T04", "XOR_PARITY mất 1 DATA chunk (#1) -> khôi phục", {"ecc_mode": "XOR_PARITY", "chunk_size": 32, "group_size": 4, "force_drop": [["DATA", 1]]}, 42, True, Reason.OK_RECOVERED)
        # T05: XOR_PARITY mất 2 DATA chunk cùng nhóm -> báo thất bại trung thực
        record("T05", "XOR_PARITY mất 2 DATA chunk cùng nhóm (#0, #1) -> thất bại", {"ecc_mode": "XOR_PARITY", "chunk_size": 32, "group_size": 4, "force_drop": [["DATA", 0], ["DATA", 1]]}, 42, False, Reason.FAIL_UNRECOVERABLE)
        # T06: 3 bản đọc (REPLICATION_3X), có substitution -> consensus + CRC cứu
        record("T06", "REPLICATION_3X chống substitution 0.2%/base", {"ecc_mode": "REPLICATION_3X", "chunk_size": 32, "copies": 3, "substitution_rate": 0.002}, 42, True, Reason.OK_RECOVERED)
        # T07: Bản đọc rỗng (dropout 100%) -> báo lỗi có lý do
        record("T07", "Dropout 100% (không còn read) -> báo thất bại có lý do", {"ecc_mode": "XOR_PARITY", "chunk_size": 32, "dropout_rate": 1.0}, 42, False, Reason.FAIL_UNRECOVERABLE)
        # T08: Lặp lại cùng seed=2026 trên kênh hỗn hợp -> tái lập 100%
        record("T08", "Tái lập cùng seed=2026 (HYBRID, dropout 10%, sub 0.1%)", {"ecc_mode": "HYBRID", "chunk_size": 32, "group_size": 4, "copies": 3, "dropout_rate": 0.10, "substitution_rate": 0.001}, 2026, True, None, check_repeat=True)

    return rows


def write_test_cases_csv(path: Path | None = None) -> list[dict]:
    out_path = path or (RESULTS_DIR / "test_cases.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = run_standard_scenarios()
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


class IntegratedRecoveryTests(unittest.TestCase):
    def test_all_T01_to_T08_pass_on_three_txt_samples(self):
        rows = run_standard_scenarios()
        self.assertEqual(len(rows), 24)  # 8 ca x 3 file TXT
        failed = [r for r in rows if not r["passed"]]
        self.assertEqual(failed, [], f"Failed scenarios: {failed}")


if __name__ == "__main__":
    rows = write_test_cases_csv()
    passed = sum(1 for r in rows if r["passed"])
    print(f"Integrated T01-T08 scenarios: {passed}/{len(rows)} PASS -> {RESULTS_DIR / 'test_cases.csv'}")
    assert passed == len(rows)
