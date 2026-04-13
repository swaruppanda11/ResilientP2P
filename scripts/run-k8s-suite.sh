#!/usr/bin/env bash
#
# Run the full 7-scenario K8s experiment suite N times for both stacks.
#
# Each run saves results to a separate subdirectory:
#   p2p-coordinator/experiments/results-k8s-multi/run-001/
#   p2p-dht/experiments/results-k8s-multi/run-001/
#
# Prerequisites:
#   - kubectl configured for the resilientp2p-gke cluster
#   - Both stacks deployed (pods running in p2p-coordinator and p2p-dht namespaces)
#   - Python 3 with httpx installed
#   - jq installed
#
# Usage:
#   ./scripts/run-k8s-suite.sh              # 5 runs, same seed (measure infra variance)
#   ./scripts/run-k8s-suite.sh 10           # 10 runs
#   ./scripts/run-k8s-suite.sh 5 --vary-seed  # 5 runs, seed changes per run
#
set -euo pipefail

RUNS="${1:-5}"
VARY_SEED=false
for arg in "$@"; do
  [[ "$arg" == "--vary-seed" ]] && VARY_SEED=true
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_EXP="${REPO_ROOT}/p2p-coordinator/experiments"
DHT_EXP="${REPO_ROOT}/p2p-dht/experiments"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ "$PYTHON_BIN" == */* && "$PYTHON_BIN" != /* ]]; then
  PYTHON_BIN="${REPO_ROOT}/${PYTHON_BIN}"
fi

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
for cmd in kubectl jq "$PYTHON_BIN"; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is not installed or not on PATH" >&2
    exit 1
  fi
done

echo "==> Preflight: checking cluster access"
if ! kubectl get pods -n p2p-coordinator &>/dev/null; then
  echo "ERROR: cannot reach p2p-coordinator pods — is your kubeconfig set and RBAC granted?" >&2
  exit 1
fi
if ! kubectl get pods -n p2p-dht &>/dev/null; then
  echo "ERROR: cannot reach p2p-dht pods — check kubeconfig/RBAC" >&2
  exit 1
fi

echo "==> Starting ${RUNS} run(s)  (vary-seed=${VARY_SEED})"
echo

# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------
run_stack() {
  local stack="$1"          # "coordinator" or "dht"
  local exp_dir="$2"        # path to experiments/ dir
  local run_dir="$3"        # e.g. "run-001"
  local seed_override="$4"  # "" for no override, else integer

  local base_config="${exp_dir}/workload-k8s.json"
  local tmp_config="${exp_dir}/.workload-k8s-run.json"

  # Build per-run config: override results_dir (and optionally seed)
  if [[ -n "$seed_override" ]]; then
    jq --arg dir "results-k8s-multi/${run_dir}" \
       --argjson seed "$seed_override" \
       '.results_dir = $dir | .seed = $seed' \
       "$base_config" > "$tmp_config"
  else
    jq --arg dir "results-k8s-multi/${run_dir}" \
       '.results_dir = $dir' \
       "$base_config" > "$tmp_config"
  fi

  echo "    [${stack}] results -> results-k8s-multi/${run_dir}/"
  if (cd "$exp_dir" && PYTHONUNBUFFERED=1 "$PYTHON_BIN" runner.py "$tmp_config"); then
    rm -f "$tmp_config"
    return 0
  fi

  rm -f "$tmp_config"
  return 1
}

FAILED=0
for i in $(seq 1 "$RUNS"); do
  RUN_DIR=$(printf "run-%03d" "$i")
  echo "=== Run ${i} of ${RUNS} (${RUN_DIR}) ==="

  SEED_ARG=""
  if [[ "$VARY_SEED" == "true" ]]; then
    SEED_ARG="$((41 + i))"
    echo "    seed=${SEED_ARG}"
  fi

  # --- Coordinator stack ---
  echo "  -> Coordinator stack"
  if ! run_stack "coordinator" "$COORD_EXP" "$RUN_DIR" "$SEED_ARG"; then
    echo "  !! Coordinator stack failed on ${RUN_DIR}" >&2
    FAILED=$((FAILED + 1))
  fi

  # --- DHT stack ---
  echo "  -> DHT stack"
  if ! run_stack "dht" "$DHT_EXP" "$RUN_DIR" "$SEED_ARG"; then
    echo "  !! DHT stack failed on ${RUN_DIR}" >&2
    FAILED=$((FAILED + 1))
  fi

  echo
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "==> Done. ${RUNS} run(s) completed, ${FAILED} failure(s)."
echo
echo "Result directories:"
echo "  ${COORD_EXP}/results-k8s-multi/"
echo "  ${DHT_EXP}/results-k8s-multi/"
echo
echo "Next steps:"
echo "  python3 scripts/aggregate-results.py           # build summary tables"
echo "  python3 scripts/plot-results.py                 # generate comparison plots"
echo "  ./scripts/export-to-gcs.sh                      # upload to GCS"
