"""Kiểm thử kênh nhiễu của Linh (bao gồm force_drop OI-11, khóa thống kê OI-08 & dropout độc lập theo bản sao)."""
from copy import deepcopy
import random
import unittest

from dnastore.noise_simulator import apply_noise


def make_packets(count=12):
    return [
        {
            "file_id": "F01",
            "packet_id": i,
            "total_packets": count,
            "kind": "DATA",
            "group_id": i // 4,
            "dna_sequence": "ATGC" * 16,
            "payload_len": 16,
            "copy_id": 0,
            "crc32": "12345678",
            "extra": {"labels": ["original"]},
        }
        for i in range(count)
    ]


class NoiseSimulatorTests(unittest.TestCase):
    def test_no_noise_preserves_sequence_and_packet_fields(self):
        packets = make_packets()
        reads, stats = apply_noise(packets, {}, 42)
        self.assertEqual(len(reads), len(packets))
        for packet, read in zip(packets, reads):
            self.assertEqual({k: read[k] for k in packet}, packet)
            self.assertEqual(read["read_id"], 0)
        self.assertEqual(stats["n_dropped_packets"], 0)
        self.assertEqual(stats["n_substituted_bases"], 0)
        self.assertEqual(stats["n_reads"], len(packets))

    def test_seed_repeats_without_using_global_rng(self):
        config = {"dropout_rate": 0.2, "substitution_rate": 0.1, "read_count": 3}
        before = random.getstate()
        first = apply_noise(make_packets(), config, 42)
        self.assertEqual(first, apply_noise(make_packets(), config, 42))
        self.assertEqual(before, random.getstate())

    def test_input_and_nested_fields_are_not_mutated_or_aliased(self):
        packets = make_packets(1)
        before = deepcopy(packets)
        reads, _ = apply_noise(packets, {"substitution_rate": 1, "read_count": 2}, 1)
        self.assertEqual(packets, before)
        reads[0]["extra"]["labels"].append("changed")
        self.assertEqual(packets, before)
        self.assertEqual(reads[1]["extra"]["labels"], ["original"])

    def test_force_drop_removes_exact_packets_deterministically(self):
        packets = make_packets(6)
        reads, stats = apply_noise(packets, {"force_drop": [["DATA", 1], ["DATA", 4]]}, 0)
        surviving_ids = [r["packet_id"] for r in reads]
        self.assertEqual(surviving_ids, [0, 2, 3, 5])
        self.assertEqual(stats["n_dropped_packets"], 2)
        self.assertEqual(stats["logical_packets_dropped"], 2)

    def test_independent_copy_dropout_helps_replication(self):
        base = make_packets(50)
        packets = (
            base
            + [{**deepcopy(p), "copy_id": 1} for p in base]
            + [{**deepcopy(p), "copy_id": 2} for p in base]
        )
        reads, stats = apply_noise(packets, {"dropout_rate": 0.2, "read_count": 1}, 42)
        # Với 3 bản sao độc lập và p=0.2, xác suất mất cả 3 bản sao = 0.008 << 0.2
        self.assertGreater(stats["source_packets_dropped"], 0)
        self.assertLess(stats["logical_packets_dropped"], stats["source_packets_dropped"])
        self.assertEqual(stats["n_dropped_packets"], stats["source_packets_dropped"])

    def test_logical_dropout_scope_option(self):
        packets = make_packets(40)
        packets += [{**deepcopy(p), "copy_id": 1} for p in packets]
        reads, stats = apply_noise(packets, {"dropout_rate": 0.5, "dropout_scope": "logical"}, 42)
        self.assertEqual(stats["source_packets_dropped"], 2 * stats["logical_packets_dropped"])
        self.assertEqual(len(reads), 2 * (40 - stats["logical_packets_dropped"]))

    def test_full_substitution_changes_every_base_and_preserves_crc32(self):
        packets = make_packets(2)
        reads, stats = apply_noise(packets, {"substitution_rate": 1, "read_count": 3}, 12)
        self.assertEqual(len(reads), 6)
        for read in reads:
            original = packets[read["packet_id"]]["dna_sequence"]
            self.assertEqual(len(read["dna_sequence"]), len(original))
            self.assertTrue(all(a != b for a, b in zip(original, read["dna_sequence"])))
            self.assertEqual(read["crc32"], "12345678")
        self.assertEqual(stats["n_substituted_bases"], stats["bases_processed"])

    def test_invalid_config_is_rejected(self):
        invalid = [
            {"dropout_rate": -0.1},
            {"dropout_rate": 5},
            {"substitution_rate": float("nan")},
            {"dropout_rate": float("inf")},
            {"substitution_rate": True},
            {"dropout_rate": "0.1"},
            {"read_count": 0},
            {"read_count": 1.5},
            {"read_count": True},
            {"dropout": 0.1},
            {"force_drop": [["UNKNOWN", 1]]},
            {"force_drop": ["DATA", 1]},
        ]
        for config in invalid:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    apply_noise(make_packets(1), config, 1)


if __name__ == "__main__":
    unittest.main()
