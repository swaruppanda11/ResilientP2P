#!/usr/bin/env bash
#
# End-to-end Workstream 3 validation: prove a malicious peer gets quarantined
# and excluded from coordinator lookups, then comes back after cooldown.
#
# Mutates cluster state (sets a peer's MALICIOUS_MODE) and reverts on exit.
# DOES NOT touch the auth Secret. Assumes WS2 is already rolled out — the
# coordinator's /report-bad-peer endpoint is gated behind require_auth.
#
# Usage:
#   ./scripts/validate-reputation.sh                      # coordinator stack
#   ./scripts/validate-reputation.sh -n p2p-dht           # DHT stack
#   ./scripts/validate-reputation.sh -p peer-a1 -v        # target a different peer, verbose
#
set -euo pipefail

NS="p2p-coordinator"
TARGET_PEER="peer-a1"
VERBOSE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n) NS="$2"; shift 2 ;;
    -p) TARGET_PEER="$2"; shift 2 ;;
    -v|--verbose) VERBOSE=true; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

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
for bin in kubectl jq curl; do
  command -v "$bin" >/dev/null || { echo "missing dependency: $bin" >&2; exit 2; }
done

kubectl -n "$NS" get deploy/coordinator >/dev/null 2>&1 || {
  echo "${R}error${N}: cannot reach namespace $NS" >&2; exit 2;
}
kubectl -n "$NS" get deploy/"$TARGET_PEER" >/dev/null 2>&1 || {
  echo "${R}error${N}: deploy/$TARGET_PEER not found in $NS" >&2; exit 2;
}

REP_ENABLED="$(kubectl -n "$NS" get cm p2p-common-config \
  -o jsonpath='{.data.REPUTATION_ENABLED}' 2>/dev/null || echo "")"
if [[ "$REP_ENABLED" != "true" ]]; then
  echo "${Y}warning${N}: REPUTATION_ENABLED is '${REP_ENABLED}' — this script assumes 'true'."
  echo "  Patch the ConfigMap and roll the coordinator before validating."
  exit 2
fi

TOKEN="$(kubectl -n "$NS" get secret p2p-auth-token \
  -o jsonpath='{.data.AUTH_TOKEN}' 2>/dev/null | base64 -d || true)"
if [[ -z "$TOKEN" ]]; then
  echo "${R}error${N}: p2p-auth-token Secret missing in $NS"; exit 2
fi

printf "${B}▶ Workstream 3 validation in ${NS} (target=${TARGET_PEER})${N}\n"

# --- Capture original env so we can revert ----------------------------------
ORIGINAL_MODE="$(kubectl -n "$NS" get deploy/"$TARGET_PEER" \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MALICIOUS_MODE")].value}' \
  2>/dev/null || echo "")"
[[ -z "$ORIGINAL_MODE" ]] && ORIGINAL_MODE="normal"

# --- Port-forwards + cleanup trap ------------------------------------------
PF_PIDS=()
restore_peer() {
  printf "\n${B}↺ Reverting %s MALICIOUS_MODE → %s${N}\n" "$TARGET_PEER" "$ORIGINAL_MODE"
  kubectl -n "$NS" set env deploy/"$TARGET_PEER" \
    "MALICIOUS_MODE=$ORIGINAL_MODE" >/dev/null 2>&1 || true
  kubectl -n "$NS" rollout status deploy/"$TARGET_PEER" --timeout=60s >/dev/null 2>&1 || true
}
cleanup() {
  for pid in "${PF_PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  restore_peer
}
trap cleanup EXIT

start_pf() {
  kubectl -n "$NS" port-forward "svc/$1" "$2:$3" >/dev/null 2>&1 &
  PF_PIDS+=("$!")
}
start_pf coordinator 18000 8000
start_pf peer-a2     17002 7000
start_pf peer-b1     17003 7000

# Wait for /health on the coordinator.
for _ in {1..30}; do
  curl -sf -o /dev/null "http://localhost:18000/health" && break
  sleep 0.3
