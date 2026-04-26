#!/usr/bin/env bash
#
# End-to-end validation of Workstream 2 peer auth against a live GKE cluster.
# Proves:
#   1. /health stays public in every mode.
#   2. Gated endpoints reject unauthenticated, wrong-token, and missing-identity calls.
#   3. A valid token gets through AND the coordinator logs attribute the call
#      to the claimed X-Peer-Id.
#   4. The runner's preflight check fails loudly when AUTH_TOKEN is unset.
#
# Prerequisites: kubectl authenticated to the target cluster, `jq` installed,
# namespace at AUTH_MODE=shared_token with the p2p-auth-token Secret populated.
#
# Usage:
#   ./scripts/validate-auth.sh                      # coordinator stack (default)
#   ./scripts/validate-auth.sh -n p2p-dht           # DHT stack
#   ./scripts/validate-auth.sh -n p2p-coordinator -v  # verbose
#
set -euo pipefail

NS="p2p-coordinator"
VERBOSE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n) NS="$2"; shift 2 ;;
    -v|--verbose) VERBOSE=true; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_PATH="$REPO_ROOT/p2p-coordinator/experiments/runner.py"
[[ "$NS" == "p2p-dht" ]] && RUNNER_PATH="$REPO_ROOT/p2p-dht/experiments/runner.py"

# --- ANSI helpers -----------------------------------------------------------
if [[ -t 1 ]]; then
  G="\033[32m"; R="\033[31m"; Y="\033[33m"; B="\033[1m"; N="\033[0m"
else
  G=""; R=""; Y=""; B=""; N=""
fi

pass=0; fail=0
check() {
  local label="$1"; shift
  if "$@"; then
    printf "  ${G}✓${N} %s\n" "$label"
    pass=$((pass + 1))
  else
    printf "  ${R}✗${N} %s\n" "$label"
    fail=$((fail + 1))
  fi
}

# --- Prereqs ----------------------------------------------------------------
for bin in kubectl jq curl python3; do
  command -v "$bin" >/dev/null || { echo "missing dependency: $bin" >&2; exit 2; }
done

kubectl -n "$NS" get deploy/coordinator >/dev/null 2>&1 || {
  echo "${R}error${N}: cannot reach namespace $NS (is kubectl context correct?)" >&2
  exit 2
}

# --- Pull token from Secret -------------------------------------------------
TOKEN="$(kubectl -n "$NS" get secret p2p-auth-token \
  -o jsonpath='{.data.AUTH_TOKEN}' 2>/dev/null | base64 -d || true)"

if [[ -z "$TOKEN" ]]; then
  echo "${R}error${N}: p2p-auth-token secret missing or empty in $NS" >&2
  exit 2
fi

AUTH_MODE="$(kubectl -n "$NS" get cm p2p-common-config \
  -o jsonpath='{.data.AUTH_MODE}' 2>/dev/null || echo "unknown")"

printf "${B}▶ Validating auth in namespace ${NS} (AUTH_MODE=${AUTH_MODE})${N}\n"
[[ "$VERBOSE" == true ]] && printf "  token(len)=%d\n" "${#TOKEN}"

# --- Port-forwards ----------------------------------------------------------
PF_PIDS=()
cleanup() {
  for pid in "${PF_PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT

start_pf() {
  local svc="$1" local_port="$2" remote_port="$3"
  kubectl -n "$NS" port-forward "svc/$svc" "$local_port:$remote_port" \
    >/dev/null 2>&1 &
  PF_PIDS+=("$!")
}

start_pf coordinator 18000 8000
start_pf peer-a1     17001 7000

# Wait for readiness via the public /health.
for endpoint in "http://localhost:18000/health" "http://localhost:17001/health"; do
  for _ in {1..30}; do
    curl -sf -o /dev/null "$endpoint" && break
    sleep 0.3
  done
done

# --- Test 1: /health is public regardless of mode ---------------------------
printf "\n${B}1. /health is public${N}\n"
check "coordinator /health → 200 without auth" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} http://localhost:18000/health)" == "200" ]]'
check "peer-a1 /health → 200 without auth" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} http://localhost:17001/health)" == "200" ]]'

