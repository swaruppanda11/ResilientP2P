#!/usr/bin/env python3
"""
Generate comparison plots from aggregated experiment results.

Reads:  results-aggregate/aggregate-summary.json
Writes: results-aggregate/plots/*.png

Plots generated:
  1. source-distribution.png  — stacked bar: origin/peer/cache per scenario
  2. latency-comparison.png   — grouped bar: mean, median, p95 per scenario
  3. bandwidth-reduction.png  — bar chart of BW reduction per scenario
  4. failure-latency.png      — grouped bar: failure scenario latencies

Usage:
  python3 scripts/plot-results.py
  python3 scripts/plot-results.py --input results-aggregate/aggregate-summary.json

Requires: matplotlib (pip install matplotlib)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
except ImportError:
    print("ERROR: matplotlib is required. Install with: pip install matplotlib", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent

CORE_SCENARIOS = [
    "Explicit Locality Smoke Test",
    "Course Burst Workload",
    "Burst With Independent Churn",
    "Correlated Class Exit Churn",
]

CORE_SHORT_NAMES = [
    "Locality\nSmoke",
    "Course\nBurst",
    "Indep.\nChurn",
    "Correlated\nChurn",
]

FAILURE_SCENARIO_PAIRS = [
    ("Coordinator Failure Fallback Smoke Test", "DHT Failure Fallback Smoke Test", "Crash\nFallback"),
    ("Coordinator Partition Fallback Test", "DHT Partition Fallback Test", "Partition\nFallback"),
    ("Coordinator Timeout Fallback Test", "DHT Timeout Fallback Test", "Timeout\nFallback"),
]

COORD_COLOR = "#2196F3"
DHT_COLOR = "#FF9800"
ORIGIN_COLOR = "#E53935"
PEER_COLOR = "#43A047"
CACHE_COLOR = "#1E88E5"


def get_val(agg: Dict, scenario: str, *keys: str, default: float = 0.0) -> float:
    """Safely navigate nested aggregate dict."""
    node: Any = agg.get(scenario)
    if node is None:
        return default
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key, default)
        else:
            return default
    return float(node) if node is not None else default


# ---------------------------------------------------------------------------
# Plot 1: Source Distribution
# ---------------------------------------------------------------------------

def plot_source_distribution(coord: Dict, dht: Dict, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, (label, agg, color_accent) in zip(
        axes, [("Coordinator-Primary", coord, COORD_COLOR), ("DHT-Primary", dht, DHT_COLOR)]
    ):
        origins, peers, caches = [], [], []
        for scenario in CORE_SCENARIOS:
            origins.append(get_val(agg, scenario, "source_counts", "origin", "mean"))
            peers.append(get_val(agg, scenario, "source_counts", "peer", "mean"))
            caches.append(get_val(agg, scenario, "source_counts", "cache", "mean"))

        x = range(len(CORE_SCENARIOS))
        ax.bar(x, origins, label="origin", color=ORIGIN_COLOR, alpha=0.85)
        ax.bar(x, peers, bottom=origins, label="peer", color=PEER_COLOR, alpha=0.85)
        bottoms = [o + p for o, p in zip(origins, peers)]
        ax.bar(x, caches, bottom=bottoms, label="cache", color=CACHE_COLOR, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(CORE_SHORT_NAMES, fontsize=9)
        ax.set_ylabel("Request Count (mean)")
        ax.set_title(label)
        ax.legend(loc="upper right", fontsize=8)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    fig.suptitle("Source Distribution per Scenario", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    path = output_dir / "source-distribution.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[+] {path}")


# ---------------------------------------------------------------------------
# Plot 2: Latency Comparison
# ---------------------------------------------------------------------------

def plot_latency_comparison(coord: Dict, dht: Dict, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)
    metrics = [
        ("mean", "Mean Latency (ms)"),
        ("median", "Median Latency (ms)"),
        ("p95", "p95 Latency (ms)"),
    ]

    bar_width = 0.35
    x = range(len(CORE_SCENARIOS))

    for ax, (metric_key, title) in zip(axes, metrics):
        coord_vals = [get_val(coord, s, "service_latency_ms", metric_key, "mean") for s in CORE_SCENARIOS]
        coord_errs = [get_val(coord, s, "service_latency_ms", metric_key, "std") for s in CORE_SCENARIOS]
        dht_vals = [get_val(dht, s, "service_latency_ms", metric_key, "mean") for s in CORE_SCENARIOS]
        dht_errs = [get_val(dht, s, "service_latency_ms", metric_key, "std") for s in CORE_SCENARIOS]

        x_coord = [i - bar_width / 2 for i in x]
        x_dht = [i + bar_width / 2 for i in x]

        ax.bar(x_coord, coord_vals, bar_width, yerr=coord_errs, label="Coordinator",
               color=COORD_COLOR, alpha=0.85, capsize=3)
        ax.bar(x_dht, dht_vals, bar_width, yerr=dht_errs, label="DHT",
               color=DHT_COLOR, alpha=0.85, capsize=3)

        ax.set_xticks(x)
        ax.set_xticklabels(CORE_SHORT_NAMES, fontsize=8)
        ax.set_ylabel("Latency (ms)")
        ax.set_title(title)
        ax.legend(fontsize=8)

    fig.suptitle("Service Latency Comparison — Core Workloads", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    path = output_dir / "latency-comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[+] {path}")


# ---------------------------------------------------------------------------
# Plot 3: Bandwidth Reduction
# ---------------------------------------------------------------------------

def plot_bandwidth_reduction(coord: Dict, dht: Dict, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))

    bar_width = 0.35
    x = range(len(CORE_SCENARIOS))

    coord_vals = [get_val(coord, s, "bandwidth_reduction", "mean") * 100 for s in CORE_SCENARIOS]
    coord_errs = [get_val(coord, s, "bandwidth_reduction", "std") * 100 for s in CORE_SCENARIOS]
    dht_vals = [get_val(dht, s, "bandwidth_reduction", "mean") * 100 for s in CORE_SCENARIOS]
    dht_errs = [get_val(dht, s, "bandwidth_reduction", "std") * 100 for s in CORE_SCENARIOS]

    x_coord = [i - bar_width / 2 for i in x]
    x_dht = [i + bar_width / 2 for i in x]

    ax.bar(x_coord, coord_vals, bar_width, yerr=coord_errs, label="Coordinator",
           color=COORD_COLOR, alpha=0.85, capsize=3)
    ax.bar(x_dht, dht_vals, bar_width, yerr=dht_errs, label="DHT",
           color=DHT_COLOR, alpha=0.85, capsize=3)

    ax.set_xticks(x)
    ax.set_xticklabels(CORE_SHORT_NAMES, fontsize=9)
    ax.set_ylabel("Bandwidth Reduction (%)")
    ax.set_title("External Bandwidth Reduction per Scenario", fontsize=13, fontweight="bold")
    ax.legend()
    ax.set_ylim(0, 100)
    ax.axhline(y=60, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axhline(y=75, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.text(len(CORE_SCENARIOS) - 0.5, 61, "60% target", fontsize=7, color="gray")
    ax.text(len(CORE_SCENARIOS) - 0.5, 76, "75% target", fontsize=7, color="gray")

    fig.tight_layout()
    path = output_dir / "bandwidth-reduction.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[+] {path}")


# ---------------------------------------------------------------------------
# Plot 4: Failure Scenario Latencies
# ---------------------------------------------------------------------------

def plot_failure_latency(coord: Dict, dht: Dict, output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    bar_width = 0.35

    for ax, (metric_key, title) in zip(axes, [("mean", "Mean Latency"), ("median", "Median Latency")]):
        short_names = [pair[2] for pair in FAILURE_SCENARIO_PAIRS]
        x = range(len(FAILURE_SCENARIO_PAIRS))

        coord_vals = [
            get_val(coord, pair[0], "service_latency_ms", metric_key, "mean")
            for pair in FAILURE_SCENARIO_PAIRS
        ]
        coord_errs = [
            get_val(coord, pair[0], "service_latency_ms", metric_key, "std")
            for pair in FAILURE_SCENARIO_PAIRS
        ]
        dht_vals = [
            get_val(dht, pair[1], "service_latency_ms", metric_key, "mean")
            for pair in FAILURE_SCENARIO_PAIRS
        ]
        dht_errs = [
            get_val(dht, pair[1], "service_latency_ms", metric_key, "std")
            for pair in FAILURE_SCENARIO_PAIRS
        ]

        x_coord = [i - bar_width / 2 for i in x]
        x_dht = [i + bar_width / 2 for i in x]

        ax.bar(x_coord, coord_vals, bar_width, yerr=coord_errs, label="Coordinator",
               color=COORD_COLOR, alpha=0.85, capsize=3)
        ax.bar(x_dht, dht_vals, bar_width, yerr=dht_errs, label="DHT",
               color=DHT_COLOR, alpha=0.85, capsize=3)

        ax.set_xticks(x)
        ax.set_xticklabels(short_names, fontsize=9)
        ax.set_ylabel("Latency (ms)")
        ax.set_title(f"{title} (ms)")
        ax.legend(fontsize=8)

    fig.suptitle("Failure-Injection Scenario Latencies", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    path = output_dir / "failure-latency.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"[+] {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate comparison plots")
    parser.add_argument(
        "--input",
        default=str(REPO_ROOT / "results-aggregate" / "aggregate-summary.json"),
        help="Path to aggregate-summary.json",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "results-aggregate" / "plots"),
        help="Directory for plot PNGs",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run aggregate-results.py first.", file=sys.stderr)
        sys.exit(1)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    coord = data["coordinator"]
    dht = data["dht"]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_source_distribution(coord, dht, output_dir)
    plot_latency_comparison(coord, dht, output_dir)
    plot_bandwidth_reduction(coord, dht, output_dir)
    plot_failure_latency(coord, dht, output_dir)

    print(f"\n[+] All plots saved to {output_dir}/")


if __name__ == "__main__":
    main()
