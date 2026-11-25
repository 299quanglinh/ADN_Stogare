"""Kiểm thử sản phẩm giao diện, cấu hình RunConfig, Preset Demo & bàn giao của Dũng.

Chạy hoàn toàn bằng thư viện chuẩn Python (tương thích cả `unittest` lẫn `pytest`),
không làm hỏng bộ 48 test lõi trên môi trường sạch chưa cài Streamlit.
Nếu môi trường có cài Streamlit, tự động chạy thêm `AppTest` kiểm tra render `app.py`.
"""
from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path
import py_compile
import unittest

from dnastore import Reason, StorageController, compute_gc_content, encode_file, load_backends, run_simulation
from dnastore.models import RunConfig, check_result_schema

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"
SAMPLES_DIR = ROOT / "data" / "samples"
RESULTS_DIR = ROOT / "results"
DOCS_DIR = ROOT / "docs"


class DungUIAndDeliverablesTests(unittest.TestCase):
    def test_01_app_py_exists_compiles_and_uses_public_dnastore_api(self):
        self.assertTrue(APP_PATH.exists(), "Thiếu tệp app.py ở gốc repository")
        py_compile.compile(str(APP_PATH), doraise=True)
        src = APP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)

        # Kiểm tra không còn hard-code tham số deprecated use_column_width
        kw_names = {kw.arg for n in ast.walk(tree) if isinstance(n, ast.Call) for kw in n.keywords}
        self.assertNotIn("use_column_width", kw_names)

        # Xác nhận gọi đúng API công khai và có đủ chức năng yêu cầu trong CONGVIECCANLAM.md
        for must_have in (
            "run_simulation",
            "encode_file",
            "StorageController",
            "st.file_uploader",
            "st.download_button",
            "session_state",
            "DEMO_PRESETS",
            "chart_dropout_recovery.png",
            "chart_substitution_scaling.png",
            "benchmark_summary.csv",
        ):
            self.assertIn(must_have, src, f"app.py thiếu thành phần bắt buộc: {must_have}")

    def test_02_runconfig_presets_and_copies_rules_match_api_v1_0(self):
        # Xác minh không truyền khóa lạ (như dropout_scope) và tự set copies=3 cho REPLICATION_3X/HYBRID
        for mode, expected_copies in (
            ("NONE", 1),
            ("XOR_PARITY", 1),
            ("REPLICATION_3X", 3),
            ("HYBRID", 3),
        ):
            cfg = {
                "chunk_size": 32,
                "ecc_mode": mode,
                "group_size": 4,
                "copies": expected_copies,
                "dropout_rate": 0.05,
                "substitution_rate": 0.001,
                "read_count": 1,
            }
            parsed = RunConfig.from_dict(cfg)
            self.assertEqual(parsed.ecc_mode, mode)
            self.assertEqual(parsed.copies, expected_copies)

    def test_03_three_demo_presets_on_real_backends_sample_medium(self):
        be = load_backends(use_mock=False)
        self.assertTrue(all(v == "real" for v in be.sources.values()))
        med_path = SAMPLES_DIR / "sample_medium.txt"
        raw = med_path.read_bytes()

        # Preset 1: Không lỗi -> OK_CLEAN
        r1 = run_simulation(
            (med_path.name, raw),
            {"chunk_size": 32, "ecc_mode": "XOR_PARITY", "group_size": 4, "copies": 1, "dropout_rate": 0.0, "substitution_rate": 0.0, "read_count": 1},
            seed=42,
            storage=StorageController(),
        )
        self.assertTrue(r1["success"] and r1["sha256_match"])
        self.assertEqual(r1["reason"], Reason.OK_CLEAN)
        self.assertEqual(r1["recovered_bytes"], raw)
        self.assertEqual(check_result_schema(r1), [])

        # Preset 2: Mất 1 packet DATA #1 -> OK_RECOVERED
        r2 = run_simulation(
            (med_path.name, raw),
            {"chunk_size": 32, "ecc_mode": "XOR_PARITY", "group_size": 4, "copies": 1, "dropout_rate": 0.0, "substitution_rate": 0.0, "read_count": 1, "force_drop": [["DATA", 1]]},
            seed=42,
            storage=StorageController(),
        )
        self.assertTrue(r2["success"] and r2["sha256_match"])
        self.assertEqual(r2["reason"], Reason.OK_RECOVERED)
        self.assertEqual(r2["n_packets_lost"], 1)
        self.assertEqual(r2["recovered_bytes"], raw)

        # Preset 3: Mất 2 packet cùng nhóm DATA #0 & #1 -> FAIL_UNRECOVERABLE
        r3 = run_simulation(
            (med_path.name, raw),
            {"chunk_size": 32, "ecc_mode": "XOR_PARITY", "group_size": 4, "copies": 1, "dropout_rate": 0.0, "substitution_rate": 0.0, "read_count": 1, "force_drop": [["DATA", 0], ["DATA", 1]]},
            seed=42,
            storage=StorageController(),
        )
        self.assertFalse(r3["success"])
        self.assertFalse(r3["sha256_match"])
        self.assertIsNone(r3["recovered_bytes"])
        self.assertEqual(r3["recovered_size"], 0)
        self.assertEqual(r3["reason"], Reason.FAIL_UNRECOVERABLE)

    def test_04_encode_file_preview_all_samples_and_crc32_present(self):
        for fname in ("sample_short.txt", "sample_medium.txt", "sample_long.txt"):
            raw = (SAMPLES_DIR / fname).read_bytes()
            packets, meta = encode_file(
                raw,
                file_id="PREVIEW",
                chunk_size=32,
                filename=fname,
                ecc_mode="XOR_PARITY",
                ecc_params={"group_size": 4, "copies": 1},
            )
            self.assertGreater(len(packets), meta["total_packets"])
            self.assertTrue(all(set(p["dna_sequence"]).issubset({"A", "T", "G", "C"}) for p in packets))
            self.assertTrue(all("crc32" in p and len(p["crc32"]) == 8 for p in packets))
            data_seqs = [p["dna_sequence"] for p in packets if p["kind"] == "DATA" and p.get("copy_id", 0) == 0]
            gc = compute_gc_content("".join(data_seqs))
            self.assertTrue(0.0 <= gc <= 100.0)

    def test_05_binary_upload_tuple_roundtrip_for_ui_flow(self):
        png_like = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        res = run_simulation(
            ("demo_upload.png", png_like),
            {"chunk_size": 32, "ecc_mode": "HYBRID", "group_size": 4, "copies": 3, "dropout_rate": 0.05, "substitution_rate": 0.001, "read_count": 1},
            seed=42,
            storage=StorageController(),
        )
        self.assertTrue(res["success"] and res["sha256_match"])
        self.assertEqual(res["recovered_bytes"], png_like)
        self.assertEqual(res["file_type"], "png")

    def test_06_user_guide_and_wireframe_and_part4_report_exist(self):
        ug = DOCS_DIR / "user_guide.md"
        wf = DOCS_DIR / "ui_wireframe.png"
        p4 = DOCS_DIR / "bao_cao_phan_4_dung.md"
        self.assertTrue(ug.exists() and ug.stat().st_size > 1000)
        self.assertTrue(wf.exists() and wf.stat().st_size > 20_000)
        self.assertTrue(p4.exists() and p4.stat().st_size > 2000)
        ug_txt = ug.read_text(encoding="utf-8")
        self.assertIn("streamlit run app.py", ug_txt)
        self.assertIn("python -m dnastore.cli demo", ug_txt)

    def test_07_real_results_csv_and_three_charts_exist(self):
        for fname in (
            "benchmark_results.csv",
            "benchmark_summary.csv",
            "experiment_conditions.json",
            "test_cases.csv",
            "chart_dropout_recovery.png",
            "chart_substitution_scaling.png",
            "chart_overhead_runtime.png",
        ):
            p = RESULTS_DIR / fname
            self.assertTrue(p.exists() and p.stat().st_size > 0, f"Thiếu hoặc rỗng: results/{fname}")

        cond = json.loads((RESULTS_DIR / "experiment_conditions.json").read_text(encoding="utf-8"))
        self.assertEqual(cond["total_runs"], 2160)
        self.assertTrue(all(v == "real" for v in cond["backends"].values()))

        with (RESULTS_DIR / "benchmark_summary.csv").open("r", encoding="utf-8") as fh:
            sum_rows = list(csv.DictReader(fh))
        self.assertEqual(len(sum_rows), 72)

    def test_08_optional_streamlit_apptest_smoke(self):
        if importlib.util.find_spec("streamlit") is None or importlib.util.find_spec("pandas") is None:
            self.skipTest("Môi trường kiểm thử không cài Streamlit; bỏ qua AppTest.")
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=20)
        self.assertFalse(at.exception, f"AppTest báo lỗi khi khởi tạo app.py: {at.exception}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
