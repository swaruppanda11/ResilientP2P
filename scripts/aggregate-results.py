#!/usr/bin/env python3
"""
Aggregate repeated-run K8s experiment results into summary tables.

Reads from:
  p2p-coordinator/experiments/results-k8s-multi/run-*/
  p2p-dht/experiments/results-k8s-multi/run-*/

Outputs:
  results-aggregate/aggregate-summary.json   — machine-readable summary
  results-aggregate/aggregate-summary.md     — markdown comparison tables

Usage:
  python3 scripts/aggregate-results.py                     # default
  python3 scripts/aggregate-results.py --runs-dir custom   # override run dirname pattern
"""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
COORD_EXP = REPO_ROOT / "p2p-coordinator" / "experiments"
DHT_EXP = REPO_ROOT / "p2p-dht" / "experiments"

# Scenarios that appear in both stacks with identical names (core workloads).
CORE_SCENARIOS = [
    "Explicit Locality Smoke Test",
    "Course Burst Workload",
    "Burst With Independent Churn",
    "Correlated Class Exit Churn",
]

# Failure scenarios are stack-specific but paired for comparison.
FAILURE_SCENARIO_PAIRS = [
    ("Coordinator Failure Fallback Smoke Test", "DHT Failure Fallback Smoke Test"),
    ("Coordinator Partition Fallback Test", "DHT Partition Fallback Test"),
    ("Coordinator Timeout Fallback Test", "DHT Timeout Fallback Test"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def discover_runs(exp_dir: Path, multi_dir: str = "results-k8s-multi") -> List[Path]:
    """Return sorted list of run directories under the multi-run output."""
    base = exp_dir / multi_dir
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("run-"))


def load_scenario(run_dir: Path, scenario_slug: str) -> Dict[str, Any] | None:
    """Load a single scenario result JSON from a run directory."""
    path = run_dir / f"{scenario_slug}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


def mean_std(values: Sequence[float]) -> Tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    m = statistics.mean(values)
    s = statistics.pstdev(values) if len(values) > 1 else 0.0
    return (m, s)


def ci95(values: Sequence[float]) -> Tuple[float, float]:
    """Return (lower, upper) of a 95% confidence interval (t-distribution)."""
    if len(values) < 2:
        m = values[0] if values else 0.0
        return (m, m)
    m = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(len(values))
    # t critical value for 95% CI, approximated for small n
    t_crit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776,
              6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}
    t = t_crit.get(len(values), 1.96)
    margin = t * se
    return (m - margin, m + margin)


def fmt(val: float, decimals: int = 2) -> str:
    return f"{val:.{decimals}f}"


