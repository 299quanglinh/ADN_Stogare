"""Kiểm thử bộ điều phối run_simulation (Thái) với cả backend MOCK và backend THẬT (Trung + Linh)."""
from pathlib import Path
import tempfile
import unittest

from dnastore.backends import Backends, load_backends
from dnastore.metadata_manager import sha256_hex
from dnastore.models import Reason, check_result_schema
from dnastore.orchestrator import run_simulation
from dnastore.storage_controller import StorageController

SAMPLE_MEDIUM = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_medium.txt"
TXT = SAMPLE_MEDIUM.read_bytes()
PNGLIKE = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 3 + b"\x00\xff\x00"
MOCK = load_backends(use_mock=True)
REAL = load_backends(use_mock=False)
BASE = {"chunk_size": 32, "ecc_mode": "XOR_PARITY", "group_size": 4}


def run_mock(data, **cfg):
    seed = cfg.pop("seed", 1)
    return run_simulation(("t.bin", data), {**BASE, **cfg}, seed=seed, backends=MOCK)


def run_real(data, **cfg):
    seed = cfg.pop("seed", 1)
    return run_simulation(("sample_medium.txt", data), {**BASE, **cfg}, seed=seed, backends=REAL)


class OrchestratorTests(unittest.TestCase):
    def test_default_backends_load_all_real_modules(self):
        be = load_backends(use_mock=False)
        self.assertEqual(
            be.sources,
            {"encode_file": "real", "apply_noise": "real", "decode_or_recover": "real"},
        )

    def test_T01_text_no_error(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(TXT)
                self.assertTrue(r["success"])
                self.assertEqual(r["recovered_bytes"], TXT)
                self.assertTrue(r["sha256_match"])
                self.assertEqual(r["reason"], Reason.OK_CLEAN)
                self.assertEqual(check_result_schema(r), [])

    def test_T02_binary_no_error(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(PNGLIKE)
                self.assertTrue(r["success"])
                self.assertEqual(r["recovered_bytes"], PNGLIKE)

    def test_T03_no_ecc_one_packet_lost_fails_honestly(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(TXT, ecc_mode="NONE", force_drop=[["DATA", 2]])
                self.assertFalse(r["success"])
                self.assertIsNone(r["recovered_bytes"])
                self.assertFalse(r["sha256_match"])
                self.assertEqual(r["reason"], Reason.FAIL_UNRECOVERABLE)
                self.assertTrue(r["reason_detail"])

    def test_T04_parity_recovers_one_lost_chunk(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(TXT, force_drop=[["DATA", 1]])
                self.assertTrue(r["success"])
                self.assertEqual(r["reason"], Reason.OK_RECOVERED)
                self.assertEqual(r["n_packets_lost"], 1)

    def test_T05_two_lost_in_same_group_fails(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(TXT, force_drop=[["DATA", 0], ["DATA", 1]])
                self.assertFalse(r["success"])
                self.assertEqual(r["reason"], Reason.FAIL_UNRECOVERABLE)

    def test_two_lost_in_different_groups_still_recovered(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                r = runner(TXT, force_drop=[["DATA", 0], ["DATA", 5]])
                self.assertTrue(r["success"])
                self.assertEqual(r["reason"], Reason.OK_RECOVERED)
                self.assertEqual(r["n_packets_lost"], 2)

    def test_T07_invalid_config_and_empty_file_report_reason(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                self.assertEqual(runner(TXT, chunk_size=0)["reason"], Reason.FAIL_INVALID_INPUT)
                self.assertEqual(runner(b"")["reason"], Reason.FAIL_INVALID_INPUT)
                self.assertEqual(runner(TXT, dropout_rate=1.5)["reason"], Reason.FAIL_INVALID_INPUT)
        self.assertEqual(
            run_simulation(("t", TXT), {"typo_key": 1}, backends=REAL)["reason"],
            Reason.FAIL_INVALID_INPUT,
        )

    def test_encoder_exception_is_reported_not_raised(self):
        r = run_real(TXT, ecc_mode="REED_SOLOMON")
        self.assertFalse(r["success"])
        self.assertEqual(r["reason"], Reason.FAIL_ENCODER_ERROR)

    def test_T08_same_seed_reproducible_different_seed_may_differ(self):
        for name, runner in (("mock", run_mock), ("real", run_real)):
            with self.subTest(backend=name):
                a = runner(TXT, dropout_rate=0.2, seed=7)
                b = runner(TXT, dropout_rate=0.2, seed=7)
                for k in ("success", "reason", "n_packets_lost", "sha256_match"):
                    self.assertEqual(a[k], b[k])
                lost = {runner(TXT, dropout_rate=0.2, seed=s)["n_packets_lost"] for s in range(10)}
                self.assertGreater(len(lost), 1)

    def test_real_crc32_detects_substitution_and_ecc_recovers(self):
        """Hồi quy lỗi tích hợp #1, #2, #5: CRC-32 sống qua StorageController & giúp sửa substitution."""
        r_rep = run_real(TXT, ecc_mode="REPLICATION_3X", copies=3, substitution_rate=0.002, seed=11)
        self.assertTrue(r_rep["success"])
        self.assertTrue(r_rep["sha256_match"])
        self.assertGreater(r_rep["n_substituted_bases"], 0)
        self.assertEqual(r_rep["reason"], Reason.OK_RECOVERED)

        r_hyb = run_real(TXT, ecc_mode="HYBRID", copies=3, dropout_rate=0.10, substitution_rate=0.001, seed=42)
        self.assertTrue(r_hyb["success"])
        self.assertTrue(r_hyb["sha256_match"])

    def test_undetected_substitution_on_mock_is_hash_mismatch_not_fake_success(self):
        r = run_mock(TXT, substitution_rate=0.05, seed=3)
        self.assertFalse(r["success"])
        self.assertEqual(r["reason"], Reason.FAIL_HASH_MISMATCH)
        self.assertIsNone(r["recovered_bytes"])

    def test_recovery_never_sees_original_or_hash_with_real_codec(self):
        """Hồi quy OI-10: bộ phục hồi thật của Trung/Linh không nhận expected_sha256 và vẫn khôi phục đúng."""
        seen = {}

        def spy(reads, metadata):
            seen["metadata"], seen["reads"] = metadata, reads
            return REAL.decode_or_recover(reads, metadata)

        be = Backends(REAL.encode_file, REAL.apply_noise, spy, dict(REAL.sources))
        r = run_simulation(("sample_medium.txt", TXT), {**BASE, "force_drop": [["DATA", 1]]}, seed=1, backends=be)
        self.assertTrue(r["success"])
        self.assertEqual(r["reason"], Reason.OK_RECOVERED)
        self.assertNotIn("expected_sha256", seen["metadata"])
        self.assertNotIn(sha256_hex(TXT), repr(seen["metadata"]))

    def test_noise_cannot_corrupt_stored_packets(self):
        store = StorageController()

        def evil_noise(packets, config, seed):
            for p in packets:
                p["dna_sequence"] = "A" * len(p["dna_sequence"])
            return REAL.apply_noise(packets, config, seed)

        be = Backends(REAL.encode_file, evil_noise, REAL.decode_or_recover, dict(REAL.sources))
        r = run_simulation(("sample_medium.txt", TXT), BASE, seed=1, backends=be, storage=store)
        fid = r["file_id"]
        self.assertNotEqual(set("".join(p["dna_sequence"] for p in store.read_packets(fid))), {"A"})

    def test_wrong_hash_from_encoder_is_flagged(self):
        def bad_encoder(data, file_id, chunk_size, ecc_mode="XOR_PARITY", ecc_params=None):
            p, m = REAL.encode_file(data, file_id, chunk_size, ecc_mode=ecc_mode, ecc_params=ecc_params)
            m["expected_sha256"] = "0" * 64
            return p, m

        be = Backends(bad_encoder, REAL.apply_noise, REAL.decode_or_recover, {})
        self.assertEqual(run_simulation(("t", TXT), BASE, backends=be)["reason"], Reason.FAIL_ENCODER_ERROR)

    def test_recovery_returning_wrong_bytes_is_never_success(self):
        be = Backends(REAL.encode_file, REAL.apply_noise, lambda reads, md: b"sai", {})
        r = run_simulation(("t", TXT), BASE, backends=be)
        self.assertFalse(r["success"])
        self.assertEqual(r["reason"], Reason.FAIL_HASH_MISMATCH)

    def test_recovery_returning_none_or_crashing(self):
        be = Backends(REAL.encode_file, REAL.apply_noise, lambda reads, md: None, {})
        self.assertEqual(run_simulation(("t", TXT), BASE, backends=be)["reason"], Reason.FAIL_UNRECOVERABLE)

        def boom(reads, md):
            raise RuntimeError("boom")

        be = Backends(REAL.encode_file, REAL.apply_noise, boom, {})
        self.assertEqual(run_simulation(("t", TXT), BASE, backends=be)["reason"], Reason.FAIL_INTERNAL_ERROR)

    def test_file_path_input_and_sample_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "mau.txt"
            p.write_bytes(TXT)
            r = run_simulation(str(p), BASE, backends=REAL)
            self.assertTrue(r["success"])
            self.assertEqual(r["filename"], "mau.txt")
            self.assertEqual(r["file_type"], "txt")

    def test_result_schema_for_every_outcome(self):
        outcomes = (
            run_real(TXT),
            run_real(TXT, force_drop=[["DATA", 1]]),
            run_real(TXT, ecc_mode="NONE", force_drop=[["DATA", 0]]),
            run_real(TXT, force_drop=[["DATA", 0], ["DATA", 1]]),
            run_real(b""),
        )
        for r in outcomes:
            self.assertEqual(check_result_schema(r), [], r["reason"])


if __name__ == "__main__":
    unittest.main()