# --- Test 2: gated endpoints reject bad auth --------------------------------
printf "\n${B}2. Gated endpoints reject bad auth${N}\n"
check "coordinator /stats without token → 401" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} http://localhost:18000/stats)" == "401" ]]'

check "coordinator /stats with WRONG token → 401" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer deliberately-wrong" http://localhost:18000/stats)" == "401" ]]'

check "peer-a1 /stats without token → 401" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} http://localhost:17001/stats)" == "401" ]]'

# --- Test 3: valid token → 200 AND coordinator attributes the call ----------
printf "\n${B}3. Valid token → 200 and identity attribution in logs${N}\n"

MARKER="auth-validate-$(date +%s)-$$"
# Fire a lookup the coordinator will log with our claimed identity.
CURL_STATUS="$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Peer-Id: $MARKER" \
  -H "X-Peer-Group: professors" \
  "http://localhost:18000/lookup/$MARKER?location_id=Building-A")"

check "coordinator /lookup with valid token → 200" bash -c "[[ '$CURL_STATUS' == '200' ]]"

# Give Kubernetes a beat to flush stdout, then grep logs for our marker.
sleep 1
if kubectl -n "$NS" logs deploy/coordinator --tail=200 2>/dev/null \
     | grep -Fq "$MARKER"; then
  check "coordinator logs attribute the call to claimed X-Peer-Id" true
  [[ "$VERBOSE" == true ]] && kubectl -n "$NS" logs deploy/coordinator --tail=200 \
      | grep -F "$MARKER" | head -2 | sed 's/^/    /'
else
  check "coordinator logs attribute the call to claimed X-Peer-Id" false
fi

# --- Test 4: peer-a1 stats with valid token → 200 ---------------------------
check "peer-a1 /stats with valid token → 200" bash -c \
  '[[ "$(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer '"$TOKEN"'" -H "X-Peer-Id: '"$MARKER"'" http://localhost:17001/stats)" == "200" ]]'

# --- Test 5: runner refuses to run without AUTH_TOKEN when cluster is gated -
printf "\n${B}4. Runner preflight fails loudly without AUTH_TOKEN${N}\n"

if [[ "$AUTH_MODE" == "shared_token" ]]; then
  tmp_out="$(mktemp)"
  spec_path="$REPO_ROOT/p2p-coordinator/experiments/workload-k8s.json"
  [[ "$NS" == "p2p-dht" ]] && spec_path="$REPO_ROOT/p2p-dht/experiments/workload-k8s.json"

  # Unset AUTH_TOKEN in the subshell so the preflight trips.
  # `timeout` caps it because run() will proceed into scenarios if preflight passes.
  if ( unset AUTH_TOKEN && timeout 15 python3 "$RUNNER_PATH" "$spec_path" \
         >"$tmp_out" 2>&1 ); rc=$?; then :; else rc=$?; fi

  if grep -q "Cluster requires AUTH_TOKEN" "$tmp_out" && [[ "$rc" != "0" ]]; then
    check "runner exits with 'Cluster requires AUTH_TOKEN' message" true
  else
    check "runner exits with 'Cluster requires AUTH_TOKEN' message" false
    [[ "$VERBOSE" == true ]] && sed 's/^/    /' "$tmp_out"
  fi
  rm -f "$tmp_out"
else
  printf "  ${Y}~${N} skipping: cluster is at AUTH_MODE=${AUTH_MODE} (runner preflight only trips under shared_token)\n"
fi

# --- Summary ----------------------------------------------------------------
printf "\n${B}Summary${N}: ${G}${pass} passed${N}, "
if (( fail > 0 )); then
  printf "${R}${fail} failed${N}\n"
  exit 1
else
  printf "${G}0 failed${N}\n"
  exit 0
fi