def fmt_pm(m: float, s: float, decimals: int = 2) -> str:
    """Format as mean +/- std."""
    if s < 0.005:
        return fmt(m, decimals)
    return f"{fmt(m, decimals)} +/- {fmt(s, decimals)}"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_scenario_across_runs(
    runs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate the summary section across multiple runs of the same scenario."""
    summaries = [r["summary"] for r in runs]

    # Success rate
    success_rates = [s["success_rate"] for s in summaries]

    # Latency stats (we aggregate the per-run summary stats)
    svc_means = [s["service_latency_ms"]["mean"] for s in summaries]
    svc_medians = [s["service_latency_ms"]["median"] for s in summaries]
    svc_p95s = [s["service_latency_ms"]["p95"] for s in summaries]
    svc_maxes = [s["service_latency_ms"]["max"] for s in summaries]

    # Source counts
    all_sources = set()
    for s in summaries:
        all_sources.update(s["source_counts"].keys())
    source_agg = {}
    for source in sorted(all_sources):
        vals = [s["source_counts"].get(source, 0) for s in summaries]
        source_agg[source] = {"mean": statistics.mean(vals), "std": statistics.pstdev(vals)}

    # Bytes by source
    bytes_agg = {}
    for source in sorted(all_sources):
        vals = [s["bytes_by_source"].get(source, 0) for s in summaries]
        bytes_agg[source] = {"mean": statistics.mean(vals), "std": statistics.pstdev(vals)}

    # Fetch counts
    fetch_counts = [s["fetch_count"] for s in summaries]
    success_counts = [s["successful_fetch_count"] for s in summaries]
    failed_counts = [s["failed_fetch_count"] for s in summaries]

    # Bandwidth reduction: (total_peer_and_cache_bytes) / (total_all_bytes)
    bw_reductions = []
    for s in summaries:
        total = sum(s["bytes_by_source"].values())
        origin = s["bytes_by_source"].get("origin", 0)
        if total > 0:
            bw_reductions.append((total - origin) / total)
        else:
            bw_reductions.append(0.0)

    return {
        "num_runs": len(runs),
        "success_rate": {"mean": statistics.mean(success_rates), "std": statistics.pstdev(success_rates)},
        "fetch_count": {"mean": statistics.mean(fetch_counts), "std": statistics.pstdev(fetch_counts)},
        "successful_fetch_count": {"mean": statistics.mean(success_counts), "std": statistics.pstdev(success_counts)},
        "failed_fetch_count": {"mean": statistics.mean(failed_counts), "std": statistics.pstdev(failed_counts)},
        "service_latency_ms": {
            "mean": {"mean": statistics.mean(svc_means), "std": statistics.pstdev(svc_means)},
            "median": {"mean": statistics.mean(svc_medians), "std": statistics.pstdev(svc_medians)},
            "p95": {"mean": statistics.mean(svc_p95s), "std": statistics.pstdev(svc_p95s)},
            "max": {"mean": statistics.mean(svc_maxes), "std": statistics.pstdev(svc_maxes)},
        },
        "source_counts": source_agg,
        "bytes_by_source": bytes_agg,
        "bandwidth_reduction": {"mean": statistics.mean(bw_reductions), "std": statistics.pstdev(bw_reductions)},
    }


def collect_stack_data(
    exp_dir: Path, multi_dir: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Load all runs for a stack, grouped by scenario name."""
    runs = discover_runs(exp_dir, multi_dir)
    if not runs:
        return {}

    by_scenario: Dict[str, List[Dict[str, Any]]] = {}
    for run_dir in runs:
        for result_file in sorted(run_dir.glob("*.json")):
            with result_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            name = data["scenario"]
            by_scenario.setdefault(name, []).append(data)

    return by_scenario


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def generate_markdown(
    coord_agg: Dict[str, Dict],
    dht_agg: Dict[str, Dict],
    num_runs_coord: int,
    num_runs_dht: int,
) -> str:
    lines: List[str] = []
    lines.append("# Aggregate Cloud Results")
    lines.append("")
    lines.append(f"Coordinator stack: **{num_runs_coord}** run(s)  ")
    lines.append(f"DHT stack: **{num_runs_dht}** run(s)")
    lines.append("")
    lines.append("All values shown as **mean +/- std** across runs.")
    lines.append("")

    # --- Core workload table ---
    lines.append("## Core Workload Comparison")
    lines.append("")
    lines.append(
        "| Scenario | Stack | Success Rate | Mean Latency (ms) | Median Latency (ms) "
        "| p95 Latency (ms) | Sources | BW Reduction |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|---:|")

    for scenario in CORE_SCENARIOS:
        for label, agg in [("Coord", coord_agg), ("DHT", dht_agg)]:
            if scenario not in agg:
                continue
            a = agg[scenario]
            sr = fmt_pm(a["success_rate"]["mean"], a["success_rate"]["std"])
            ml = fmt_pm(a["service_latency_ms"]["mean"]["mean"], a["service_latency_ms"]["mean"]["std"])
            md = fmt_pm(a["service_latency_ms"]["median"]["mean"], a["service_latency_ms"]["median"]["std"])
            p95 = fmt_pm(a["service_latency_ms"]["p95"]["mean"], a["service_latency_ms"]["p95"]["std"])
            src_parts = []
            for source in ["origin", "peer", "cache"]:
                if source in a["source_counts"]:
                    sc = a["source_counts"][source]
                    src_parts.append(f"{source}={fmt(sc['mean'], 1)}")
            sources = ", ".join(src_parts)
            bw = fmt_pm(a["bandwidth_reduction"]["mean"] * 100, a["bandwidth_reduction"]["std"] * 100, 1)
            lines.append(f"| {scenario} | {label} | {sr} | {ml} | {md} | {p95} | {sources} | {bw}% |")

    lines.append("")

    # --- Failure injection table ---
    lines.append("## Failure Injection Comparison")
    lines.append("")
    lines.append(
        "| Scenario | Stack | Success Rate | Mean Latency (ms) | Median Latency (ms) "
        "| p95 Latency (ms) | Sources |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")

    for coord_name, dht_name in FAILURE_SCENARIO_PAIRS:
        for label, name, agg in [("Coord", coord_name, coord_agg), ("DHT", dht_name, dht_agg)]:
            if name not in agg:
                continue
            a = agg[name]
            sr = fmt_pm(a["success_rate"]["mean"], a["success_rate"]["std"])
            ml = fmt_pm(a["service_latency_ms"]["mean"]["mean"], a["service_latency_ms"]["mean"]["std"])
            md = fmt_pm(a["service_latency_ms"]["median"]["mean"], a["service_latency_ms"]["median"]["std"])
            p95 = fmt_pm(a["service_latency_ms"]["p95"]["mean"], a["service_latency_ms"]["p95"]["std"])
            src_parts = []
            for source in ["origin", "peer", "cache"]:
                if source in a["source_counts"]:
                    sc = a["source_counts"][source]
                    src_parts.append(f"{source}={fmt(sc['mean'], 1)}")
            sources = ", ".join(src_parts)
            lines.append(f"| {name} | {label} | {sr} | {ml} | {md} | {p95} | {sources} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/aggregate-results.py`")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate repeated-run K8s results")
    parser.add_argument(
        "--multi-dir", default="results-k8s-multi",
        help="Name of the multi-run results directory (default: results-k8s-multi)",
    )
    parser.add_argument(
        "--output-dir", default=str(REPO_ROOT / "results-aggregate"),
        help="Directory for aggregate output files",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect data
    coord_data = collect_stack_data(COORD_EXP, args.multi_dir)
    dht_data = collect_stack_data(DHT_EXP, args.multi_dir)

    if not coord_data and not dht_data:
        # Fall back to single-run results-k8s/ if no multi-run data exists
        print("No multi-run data found. Falling back to single-run results-k8s/...")
        coord_data = collect_stack_data_single(COORD_EXP, "results-k8s")
        dht_data = collect_stack_data_single(DHT_EXP, "results-k8s")
        if not coord_data and not dht_data:
            print("ERROR: No result data found in either multi-run or single-run directories.", file=sys.stderr)
            sys.exit(1)

    # Aggregate each scenario
    coord_agg: Dict[str, Dict] = {}
    for name, runs in coord_data.items():
        coord_agg[name] = aggregate_scenario_across_runs(runs)

    dht_agg: Dict[str, Dict] = {}
    for name, runs in dht_data.items():
        dht_agg[name] = aggregate_scenario_across_runs(runs)

    # Determine run counts
    num_coord = max((a["num_runs"] for a in coord_agg.values()), default=0)
    num_dht = max((a["num_runs"] for a in dht_agg.values()), default=0)

    # Write JSON summary
    summary = {
        "coordinator": coord_agg,
        "dht": dht_agg,
        "meta": {
            "coordinator_runs": num_coord,
            "dht_runs": num_dht,
            "multi_dir": args.multi_dir,
        },
    }
    json_path = output_dir / "aggregate-summary.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"[+] Wrote {json_path}")

    # Write markdown summary
    md = generate_markdown(coord_agg, dht_agg, num_coord, num_dht)
    md_path = output_dir / "aggregate-summary.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write(md)
    print(f"[+] Wrote {md_path}")

    # Also print the markdown to stdout for quick review
    print()
    print(md)


def collect_stack_data_single(
    exp_dir: Path, results_dir: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Load results from a flat single-run directory (fallback)."""
    base = exp_dir / results_dir
    if not base.exists():
        return {}
    by_scenario: Dict[str, List[Dict[str, Any]]] = {}
    for result_file in sorted(base.glob("*.json")):
        with result_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        name = data["scenario"]
        by_scenario.setdefault(name, []).append(data)
    return by_scenario


if __name__ == "__main__":
    main()
