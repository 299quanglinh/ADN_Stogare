"""app.py — Ứng dụng Web Streamlit cho Hệ thống Mô phỏng Lưu trữ Dữ liệu bằng Phân tử ADN.

Tác giả: Thành viên Dũng (Nhánh: feat/streamlit-ui | Đồng bộ hợp đồng api-v1.0)
Khởi chạy:
    streamlit run app.py

Tuân thủ tuyệt đối docs/api_contract.md (api-v1.0) & CONGVIECCANLAM.md:
  - Không chỉnh sửa logic lõi trong `dnastore/`; chỉ gọi qua API công khai
    (`dnastore.encode_file`, `dnastore.run_simulation`, `dnastore.StorageController`, ...).
  - Truyền đúng 8 khóa hợp lệ của `RunConfig` (tự động set `copies=3` cho REPLICATION_3X / HYBRID,
    KHÔNG truyền khóa lạ như `dropout_scope` vào dict `config`).
  - Hỗ trợ nạp tệp upload (TXT/PNG/PDF nhỏ) hoặc chọn nhanh từ `data/samples/`.
  - Tích hợp 3 nút Preset Demo chuẩn khớp `dnastore/cli.py` (OK_CLEAN / OK_RECOVERED / FAIL_UNRECOVERABLE).
  - Hiển thị đầy đủ schema 21 trường, nút tải tệp khôi phục chỉ mở khi `success=True` & `sha256_match=True`.
  - Trình bày trực quan dữ liệu & biểu đồ thực nghiệm 100% `backends=real` từ `results/`.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dnastore import (
    Reason,
    StorageController,
    compute_gc_content,
    compute_sha256,
    encode_file,
    load_backends,
    run_simulation,
)
from dnastore.models import SUPPORTED_ECC_MODES

ROOT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT_DIR / "data" / "samples"
RESULTS_DIR = ROOT_DIR / "results"
DOCS_DIR = ROOT_DIR / "docs"

MAX_RECOMMENDED_UPLOAD_BYTES = 100 * 1024  # 100 KB (ngưỡng an toàn cho mô phỏng Python thuần)

VALID_RUNCONFIG_KEYS = (
    "chunk_size",
    "ecc_mode",
    "group_size",
    "copies",
    "dropout_rate",
    "substitution_rate",
    "read_count",
    "force_drop",
)

DEMO_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "key": "preset_1",
        "title": "Kịch bản 1: Không lỗi",
        "desc": "ecc_mode=XOR_PARITY, dropout=0%, sub=0%, seed=42 → Kỳ vọng OK_CLEAN.",
        "ecc_mode": "XOR_PARITY",
        "dropout_rate": 0.0,
        "substitution_rate": 0.0,
        "force_drop": [],
        "seed": 42,
        "expected_success": True,
        "expected_reason": Reason.OK_CLEAN,
    },
    {
        "key": "preset_2",
        "title": "Kịch bản 2: Mất 1 packet (XOR sửa được)",
        "desc": "ecc_mode=XOR_PARITY, force_drop=[['DATA', 1]], seed=42 → Kỳ vọng OK_RECOVERED.",
        "ecc_mode": "XOR_PARITY",
        "dropout_rate": 0.0,
        "substitution_rate": 0.0,
        "force_drop": [["DATA", 1]],
        "seed": 42,
        "expected_success": True,
        "expected_reason": Reason.OK_RECOVERED,
    },
    {
        "key": "preset_3",
        "title": "Kịch bản 3: Mất 2 packet cùng nhóm (Vượt ngưỡng)",
        "desc": "ecc_mode=XOR_PARITY, force_drop=[['DATA', 0], ['DATA', 1]], seed=42 → Kỳ vọng FAIL_UNRECOVERABLE.",
        "ecc_mode": "XOR_PARITY",
        "dropout_rate": 0.0,
        "substitution_rate": 0.0,
        "force_drop": [["DATA", 0], ["DATA", 1]],
        "seed": 42,
        "expected_success": False,
        "expected_reason": Reason.FAIL_UNRECOVERABLE,
    },
)


def _stretch_kwargs(widget_fn: Any) -> dict[str, Any]:
    """Tương thích cả Streamlit >=1.50 (width='stretch') lẫn Streamlit 1.32–1.49 (use_container_width=True)."""
    try:
        params = inspect.signature(widget_fn).parameters
        if "width" in params:
            # Trên Streamlit >= 1.50 (như 1.67.0), width="stretch" thay thế use_container_width=True
            st_ver = tuple(int(p) for p in st.__version__.split(".")[:2] if p.isdigit())
            if st_ver >= (1, 50):
                return {"width": "stretch"}
        if "use_container_width" in params:
            return {"use_container_width": True}
    except Exception:
        pass
    return {}


def build_run_config(
    *,
    chunk_size: int = 32,
    ecc_mode: str = "XOR_PARITY",
    group_size: int = 4,
    dropout_rate: float = 0.0,
    substitution_rate: float = 0.0,
    read_count: int = 1,
    force_drop: list[list[Any]] | None = None,
) -> dict[str, Any]:
    """Tạo dict `RunConfig` hợp lệ (đúng 8 khóa `api-v1.0`, tự gán copies=3 cho REPLICATION_3X / HYBRID)."""
    mode = str(ecc_mode).upper()
    copies = 3 if mode in ("REPLICATION_3X", "HYBRID") else 1
    cfg: dict[str, Any] = {
        "chunk_size": int(chunk_size),
        "ecc_mode": mode,
        "group_size": int(group_size),
        "copies": copies,
        "dropout_rate": float(dropout_rate),
        "substitution_rate": float(substitution_rate),
        "read_count": int(read_count),
    }
    if force_drop:
        cfg["force_drop"] = [[str(k).upper(), int(pid)] for k, pid in force_drop]
    return {k: v for k, v in cfg.items() if k in VALID_RUNCONFIG_KEYS}


def is_download_allowed(res: dict[str, Any] | None) -> bool:
    """Chốt chặn học thuật: CHỈ cho tải tệp khi success=True, sha256_match=True và có bytes hợp lệ."""
    if not isinstance(res, dict):
        return False
    return (
        res.get("success") is True
        and res.get("sha256_match") is True
        and isinstance(res.get("recovered_bytes"), (bytes, bytearray))
        and len(res["recovered_bytes"]) > 0
    )


def evaluate_preset_verdict(res: dict[str, Any], preset: dict[str, Any]) -> tuple[bool, str]:
    """Đối chiếu kết quả chạy thật với kỳ vọng của 1 trong 3 kịch bản Preset Demo."""
    exp_ok = bool(preset["expected_success"])
    exp_reason = str(preset["expected_reason"])
    ok_match = (res.get("success") is exp_ok) and (res.get("reason") == exp_reason)
    if exp_ok:
        ok_match = ok_match and (res.get("sha256_match") is True) and (res.get("recovered_bytes") is not None)
    else:
        ok_match = ok_match and (res.get("sha256_match") is False) and (res.get("recovered_bytes") is None)

    if ok_match:
        return True, (
            f"ĐẠT KỲ VỌNG | reason={res.get('reason')} | sha256_match={res.get('sha256_match')} | "
            f"lost={res.get('n_packets_lost')} | {float(res.get('elapsed_ms', 0.0)):.2f} ms"
        )
    return False, (
        f"KHÁC KỲ VỌNG (kỳ vọng success={exp_ok}, reason={exp_reason} nhưng nhận "
        f"success={res.get('success')}, reason={res.get('reason')}): {res.get('reason_detail', '')}"
    )


def list_sample_files() -> list[Path]:
    """Tự động liệt kê mọi tệp mẫu trong data/samples/ (TXT/PNG/PDF...)."""
    if not SAMPLES_DIR.exists():
        return []
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


def format_dna_preview(seq: str, limit: int = 44) -> str:
    return seq if len(seq) <= limit else f"{seq[:limit]}... ({len(seq)} nt)"


@st.cache_data(show_spinner=False)
def cached_encode_preview(
    raw_bytes: bytes,
    filename: str,
    chunk_size: int,
    ecc_mode: str,
    group_size: int,
) -> dict[str, Any]:
    """Gọi `dnastore.encode_file` (Trung) có cache để xem trước bảng packet & chuỗi ADN gốc."""
    mode = str(ecc_mode).upper()
    copies = 3 if mode in ("REPLICATION_3X", "HYBRID") else 1
    packets, metadata = encode_file(
        raw_bytes,
        file_id="PREVIEW",
        chunk_size=int(chunk_size),
        filename=filename,
        ecc_mode=mode,
        ecc_params={"group_size": int(group_size), "copies": copies},
    )
    total_nt = sum(len(p["dna_sequence"]) for p in packets)
    baseline_nt = len(raw_bytes) * 4
    overhead_pct = round(((total_nt - baseline_nt) / baseline_nt) * 100.0, 2) if baseline_nt else 0.0
    bits_per_nt = round((len(raw_bytes) * 8) / total_nt, 2) if total_nt else 0.0
    data_seqs = [p["dna_sequence"] for p in packets if p["kind"] == "DATA" and p.get("copy_id", 0) == 0]
    gc_pct = compute_gc_content("".join(data_seqs)) if data_seqs else 0.0
    return {
        "packets": packets,
        "metadata": metadata,
        "total_nucleotides": total_nt,
        "overhead_pct": overhead_pct,
        "bits_per_nt": bits_per_nt,
        "gc_content_pct": gc_pct,
    }


def render_simulation_result(res: dict[str, Any], original_bytes: bytes, default_filename: str, key_prefix: str = "sim") -> None:
    """Hiển thị đầy đủ 21 trường chuẩn hóa theo `docs/api_contract.md` & nút tải tệp khôi phục."""
    backends = res.get("backends", {})
    all_real = isinstance(backends, dict) and bool(backends) and all(v == "real" for v in backends.values())
    if all_real:
        st.caption(f"Nguồn thực thi (`backends`): `{backends}` — 100% module thật.")
    else:
        st.warning(f"Nguồn thực thi (`backends`): `{backends}` — có module đang chạy ở chế độ mock.")

    if res.get("success") is True and res.get("sha256_match") is True:
        st.success(
            f"✅ KHÔI PHỤC THÀNH CÔNG | `reason={res.get('reason')}` | "
            f"`sha256_match=True` | `{float(res.get('elapsed_ms', 0.0)):.2f} ms`"
        )
    else:
        detail = res.get("reason_detail", "")
        detail_part = f" — {detail}" if detail else ""
        st.error(
            f"❌ KHÔI PHỤC THẤT BẠI TRUNG THỰC | `reason={res.get('reason')}`{detail_part}"
        )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Kích thước gốc / phục hồi", f"{res.get('original_size', 0)} / {res.get('recovered_size', 0)} B")
    c2.metric("Tổng packet (`n_packets`)", f"{res.get('n_packets', 0)}")
    lost = res.get("n_packets_lost")
    c3.metric("Packet mất (`n_packets_lost`)", "N/A" if lost is None else str(lost))
    subs = res.get("n_substituted_bases")
    c4.metric("Base đổi (`n_substituted_bases`)", "N/A" if subs is None else str(subs))
    c5.metric("Thời gian (`elapsed_ms`)", f"{float(res.get('elapsed_ms', 0.0)):.2f} ms")

    orig_sha = compute_sha256(original_bytes) if original_bytes else "N/A"
    rec_bytes = res.get("recovered_bytes")
    rec_sha = compute_sha256(rec_bytes) if isinstance(rec_bytes, (bytes, bytearray)) else "None (không xuất tệp sai)"

    st.markdown("**Đối chiếu toàn vẹn SHA-256 & Thông số lưu kho:**")
    st.code(
        f"file_id          : {res.get('file_id')} | filename: {res.get('filename')} ({res.get('file_type')})\n"
        f"ecc_mode         : {res.get('ecc_mode')} | chunk_size: {res.get('chunk_size')} B | n_nucleotides: {res.get('n_nucleotides'):,} nt\n"
        f"noise            : dropout_rate={res.get('dropout_rate')} | substitution_rate={res.get('substitution_rate')} | seed={res.get('seed')}\n"
        f"SHA-256 gốc      : {orig_sha}\n"
        f"SHA-256 phục hồi : {rec_sha}\n"
        f"sha256_match     : {res.get('sha256_match')} | success: {res.get('success')} | reason: {res.get('reason')}",
        language="text",
    )

    fname = res.get("filename") or default_filename
    if is_download_allowed(res):
        st.download_button(
            label=f"⬇️ Tải xuống tệp đã khôi phục (recovered_{fname})",
            data=res["recovered_bytes"],
            file_name=f"recovered_{fname}",
            mime="application/octet-stream",
            key=f"dl_{key_prefix}_{res.get('file_id')}_{res.get('seed')}",
        )
        lower_name = fname.lower()
        if lower_name.endswith(".txt"):
            with st.expander("Xem trước nội dung văn bản đã khôi phục", expanded=False):
                st.text(res["recovered_bytes"].decode("utf-8", errors="replace"))
        elif lower_name.endswith(".png"):
            st.image(res["recovered_bytes"], caption=f"Ảnh PNG khôi phục thành công ({fname})", width=220)
    else:
        st.info("🔒 Nút tải tệp đã bị khóa vì ca chạy thất bại hoặc SHA-256 không khớp (`recovered_bytes=None`).")


def main() -> None:
    st.set_page_config(
        page_title="Mô phỏng Lưu trữ Dữ liệu bằng Phân tử ADN",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("🧬 Mô phỏng Hệ thống Lưu trữ Dữ liệu bằng Phân tử ADN")

    if "store" not in st.session_state:
        # Chốt OI-18: giữ 1 StorageController bộ nhớ trong trong phiên Streamlit
        st.session_state["store"] = StorageController()
    if "last_sim_result" not in st.session_state:
        st.session_state["last_sim_result"] = None
    if "last_sim_input" not in st.session_state:
        st.session_state["last_sim_input"] = None
    if "preset_results" not in st.session_state:
        st.session_state["preset_results"] = {}

    # =========================================================================
    # SIDEBAR: Nạp tệp & Bảng điều khiển RunConfig (khớp CONGVIECCANLAM.md)
    # =========================================================================
    with st.sidebar:
        st.header("⚙️ Cấu hình Mô phỏng")
        be_sources = load_backends().sources
        if all(v == "real" for v in be_sources.values()):
            st.success(f"Backends: 100% REAL (`api-v1.0`)\n`{be_sources}`")
        else:
            st.warning(f"Backends: `{be_sources}`")

        st.subheader("1. Nạp tệp đầu vào")
        sample_files = list_sample_files()
        source_mode = st.radio(
            "Chọn nguồn dữ liệu:",
            ["Chọn nhanh từ data/samples/", "Tải tệp từ máy (TXT / PNG / PDF)"],
            index=0,
        )

        raw_bytes: bytes | None = None
        filename = "sample_medium.txt"
        upload_error: str | None = None

        if source_mode == "Chọn nhanh từ data/samples/":
            if not sample_files:
                upload_error = "Không tìm thấy tệp mẫu trong thư mục `data/samples/`."
            else:
                sample_names = [p.name for p in sample_files]
                default_idx = sample_names.index("sample_medium.txt") if "sample_medium.txt" in sample_names else 0
                selected_name = st.selectbox("Tệp mẫu có sẵn:", sample_names, index=default_idx)
                selected_path = SAMPLES_DIR / selected_name
                filename = selected_path.name
                raw_bytes = selected_path.read_bytes()
        else:
            uploaded = st.file_uploader(
                f"Tải tệp nhỏ (khuyến nghị <= {MAX_RECOMMENDED_UPLOAD_BYTES // 1024} KB):",
                type=["txt", "png", "pdf", "bin", "csv", "json"],
            )
            if uploaded is not None:
                data_up = uploaded.getvalue()
                if len(data_up) == 0:
                    upload_error = "Tệp tải lên rỗng (0 byte) — bị từ chối bởi hợp đồng FAIL_INVALID_INPUT."
                elif len(data_up) > MAX_RECOMMENDED_UPLOAD_BYTES:
                    upload_error = (
                        f"Tệp `{uploaded.name}` có kích thước {len(data_up):,} bytes, vượt ngưỡng khuyến nghị "
                        f"{MAX_RECOMMENDED_UPLOAD_BYTES // 1024} KB của mô phỏng Python thuần."
                    )
                else:
                    filename = uploaded.name
                    raw_bytes = data_up

        st.subheader("2. Mã hóa & Dự phòng (ECC)")
        ecc_mode = st.selectbox(
            "Chế độ dự phòng (`ecc_mode`):",
            options=list(SUPPORTED_ECC_MODES),
            index=1,
            help="NONE: không dự phòng | XOR_PARITY: 4+1 | REPLICATION_3X: 3 bản sao | HYBRID: XOR + 3 bản sao",
        )
        eff_copies = 3 if ecc_mode in ("REPLICATION_3X", "HYBRID") else 1
        st.caption(f"Hệ số nhân bản gửi vào `RunConfig`: `copies = {eff_copies}`")
        chunk_size = st.select_slider("Kích thước khối (`chunk_size`, bytes):", options=[16, 32, 64], value=32)
        group_size = st.number_input("Số DATA / nhóm XOR (`group_size`):", min_value=2, max_value=8, value=4, step=1)

        st.subheader("3. Kênh nhiễu & Hạt giống")
        dropout_pct = st.slider(
            "Tỷ lệ Dropout (`dropout_rate`, %):",
            min_value=0.0,
            max_value=30.0,
            value=5.0,
            step=1.0,
        )
        sub_pct = st.slider(
            "Tỷ lệ Substitution (`substitution_rate`, %/base):",
            min_value=0.0,
            max_value=2.0,
            value=0.0,
            step=0.1,
        )
        read_count = st.number_input("Số bản đọc/packet (`read_count`):", min_value=1, max_value=5, value=1, step=1)
        seed = st.number_input("Random Seed (`seed`):", min_value=0, max_value=999999, value=42, step=1)

    tab1, tab2, tab3, tab4 = st.tabs([
        "🧪 1. Mô phỏng Toàn luồng",
        "🎬 2. Preset Demo Trực tiếp (3 ca)",
        "📊 3. Thực nghiệm & Đồ thị (2.160 lượt)",
        "🏗️ 4. Kiến trúc & Hợp đồng api-v1.0",
    ])

    # =========================================================================
    # TAB 1: MÔ PHỎNG TOÀN LUỒNG
    # =========================================================================
    with tab1:
        if upload_error:
            st.error(upload_error)
        elif raw_bytes is None:
            st.info("Vui lòng chọn một tệp mẫu hoặc tải tệp từ máy ở thanh bên trái để bắt đầu.")
        else:
            prev = cached_encode_preview(
                raw_bytes=raw_bytes,
                filename=filename,
                chunk_size=int(chunk_size),
                ecc_mode=ecc_mode,
                group_size=int(group_size),
            )
            meta = prev["metadata"]
            pkts = prev["packets"]

            st.subheader("Bước 1 & 2: Mã hóa 2 bit/nt & Bảng Packet ADN (`dnastore.encode_file`)")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Kích thước tệp gốc", f"{meta['file_size']:,} B")
            m2.metric("Packet lưu kho", f"{len(pkts)}", f"{meta['total_packets']} DATA")
            m3.metric("Tổng Nucleotide", f"{prev['total_nucleotides']:,} nt")
            m4.metric("Overhead lưu trữ", f"+{prev['overhead_pct']}%", f"{prev['bits_per_nt']} bit/nt")
            m5.metric("GC-content (DATA)", f"{prev['gc_content_pct']}%")

            with st.expander("Xem Metadata, Bảng Packet (`crc32`) & Trích chuỗi ADN (`A/T/G/C`)", expanded=True):
                col_m, col_p = st.columns([1, 2])
                with col_m:
                    st.markdown("**Metadata tệp gốc**")
                    st.json(meta)
                with col_p:
                    st.markdown(f"**Bảng Packet ADN (hiển thị tối đa 16 / {len(pkts)} packet)**")
                    pkt_table = [
                        {
                            "packet_id": p["packet_id"],
                            "kind": p["kind"],
                            "group_id": p["group_id"],
                            "copy_id": p.get("copy_id", 0),
                            "payload_len": p["payload_len"],
                            "crc32": p.get("crc32", ""),
                            "dna_sequence (trích)": format_dna_preview(p["dna_sequence"], 34),
                        }
                        for p in pkts[:16]
                    ]
                    st.dataframe(pd.DataFrame(pkt_table), hide_index=True, **_stretch_kwargs(st.dataframe))

                sel_idx = st.selectbox(
                    "Chọn 1 packet để xem đầy đủ chuỗi nucleotide (`A/T/G/C`):",
                    options=list(range(min(len(pkts), 40))),
                    format_func=lambda i: (
                        f"Packet #{pkts[i]['packet_id']} ({pkts[i]['kind']}, "
                        f"group={pkts[i]['group_id']}, copy={pkts[i].get('copy_id', 0)}, crc32={pkts[i].get('crc32', '')})"
                    ),
                )
                st.code(pkts[sel_idx]["dna_sequence"], language="text")

            st.divider()
            st.subheader("Bước 3 & 4: Chạy toàn luồng 9 bước (`dnastore.run_simulation`)")
            if st.button("🚀 Chạy Mô phỏng (Lưu kho → Gây nhiễu → Phục hồi → Xác minh SHA-256)", type="primary", **_stretch_kwargs(st.button)):
                sim_cfg = build_run_config(
                    chunk_size=int(chunk_size),
                    ecc_mode=ecc_mode,
                    group_size=int(group_size),
                    dropout_rate=float(dropout_pct) / 100.0,
                    substitution_rate=float(sub_pct) / 100.0,
                    read_count=int(read_count),
                )
                sim_res = run_simulation(
                    (filename, raw_bytes),
                    sim_cfg,
                    seed=int(seed),
                    storage=st.session_state["store"],
                )
                st.session_state["last_sim_result"] = sim_res
                st.session_state["last_sim_input"] = (filename, raw_bytes)

            last_res = st.session_state.get("last_sim_result")
            last_in = st.session_state.get("last_sim_input")
            if last_res is not None and last_in is not None:
                render_simulation_result(last_res, last_in[1], last_in[0], key_prefix="tab1")

    # =========================================================================
    # TAB 2: 3 NÚT PRESET DEMO TRỰC TIẾP (KHỚP dnastore/cli.py & api_contract.md)
    # =========================================================================
    with tab2:
        st.subheader("🎬 3 Kịch bản Preset Demo Trực tiếp (Khớp `dnastore/cli.py` & Mục 6.2 `api_contract.md`)")
        default_demo_path = SAMPLES_DIR / "sample_medium.txt"
        use_current_file = st.checkbox(
            f"Dùng tệp đang chọn ở Sidebar (`{filename}`) thay cho mặc định `sample_medium.txt` (800 B)",
            value=False,
            disabled=(raw_bytes is None),
        )
        if use_current_file and raw_bytes is not None:
            demo_name, demo_bytes = filename, raw_bytes
        elif default_demo_path.exists():
            demo_name, demo_bytes = default_demo_path.name, default_demo_path.read_bytes()
        else:
            demo_name = "demo.txt"
            demo_bytes = ("Lưu trữ dữ liệu bằng phân tử ADN: A, T, G, C. " * 6).encode("utf-8")

        st.caption(
            f"Tệp chạy Demo: **`{demo_name}`** ({len(demo_bytes):,} bytes) | "
            f"SHA-256 gốc: `{compute_sha256(demo_bytes)[:24]}...` | "
            "Cấu hình nền: `ecc_mode=XOR_PARITY`, `chunk_size=32`, `group_size=4`, `seed=42`."
        )

        if st.button("▶️ Chạy lần lượt cả 3 kịch bản Demo", type="primary", **_stretch_kwargs(st.button)):
            for preset in DEMO_PRESETS:
                p_cfg = build_run_config(
                    chunk_size=32,
                    ecc_mode=preset["ecc_mode"],
                    group_size=4,
                    dropout_rate=preset["dropout_rate"],
                    substitution_rate=preset["substitution_rate"],
                    read_count=1,
                    force_drop=preset["force_drop"] or None,
                )
                r = run_simulation((demo_name, demo_bytes), p_cfg, seed=preset["seed"], storage=StorageController())
                st.session_state["preset_results"][preset["key"]] = (r, demo_name, demo_bytes)

        cols = st.columns(3)
        for col, preset in zip(cols, DEMO_PRESETS):
            with col:
                st.markdown(f"#### {preset['title']}")
                st.caption(preset["desc"])
                if st.button(f"Chạy {preset['title'].split(':')[0]}", key=f"btn_{preset['key']}", **_stretch_kwargs(st.button)):
                    p_cfg = build_run_config(
                        chunk_size=32,
                        ecc_mode=preset["ecc_mode"],
                        group_size=4,
                        dropout_rate=preset["dropout_rate"],
                        substitution_rate=preset["substitution_rate"],
                        read_count=1,
                        force_drop=preset["force_drop"] or None,
                    )
                    r = run_simulation((demo_name, demo_bytes), p_cfg, seed=preset["seed"], storage=StorageController())
                    st.session_state["preset_results"][preset["key"]] = (r, demo_name, demo_bytes)

                if preset["key"] in st.session_state["preset_results"]:
                    r, r_name, _ = st.session_state["preset_results"][preset["key"]]
                    ok_v, msg_v = evaluate_preset_verdict(r, preset)
                    if ok_v:
                        st.success(msg_v)
                    else:
                        st.error(msg_v)
                    st.json({
                        "success": r["success"],
                        "reason": r["reason"],
                        "reason_detail": r["reason_detail"],
                        "sha256_match": r["sha256_match"],
                        "n_packets": r["n_packets"],
                        "n_packets_lost": r["n_packets_lost"],
                        "recovered_bytes_is_none": r["recovered_bytes"] is None,
                        "backends": r["backends"],
                    })
                    if is_download_allowed(r):
                        st.download_button(
                            label=f"⬇️ Tải tệp ({preset['key']}_{r_name})",
                            data=r["recovered_bytes"],
                            file_name=f"{preset['key']}_{r_name}",
                            key=f"dl_{preset['key']}",
                        )

    # =========================================================================
    # TAB 3: KẾT QUẢ THỰC NGHIỆM & ĐỒ THỊ (100% backends = real)
    # =========================================================================
    with tab3:
        st.subheader("📊 Kết quả Thực nghiệm Định lượng (2.160 lượt chạy — 100% `backends = real`)")
        cond_path = RESULTS_DIR / "experiment_conditions.json"
        if cond_path.exists():
            cond = json.loads(cond_path.read_text(encoding="utf-8"))
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Tổng lượt mô phỏng", f"{cond.get('total_runs', 2160):,}")
            k2.metric("Số seed / mức nhiễu", f"{cond.get('trials_per_level', 30)}")
            k3.metric("Cấu hình chuẩn", f"chunk={cond.get('chunk_size', 32)} B | group={cond.get('group_size', 4)}")
            k4.metric("Trạng thái Backends", "100% REAL" if all(v == "real" for v in cond.get("backends", {}).values()) else "MIXED")

        charts = [
            (
                RESULTS_DIR / "chart_dropout_recovery.png",
                "Biểu đồ 1: Tỷ lệ tái tạo toàn tệp theo mức Dropout (A: Chỉ Dropout | B: Dropout + Substitution 0,1%/base — sample_medium.txt, 800 B)",
            ),
            (
                RESULTS_DIR / "chart_substitution_scaling.png",
                "Biểu đồ 2: Khả năng chống Substitution (0–2,0%/base) & Ảnh hưởng kích thước tệp TXT (166 B / 800 B / 1.955 B)",
            ),
            (
                RESULTS_DIR / "chart_overhead_runtime.png",
                "Biểu đồ 3: So sánh Chi phí lưu trữ (Overhead %) trên 3 kích thước tệp & Thời gian xử lý trung bình (ms)",
            ),
        ]
        for c_path, caption in charts:
            if c_path.exists():
                st.image(str(c_path), caption=caption, **_stretch_kwargs(st.image))

        sum_path = RESULTS_DIR / "benchmark_summary.csv"
        if sum_path.exists():
            st.markdown("#### Bảng tổng hợp Thực nghiệm (`results/benchmark_summary.csv` — 72 cấu hình)")
            df_sum = pd.read_csv(sum_path)
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                scen_opts = ["Tất cả"] + sorted(df_sum["scenario"].unique().tolist())
                sel_scen = st.selectbox("Lọc theo kịch bản (`scenario`):", scen_opts, index=0)
            with f_col2:
                ecc_opts = ["Tất cả"] + list(SUPPORTED_ECC_MODES)
                sel_ecc = st.selectbox("Lọc theo chế độ ECC:", ecc_opts, index=0)

            df_view = df_sum.copy()
            if sel_scen != "Tất cả":
                df_view = df_view[df_view["scenario"] == sel_scen]
            if sel_ecc != "Tất cả":
                df_view = df_view[df_view["ecc_mode"] == sel_ecc]
            st.dataframe(df_view, hide_index=True, **_stretch_kwargs(st.dataframe))

            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    "⬇️ Tải benchmark_summary.csv (72 dòng)",
                    data=sum_path.read_bytes(),
                    file_name="benchmark_summary.csv",
                    mime="text/csv",
                )
            res_csv = RESULTS_DIR / "benchmark_results.csv"
            if res_csv.exists():
                with dl2:
                    st.download_button(
                        "⬇️ Tải benchmark_results.csv đầy đủ (2.160 dòng)",
                        data=res_csv.read_bytes(),
                        file_name="benchmark_results.csv",
                        mime="text/csv",
                    )

        tc_path = RESULTS_DIR / "test_cases.csv"
        if tc_path.exists():
            with st.expander("Xem bảng 24 ca kiểm thử kịch bản T01–T08 (`results/test_cases.csv`)", expanded=False):
                st.dataframe(pd.read_csv(tc_path), hide_index=True, **_stretch_kwargs(st.dataframe))

    # =========================================================================
    # TAB 4: KIẾN TRÚC 9 BƯỚC, HỢP ĐỒNG api-v1.0 & KHO LƯU TRỮ PHIÊN
    # =========================================================================
    with tab4:
        st.subheader("🏗️ Kiến trúc 9 bước, Hợp đồng `api-v1.0` & Phương án dự phòng Demo")
        arch_img = DOCS_DIR / "architecture.png"
        if arch_img.exists():
            st.image(str(arch_img), caption="Sơ đồ Kiến trúc 9 bước & Ranh giới cách ly học thuật (docs/architecture.png)", **_stretch_kwargs(st.image))

        wf_img = DOCS_DIR / "ui_wireframe.png"
        if wf_img.exists():
            with st.expander("Xem phác thảo bố cục giao diện (docs/ui_wireframe.png)", expanded=False):
                st.image(str(wf_img), **_stretch_kwargs(st.image))

        st.markdown(
            """
            - **API công khai đang gọi:** `dnastore.encode_file()` (Trung) và `dnastore.run_simulation()` (Thái — tích hợp Trung + Linh).
            - **Phương án dự phòng sát giờ Demo:** Nếu trình duyệt gặp sự cố, chạy trực tiếp trong Terminal:
              ```bash
              python -m dnastore.cli demo
              ```
            """
        )
        stored_files = st.session_state["store"].list_files()
        st.markdown(f"**Danh sách tệp đã lưu trong `StorageController` phiên hiện tại ({len(stored_files)} tệp):**")
        if stored_files:
            st.dataframe(pd.DataFrame(stored_files), hide_index=True, **_stretch_kwargs(st.dataframe))
        else:
            st.caption("Chưa có lượt chạy nào ở Tab 1 trong phiên hiện tại.")


if __name__ == "__main__":
    main()
