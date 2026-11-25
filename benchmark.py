"""benchmark.py
Script thực nghiệm định lượng chính thức của hệ thống tích hợp (Thái + Trung + Linh).
Toàn bộ lượt chạy đi qua hàm `dnastore.orchestrator.run_simulation()` với 100% module THẬT
(`backends = {'encode_file': 'real', 'apply_noise': 'real', 'decode_or_recover': 'real'}`),
dùng `StorageController()` bộ nhớ trong (chốt OI-18) trên bộ 3 tệp TXT tự tạo.

Chạy nhanh:
    python benchmark.py --trials 30
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any

from dnastore.backends import load_backends
from dnastore.orchestrator import run_simulation
from dnastore.storage_controller import StorageController

ROOT = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT / "data" / "samples"
RESULTS_DIR = ROOT / "results"

ECC_MODES = ("NONE", "XOR_PARITY", "REPLICATION_3X", "HYBRID")
DROPOUT_LEVELS = (0.00, 0.05, 0.10, 0.15, 0.20)
SUB_LEVELS = (0.000, 0.001, 0.005, 0.010, 0.020)
CHUNK_SIZE = 32
GROUP_SIZE = 4
COPIES = 3


def load_samples() -> dict[str, bytes]:
    names = ("sample_short.txt", "sample_medium.txt", "sample_long.txt")
    return {name: (SAMPLES_DIR / name).read_bytes() for name in names}


def run_benchmark(trials: int = 30, output_dir: Path = RESULTS_DIR) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    be = load_backends(use_mock=False)
    assert all(v == "real" for v in be.sources.values()), f"Expected all real backends, got {be.sources}"
    samples = load_samples()

    rows: list[dict[str, Any]] = []

    def run_batch(scenario: str, filename: str, data: bytes, dr: float, sr: float, seeds: list[int]) -> None:
        base_nt = len(data) * 4
        for mode in ECC_MODES:
            cfg = {
                "chunk_size": CHUNK_SIZE,
                "ecc_mode": mode,
                "group_size": GROUP_SIZE,
                "copies": COPIES if mode in ("REPLICATION_3X", "HYBRID") else 1,
                "dropout_rate": dr,
                "substitution_rate": sr,
                "read_count": 1,
            }
            for seed in seeds:
                # Kho bộ nhớ trong mới cho từng lượt để đo độc lập và giữ tốc độ cao (OI-18)
                res = run_simulation((filename, data), cfg, seed=seed, storage=StorageController(), backends=be)
                overhead_pct = round(((res["n_nucleotides"] - base_nt) / base_nt) * 100.0, 2)
                rows.append({
                    "scenario": scenario,
                    "file_id": res["file_id"],
                    "filename": filename,
                    "file_type": res["file_type"],
                    "file_size_bytes": res["original_size"],
                    "ecc_mode": res["ecc_mode"],
                    "chunk_size": res["chunk_size"],
                    "seed": res["seed"],
                    "dropout_rate": res["dropout_rate"],
                    "substitution_rate": res["substitution_rate"],
                    "n_packets": res["n_packets"],
                    "n_packets_lost": res["n_packets_lost"],
                    "n_substituted_bases": res["n_substituted_bases"],
                    "n_nucleotides": res["n_nucleotides"],
                    "overhead_pct": overhead_pct,
                    "elapsed_ms": round(res["elapsed_ms"], 3),
                    "success": res["success"],
                    "sha256_match": res["sha256_match"],
                    "reason": res["reason"],
                    "backends": json.dumps(res["backends"], sort_keys=True),
                })

    med_data = samples["sample_medium.txt"]

    # Kịch bản A: Chỉ Dropout (0/5/10/15/20%) trên sample_medium.txt
    for lvl_idx, dr in enumerate(DROPOUT_LEVELS):
        seeds = [10000 + lvl_idx * 100 + t for t in range(trials)]
        run_batch("pure_dropout", "sample_medium.txt", med_data, dr, 0.0, seeds)

    # Kịch bản B: Hỗn hợp Dropout (0/5/10/15/20%) + Substitution 0.1%/base trên sample_medium.txt
    for lvl_idx, dr in enumerate(DROPOUT_LEVELS):
        seeds = [20000 + lvl_idx * 100 + t for t in range(trials)]
        run_batch("mixed_dropout_sub_01pct", "sample_medium.txt", med_data, dr, 0.001, seeds)

    # Kịch bản C: Quét Substitution (0 / 0.1 / 0.5 / 1.0 / 2.0%/base) tại Dropout 0%
    for lvl_idx, sr in enumerate(SUB_LEVELS):
        seeds = [30000 + lvl_idx * 100 + t for t in range(trials)]
        run_batch("pure_substitution", "sample_medium.txt", med_data, 0.0, sr, seeds)

    # Kịch bản D: Ảnh hưởng kích thước tệp TXT (ngắn 166 B / vừa 800 B / dài 1.955 B) tại dropout 5% + sub 0.1%
    seeds_sz = [40000 + t for t in range(trials)]
    for fname, raw in samples.items():
        run_batch("txt_size_scaling_5pct_01pct", fname, raw, 0.05, 0.001, seeds_sz)

    # Tổng hợp
    grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r["scenario"], r["filename"], r["file_size_bytes"], r["ecc_mode"], r["dropout_rate"], r["substitution_rate"])
        grouped[key].append(r)

    summary_rows: list[dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        scen, fname, fsize, mode, dr, sr = key
        items = grouped[key]
        n = len(items)
        succ = sum(1 for x in items if x["success"] and x["sha256_match"])
        summary_rows.append({
            "scenario": scen,
            "filename": fname,
            "file_size_bytes": fsize,
            "ecc_mode": mode,
            "dropout_rate_pct": round(dr * 100.0, 2),
            "substitution_rate_pct": round(sr * 100.0, 3),
            "trials": n,
            "success_count": succ,
            "recovery_rate_pct": round((succ / n) * 100.0, 2),
            "avg_packets_lost": round(sum(x["n_packets_lost"] for x in items) / n, 2),
            "avg_substituted_bases": round(sum(x["n_substituted_bases"] for x in items) / n, 2),
            "overhead_pct": items[0]["overhead_pct"],
            "avg_elapsed_ms": round(sum(x["elapsed_ms"] for x in items) / n, 3),
        })

    # Ghi CSV
    for path, data_rows in (
        (output_dir / "benchmark_results.csv", rows),
        (output_dir / "benchmark_summary.csv", summary_rows),
    ):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data_rows[0].keys()))
            writer.writeheader()
            writer.writerows(data_rows)

    # Ghi điều kiện thực nghiệm
    conditions = {
        "pipeline": "dnastore.orchestrator.run_simulation",
        "backends": be.sources,
        "python_version": sys.version,
        "platform": platform.platform(),
        "trials_per_level": trials,
        "total_runs": len(rows),
        "chunk_size": CHUNK_SIZE,
        "group_size": GROUP_SIZE,
        "replication_copies": COPIES,
        "sample_files": [
            {"filename": k, "size_bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()}
            for k, v in samples.items()
        ],
    }
    (output_dir / "experiment_conditions.json").write_text(
        json.dumps(conditions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    generate_charts(summary_rows, output_dir, trials)
    return rows, summary_rows


def generate_charts(summary_rows: list[dict[str, Any]], output_dir: Path, trials: int) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Không có matplotlib - bỏ qua bước vẽ biểu đồ PNG.")
        return

    colors = {
        "NONE": "#D62728",
        "XOR_PARITY": "#1F77B4",
        "REPLICATION_3X": "#E67E22",
        "HYBRID": "#16A085",
    }
    markers = {"NONE": "o", "XOR_PARITY": "s", "REPLICATION_3X": "^", "HYBRID": "D"}
    labels = {
        "NONE": "NONE (Không dự phòng)",
        "XOR_PARITY": "XOR_PARITY (4+1)",
        "REPLICATION_3X": "REPLICATION_3X (3 bản sao)",
        "HYBRID": "HYBRID (XOR + 3 bản sao)",
    }

    # Biểu đồ 1: Dropout thuần & Hỗn hợp (sample_medium.txt)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0), sharey=True)
    for ax, scen, title in (
        (axes[0], "pure_dropout", f"A. Chỉ Dropout (sub = 0%, {trials} seeds/mức)"),
        (axes[1], "mixed_dropout_sub_01pct", f"B. Dropout + Substitution 0.1%/base ({trials} seeds/mức)"),
    ):
        for mode in ECC_MODES:
            pts = sorted(
                [r for r in summary_rows if r["scenario"] == scen and r["ecc_mode"] == mode],
                key=lambda x: x["dropout_rate_pct"],
            )
            ax.plot(
                [p["dropout_rate_pct"] for p in pts],
                [p["recovery_rate_pct"] for p in pts],
                marker=markers[mode],
                linewidth=2.2,
                markersize=6.5,
                color=colors[mode],
                label=labels[mode],
            )
        ax.set_title(title, fontsize=11.2, fontweight="bold", pad=10)
        ax.set_xlabel("Tỷ lệ Dropout (%)", fontsize=10.2)
        ax.set_xticks([0, 5, 10, 15, 20])
        ax.set_ylim(-5, 107)
        ax.grid(True, linestyle="--", alpha=0.45)

    axes[0].set_ylabel("Tỷ lệ tái tạo toàn tệp thành công (%)", fontsize=10.2)
    axes[0].legend(loc="lower left", frameon=True, fontsize=8.8)
    fig.suptitle(
        "Hệ thống tích hợp (backends=real): Tỷ lệ tái tạo tệp theo mức Dropout (sample_medium.txt, 800 B)",
        fontsize=12.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(output_dir / "chart_dropout_recovery.png", dpi=180)
    plt.close(fig)

    # Biểu đồ 2: Quét Substitution & Overhead / Runtime
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0))
    ax0, ax1 = axes[0], axes[1]
    for mode in ECC_MODES:
        pts = sorted(
            [r for r in summary_rows if r["scenario"] == "pure_substitution" and r["ecc_mode"] == mode],
            key=lambda x: x["substitution_rate_pct"],
        )
        ax0.plot(
            [p["substitution_rate_pct"] for p in pts],
            [p["recovery_rate_pct"] for p in pts],
            marker=markers[mode],
            linewidth=2.2,
            markersize=6.5,
            color=colors[mode],
            label=labels[mode],
        )
    ax0.set_title("C. Khả năng chống Substitution (dropout = 0%)", fontsize=11.2, fontweight="bold", pad=10)
    ax0.set_xlabel("Tỷ lệ Substitution (%/base)", fontsize=10.2)
    ax0.set_ylabel("Tỷ lệ tái tạo toàn tệp (%)", fontsize=10.2)
    ax0.set_xticks([0.0, 0.1, 0.5, 1.0, 2.0])
    ax0.set_ylim(-5, 107)
    ax0.grid(True, linestyle="--", alpha=0.45)
    ax0.legend(loc="center", bbox_to_anchor=(0.50, 0.26), frameon=True, fontsize=8.0, facecolor="white", framealpha=0.95)

    # Panel D: So sánh 3 kích thước TXT tại 5% dropout + 0.1% sub
    file_order = ["sample_short.txt", "sample_medium.txt", "sample_long.txt"]
    file_labels = ["Ngắn\n(166 B)", "Vừa\n(800 B)", "Dài\n(1.955 B)"]
    x_pos = list(range(len(file_order)))
    width = 0.19
    for idx, mode in enumerate(ECC_MODES):
        vals = []
        for fn in file_order:
            match = [
                r["recovery_rate_pct"]
                for r in summary_rows
                if r["scenario"] == "txt_size_scaling_5pct_01pct" and r["filename"] == fn and r["ecc_mode"] == mode
            ]
            vals.append(match[0] if match else 0.0)
        offsets = [x + (idx - 1.5) * width for x in x_pos]
        bars = ax1.bar(offsets, vals, width=width, color=colors[mode], label=mode, edgecolor="#222222", linewidth=0.6)
        for bar, val in zip(bars, vals):
            if val > 0:
                ax1.text(bar.get_x() + bar.get_width() / 2.0, val + 1.8, f"{val:.0f}%", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
    ax1.set_title("D. Ảnh hưởng kích thước tệp TXT (5% drop + 0.1% sub)", fontsize=11.2, fontweight="bold", pad=10)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(file_labels, fontsize=9.8)
    ax1.set_ylabel("Tỷ lệ tái tạo toàn tệp (%)", fontsize=10.2)
    ax1.set_ylim(0, 128)
    ax1.grid(axis="y", linestyle="--", alpha=0.45)
    ax1.legend(loc="upper center", ncol=2, frameon=True, fontsize=8.0, facecolor="white", framealpha=0.95)

    fig.suptitle(
        f"Đánh giá chống Substitution & Ảnh hưởng kích thước tệp TXT (backends=real, {trials} seeds/mức)",
        fontsize=12.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(output_dir / "chart_substitution_scaling.png", dpi=180)
    plt.close(fig)


def main() -> int:
    # Bảo đảm help và các thông báo tiếng Việt in được trên PowerShell Windows.
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=30, help="Số seed mỗi mức nhiễu (tối thiểu 30)")
    ap.add_argument("--output", type=Path, default=RESULTS_DIR)
    args = ap.parse_args()
    if args.trials < 30:
        ap.error("Cần tối thiểu 30 trials/mức theo kế hoạch 14 ngày.")
    rows, summary = run_benchmark(trials=args.trials, output_dir=args.output)
    print(f"Hoàn tất benchmark tích hợp: {len(rows)} lượt chạy -> {args.output / 'benchmark_results.csv'}")
    for scen in ("pure_dropout", "mixed_dropout_sub_01pct", "pure_substitution", "txt_size_scaling_5pct_01pct"):
        print(f"\n[{scen}]")
        for r in summary:
            if r["scenario"] == scen:
                print(
                    f"  {r['filename']:17s} | {r['ecc_mode']:14s} | drop={r['dropout_rate_pct']:4.1f}% | "
                    f"sub={r['substitution_rate_pct']:5.3f}% | rec={r['recovery_rate_pct']:6.2f}% | "
                    f"ovh={r['overhead_pct']:6.2f}% | avg={r['avg_elapsed_ms']:6.2f} ms"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