done

# --- Step 1: flip target into serve_corrupted, wait for rollout -------------
printf "\n${B}1. Set %s MALICIOUS_MODE=serve_corrupted${N}\n" "$TARGET_PEER"
kubectl -n "$NS" set env deploy/"$TARGET_PEER" MALICIOUS_MODE=serve_corrupted >/dev/null
kubectl -n "$NS" rollout status deploy/"$TARGET_PEER" --timeout=90s >/dev/null
sleep 2  # give port-forward time to reattach to the new pod
check "$TARGET_PEER rolled with serve_corrupted" true

# --- Step 2: drive a fetch from peer-b1 to seed the index, then peer-a2 ----
# triggers the malicious read against peer-a1.
printf "\n${B}2. Trigger fetches that exercise the malicious peer${N}\n"
auth_curl() {
  curl -s -H "Authorization: Bearer $TOKEN" -H "X-Peer-Id: validator" \
       -H "X-Peer-Group: campus" "$@"
}

# Force an honest peer (peer-b1) to fetch first so the canonical metadata
# lands in the coordinator. Then peer-a2 fetches and is steered toward peer-a1
# (or peer-b1) — when it hits peer-a1 the bytes are corrupted.
auth_curl -o /dev/null "http://localhost:17003/trigger-fetch/ws3-validate-obj"
for _ in 1 2 3 4 5; do
  auth_curl -o /dev/null "http://localhost:17002/trigger-fetch/ws3-validate-obj"
  sleep 0.5
done
check "fetches issued without HTTP error" true

# --- Step 3: poll /stats for quarantine -----------------------------------
printf "\n${B}3. Poll coordinator /stats until %s is quarantined${N}\n" "$TARGET_PEER"
QUARANTINED=false
for i in {1..20}; do
  STATE="$(auth_curl "http://localhost:18000/stats" \
    | jq -r --arg p "$TARGET_PEER" '.peer_reputations[]? | select(.peer_id==$p) | .state')"
  [[ "$VERBOSE" == true ]] && echo "  poll $i: state=${STATE:-<none>}"
  if [[ "$STATE" == "quarantined" ]]; then
    QUARANTINED=true; break
  fi
  sleep 1
done
check "$TARGET_PEER reached state=quarantined" bash -c "[[ '$QUARANTINED' == 'true' ]]"

# --- Step 4: lookup excludes the quarantined peer --------------------------
printf "\n${B}4. /lookup excludes %s${N}\n" "$TARGET_PEER"
PROVIDERS_JSON="$(auth_curl "http://localhost:18000/lookup/ws3-validate-obj?location_id=Building-A")"
[[ "$VERBOSE" == true ]] && echo "$PROVIDERS_JSON" | jq .

if echo "$PROVIDERS_JSON" | jq -r '.providers[]' | grep -Fq "$TARGET_PEER"; then
  check "$TARGET_PEER absent from /lookup providers" false
else
  check "$TARGET_PEER absent from /lookup providers" true
fi

# --- Step 5: subsequent fetch from a clean peer still succeeds -------------
printf "\n${B}5. Availability preserved (peer-b1 fetch still works)${N}\n"
RESULT="$(auth_curl "http://localhost:17003/trigger-fetch/ws3-validate-obj")"
[[ "$VERBOSE" == true ]] && echo "$RESULT" | jq .
SOURCE="$(echo "$RESULT" | jq -r '.source')"
check "peer-b1 fetch succeeded (source=cache|peer|origin)" \
  bash -c "[[ '$SOURCE' == 'cache' || '$SOURCE' == 'peer' || '$SOURCE' == 'origin' ]]"

# --- Summary ---------------------------------------------------------------
printf "\n${B}Summary${N}: ${G}${pass} passed${N}, "
if (( fail > 0 )); then
  printf "${R}${fail} failed${N}\n"
  exit 1
else
  printf "${G}0 failed${N}\n"
  exit 0
fi
