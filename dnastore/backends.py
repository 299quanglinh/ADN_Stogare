"""Nạp các module thật của Trung và Linh; hỗ trợ fallback sang mock qua biến môi trường DNASTORE_USE_MOCK=1.
Tác giả kiến trúc: Thái. Đã chốt đường dẫn import OI-16.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from typing import Callable

from . import mocks

IMPORT_PATHS = {
    "encode_file": "dnastore.dna_encoder:encode_file",                 # Trung (đã chốt OI-16)
    "apply_noise": "dnastore.noise_simulator:apply_noise",             # Linh  (đã chốt OI-16)
    "decode_or_recover": "dnastore.recovery_pipeline:decode_or_recover",  # Linh + Trung (đã chốt OI-16)
}
_MOCKS = {
    "encode_file": mocks.mock_encode_file,
    "apply_noise": mocks.mock_apply_noise,
    "decode_or_recover": mocks.mock_decode_or_recover,
}


@dataclass
class Backends:
    encode_file: Callable
    apply_noise: Callable
    decode_or_recover: Callable
    sources: dict[str, str] = field(default_factory=dict)  # {"encode_file": "real"|"mock", ...}


def load_backends(use_mock: bool | None = None) -> Backends:
    if use_mock is None:
        use_mock = os.environ.get("DNASTORE_USE_MOCK") == "1"
    funcs, sources = {}, {}
    for name, path in IMPORT_PATHS.items():
        func = None
        if not use_mock:
            mod_name, _, attr = path.partition(":")
            try:
                func = getattr(importlib.import_module(mod_name), attr)
            except (ImportError, AttributeError):
                func = None
        funcs[name], sources[name] = (func, "real") if func else (_MOCKS[name], "mock")
    return Backends(sources=sources, **funcs)
