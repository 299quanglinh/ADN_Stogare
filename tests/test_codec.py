"""Kiểm thử lõi mã hóa/giải mã & ECC của Trung trong gói tích hợp dnastore."""
import copy
import inspect
from pathlib import Path
import unittest

from dnastore.dna_decoder import decode_file, dna_to_bytes
from dnastore.dna_encoder import bytes_to_dna, encode_file
from dnastore.ecc_codec import decode_or_recover as ecc_decode_or_recover
from dnastore.metadata_manager import recovery_view

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
TXT_SHORT = (SAMPLES_DIR / "sample_short.txt").read_bytes()
TXT_MEDIUM = (SAMPLES_DIR / "sample_medium.txt").read_bytes()


class CodecTests(unittest.TestCase):
    def test_mapping_2bit_exact_all_256_bytes(self):
        self.assertEqual(bytes_to_dna(bytes([0x00, 0x55, 0xAA, 0xFF, 0x1B])), "AAAATTTTGGGGCCCCATGC")
        all_bytes = bytes(range(256))
        dna = bytes_to_dna(all_bytes)
        self.assertLessEqual(set(dna), {"A", "T", "G", "C"})
        self.assertEqual(dna_to_bytes(dna), all_bytes)

    def test_reject_invalid_dna_letters_and_length(self):
        for bad in ("ATGX", "ATG?", "ATG", "1234"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dna_to_bytes(bad)

    def test_encode_decode_roundtrip_txt_short_and_medium(self):
        for raw, name in [(TXT_SHORT, "sample_short.txt"), (TXT_MEDIUM, "sample_medium.txt")]:
            pkts, meta = encode_file(raw, "F01", chunk_size=32, filename=name, ecc_mode="NONE")
            rec, sha_ok, reason = decode_file(pkts, meta)
            self.assertEqual(rec, raw)
            self.assertTrue(sha_ok)
            self.assertEqual(reason, "OK")

    def test_encode_accepts_ecc_params_from_orchestrator(self):
        pkts, meta = encode_file(
            TXT_SHORT,
            "F01",
            chunk_size=32,
            filename="sample_short.txt",
            ecc_mode="HYBRID",
            ecc_params={"group_size": 2, "copies": 3},
        )
        self.assertEqual(meta["group_size"], 2)
        self.assertEqual(meta["replication_factor"], 3)
        self.assertEqual(meta["ecc_params"], {"group_size": 2, "copies": 3})
        self.assertEqual(len(pkts), (meta["total_packets"] + 3) * 3)

    def test_xor_single_loss_each_position_and_last_chunk(self):
        pkts, meta = encode_file(
            TXT_SHORT, "F01", chunk_size=32, filename="sample_short.txt", ecc_mode="XOR_PARITY", group_size=4
        )
        for drop_pid in (0, 1, 2, 3, meta["total_packets"] - 1):
            surviving = [p for p in pkts if p["packet_id"] != drop_pid]
            res = ecc_decode_or_recover(surviving, meta)
            self.assertTrue(res["success"])
            self.assertEqual(res["recovered_bytes"], TXT_SHORT)
            self.assertTrue(res["sha256_match"])

    def test_xor_data_and_parity_lost_same_group_fails(self):
        pkts, meta = encode_file(
            TXT_SHORT, "F01", chunk_size=32, filename="sample_short.txt", ecc_mode="XOR_PARITY", group_size=4
        )
        parity_g0 = meta["total_packets"]
        surviving = [p for p in pkts if p["packet_id"] not in (0, parity_g0)]
        res = ecc_decode_or_recover(surviving, meta)
        self.assertFalse(res["success"])
        self.assertIsNone(res["recovered_bytes"])

    def test_two_reads_tie_resolved_by_crc_fallback(self):
        pkts, meta = encode_file(
            TXT_SHORT, "F01", chunk_size=32, ecc_mode="REPLICATION_3X", replication_factor=3
        )
        reads = [copy.deepcopy(p) for p in pkts if not (p["packet_id"] == 0 and p["copy_id"] == 2)]
        for r in reads:
            if r["packet_id"] == 0 and r["copy_id"] == 0:
                r["dna_sequence"] = ("T" if r["dna_sequence"][0] != "T" else "A") + r["dna_sequence"][1:]
        res = ecc_decode_or_recover(reads, meta)
        self.assertTrue(res["success"])
        self.assertEqual(res["recovered_bytes"], TXT_SHORT)
        self.assertIn(0, res["stats"]["crc_fallback_fixes"])

    def test_ecc_works_without_expected_sha256_for_oi10_recovery_view(self):
        pkts, meta = encode_file(TXT_SHORT, "F01", chunk_size=32, ecc_mode="XOR_PARITY", group_size=4)
        surviving = [p for p in pkts if p["packet_id"] != 1]
        res = ecc_decode_or_recover(surviving, recovery_view(meta))
        self.assertTrue(res["success"])
        self.assertEqual(res["recovered_bytes"], TXT_SHORT)

    def test_recovery_signature_does_not_take_original(self):
        self.assertEqual(list(inspect.signature(ecc_decode_or_recover).parameters.keys()), ["reads", "metadata"])


if __name__ == "__main__":
    unittest.main()
