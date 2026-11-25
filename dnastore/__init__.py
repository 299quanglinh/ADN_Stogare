"""Gói tích hợp hệ thống mô phỏng lưu trữ dữ liệu bằng phân tử ADN (Thái – Trung – Linh)."""

from .backends import Backends, load_backends
from .dna_decoder import decode_file, dna_to_bytes, verify_sha256
from .dna_encoder import bytes_to_dna, compute_crc32, compute_gc_content, compute_sha256, encode_file
from .errors import DNAStoreError, FileAlreadyInStore, FileNotInStore, RecoveryFailure, ValidationError
from .metadata_manager import load_metadata, recovery_view, save_metadata, sha256_hex, validate_metadata
from .models import DNAPacket, Reason, RunConfig, check_result_schema
from .noise_simulator import apply_noise
from .orchestrator import run_simulation
from .recovery_pipeline import decode_or_recover, decode_or_recover_report
from .storage_controller import StorageController

__all__ = [
    "Backends",
    "load_backends",
    "bytes_to_dna",
    "dna_to_bytes",
    "compute_crc32",
    "compute_gc_content",
    "compute_sha256",
    "verify_sha256",
    "encode_file",
    "decode_file",
    "DNAStoreError",
    "ValidationError",
    "FileNotInStore",
    "FileAlreadyInStore",
    "RecoveryFailure",
    "sha256_hex",
    "validate_metadata",
    "recovery_view",
    "save_metadata",
    "load_metadata",
    "DNAPacket",
    "RunConfig",
    "Reason",
    "check_result_schema",
    "apply_noise",
    "decode_or_recover",
    "decode_or_recover_report",
    "StorageController",
    "run_simulation",
]
