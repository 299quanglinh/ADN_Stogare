"""Kiểm thử StorageController và MetadataManager (Thái + hồi quy bảo toàn crc32 của Trung).
Chạy được bằng cả `python -m unittest discover -s tests -v` và `python -m pytest -q`.
"""
from pathlib import Path
import tempfile
import unittest

from dnastore.dna_encoder import encode_file
from dnastore.errors import FileAlreadyInStore, FileNotInStore, ValidationError
from dnastore.metadata_manager import load_metadata, recovery_view, save_metadata, sha256_hex
from dnastore.mocks import mock_encode_file
from dnastore.storage_controller import StorageController

DATA = ("Xin chào ADN " * 10).encode("utf-8")


def make(fid="F01", data=DATA):
    packets, md = mock_encode_file(data, fid, 32)
    md["filename"] = "a.txt"
    return packets, md


class StorageControllerTests(unittest.TestCase):
    def test_store_then_read_roundtrip_memory(self):
        s = StorageController()
        packets, md = make()
        s.store_packets("F01", packets, md)
        self.assertEqual(s.read_packets("F01"), packets)
        self.assertEqual(s.read_metadata("F01"), md)

    def test_store_then_read_roundtrip_disk_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            packets, md = make()
            StorageController(tmp).store_packets("F01", packets, md)
            s2 = StorageController(tmp)
            self.assertEqual(s2.read_packets("F01"), packets)
            self.assertEqual(s2.list_files()[0]["file_id"], "F01")

    def test_store_preserves_trung_crc32_and_covered_packet_ids(self):
        """Hồi quy lỗi tích hợp #1: kho phải giữ nguyên crc32 và covered_packet_ids của Trung."""
        with tempfile.TemporaryDirectory() as tmp:
            packets, md = encode_file(
                DATA, "F01", chunk_size=32, filename="vi.txt", ecc_mode="XOR_PARITY", group_size=4
            )
            s = StorageController(tmp)
            s.store_packets("F01", packets, md)
            s2 = StorageController(tmp)
            loaded = s2.read_packets("F01")
            self.assertEqual(loaded, packets)
            self.assertTrue(all("crc32" in p and len(p["crc32"]) == 8 for p in loaded))
            parity_pkts = [p for p in loaded if p["kind"] == "PARITY"]
            self.assertTrue(parity_pkts and all("covered_packet_ids" in p for p in parity_pkts))

    def test_read_returns_deep_copy_so_noise_cannot_mutate_store(self):
        s = StorageController()
        packets, md = make()
        s.store_packets("F01", packets, md)
        s.read_packets("F01")[0]["dna_sequence"] = "A" * 128
        self.assertEqual(s.read_packets("F01"), packets)

    def test_new_file_id_sequential_and_unique(self):
        s = StorageController()
        self.assertEqual([s.new_file_id() for _ in range(3)], ["F01", "F02", "F03"])

    def test_duplicate_file_id_rejected_unless_overwrite(self):
        s = StorageController()
        packets, md = make()
        s.store_packets("F01", packets, md)
        with self.assertRaises(FileAlreadyInStore):
            s.store_packets("F01", packets, md)
        s.store_packets("F01", packets, md, overwrite=True)

    def test_unknown_file_raises(self):
        with self.assertRaises(FileNotInStore):
            StorageController().read_packets("F99")

    def test_invalid_inputs_rejected(self):
        mutations = [
            ("bad_base_X", lambda p, m: p[0].update(dna_sequence="ATGX" * 8)),
            ("bad_kind", lambda p, m: p[0].update(kind="DATAX")),
            ("wrong_file_id", lambda p, m: p[0].update(file_id="F02")),
            ("duplicate_key", lambda p, m: p.append(dict(p[0]))),
            ("mismatch_total", lambda p, m: p[0].update(total_packets=999)),
            ("missing_sha", lambda p, m: m.pop("expected_sha256")),
            ("oversize_payload", lambda p, m: p[0].update(payload_len=10_000)),
            ("bad_crc32", lambda p, m: p[0].update(crc32="INVALID_CRC")),
        ]
        for label, mutate in mutations:
            with self.subTest(case=label):
                packets, md = make()
                mutate(packets, md)
                with self.assertRaises(ValidationError):
                    StorageController().store_packets("F01", packets, md)

    def test_path_traversal_file_id_rejected(self):
        packets, md = make("../x")
        with self.assertRaises(ValidationError):
            StorageController().store_packets("../x", packets, md)

    def test_stats_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            s = StorageController(tmp_path)
            packets, md = make()
            s.store_packets("F01", packets, md)
            st = s.storage_stats("F01")
            self.assertEqual(st["n_data"] + st["n_parity"], len(packets))
            self.assertGreaterEqual(st["n_parity"], 1)
            s.delete_file("F01")
            self.assertFalse(s.exists("F01"))
            self.assertFalse((tmp_path / "F01").exists())

    def test_metadata_file_roundtrip_and_recovery_view_hides_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            _, md = make()
            save_metadata(path, md)
            self.assertEqual(load_metadata(path), md)
            self.assertNotIn("expected_sha256", recovery_view(md))
            self.assertEqual(md["expected_sha256"], sha256_hex(DATA))


if __name__ == "__main__":
    unittest.main()
