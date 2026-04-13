#!/usr/bin/env bash
#
# Export experiment results and aggregate outputs to a GCS bucket.
#
# Creates a timestamped folder in the bucket so each export is immutable:
#   gs://resilientp2p-results/2026-04-13T1830/
#     coordinator/results-k8s-multi/...
#     dht/results-k8s-multi/...
#     aggregate/...
#
# Prerequisites:
#   - gcloud auth login
#   - gsutil available (comes with gcloud SDK)
#   - GCS bucket created (see below)
#
# To create the bucket (one-time):
#   gsutil mb -l us-central1 -p resilientp2p-492916 gs://resilientp2p-results
#
# Usage:
#   ./scripts/export-to-gcs.sh                          # default bucket
#   ./scripts/export-to-gcs.sh gs://my-custom-bucket    # custom bucket
#
set -euo pipefail

BUCKET="${1:-gs://resilientp2p-results}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMESTAMP="$(date +%Y-%m-%dT%H%M)"
DEST="${BUCKET}/${TIMESTAMP}"

if ! command -v gsutil &>/dev/null; then
  echo "ERROR: gsutil not found. Install the Google Cloud SDK." >&2
  exit 1
fi

echo "==> Exporting results to ${DEST}/"
echo

# Upload coordinator multi-run results
COORD_MULTI="${REPO_ROOT}/p2p-coordinator/experiments/results-k8s-multi"
if [[ -d "$COORD_MULTI" ]]; then
  echo "  -> Coordinator multi-run results"
  gsutil -m rsync -r "$COORD_MULTI" "${DEST}/coordinator/results-k8s-multi/"
fi

# Upload coordinator single-run results
COORD_SINGLE="${REPO_ROOT}/p2p-coordinator/experiments/results-k8s"
if [[ -d "$COORD_SINGLE" ]]; then
  echo "  -> Coordinator single-run results"
  gsutil -m rsync -r "$COORD_SINGLE" "${DEST}/coordinator/results-k8s/"
fi

# Upload DHT multi-run results
DHT_MULTI="${REPO_ROOT}/p2p-dht/experiments/results-k8s-multi"
if [[ -d "$DHT_MULTI" ]]; then
  echo "  -> DHT multi-run results"
  gsutil -m rsync -r "$DHT_MULTI" "${DEST}/dht/results-k8s-multi/"
fi

# Upload DHT single-run results
DHT_SINGLE="${REPO_ROOT}/p2p-dht/experiments/results-k8s"
if [[ -d "$DHT_SINGLE" ]]; then
  echo "  -> DHT single-run results"
  gsutil -m rsync -r "$DHT_SINGLE" "${DEST}/dht/results-k8s/"
fi

# Upload aggregate outputs
AGG="${REPO_ROOT}/results-aggregate"
if [[ -d "$AGG" ]]; then
  echo "  -> Aggregate outputs"
  gsutil -m rsync -r "$AGG" "${DEST}/aggregate/"
fi

echo
echo "==> Done. Results exported to:"
echo "    ${DEST}/"
echo
echo "To list contents:"
echo "    gsutil ls ${DEST}/"
