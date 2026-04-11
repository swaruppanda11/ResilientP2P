#!/usr/bin/env bash
#
# Build all 5 images for linux/amd64 and push to Artifact Registry.
# Tags each image with both the current git SHA and `v1`.
#
# Prerequisites (run once on a new machine):
#   gcloud auth login
#   gcloud config set project resilientp2p-492916
#   gcloud auth configure-docker us-central1-docker.pkg.dev
#   docker buildx create --use   # if you don't already have a buildx builder
#
# Usage:
#   ./scripts/build-and-push.sh
#
set -euo pipefail

PROJECT_ID="resilientp2p-492916"
REGION="us-central1"
REPO="resilientp2p"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

GIT_SHA="$(git rev-parse --short HEAD)"
PLATFORM="linux/amd64"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COORD_CTX="${REPO_ROOT}/p2p-coordinator"
DHT_CTX="${REPO_ROOT}/p2p-dht"

echo "==> Building and pushing images"
echo "    registry: ${REGISTRY}"
echo "    git sha:  ${GIT_SHA}"
echo "    platform: ${PLATFORM}"
echo

build_and_push() {
  local name="$1"
  local context="$2"
  local dockerfile="$3"

  local sha_tag="${REGISTRY}/${name}:${GIT_SHA}"
  local v1_tag="${REGISTRY}/${name}:v1"

  echo "--> ${name}"
  docker buildx build \
    --platform "${PLATFORM}" \
    --file "${dockerfile}" \
    --tag "${sha_tag}" \
    --tag "${v1_tag}" \
    --push \
    "${context}"
  echo "    pushed: ${sha_tag}"
  echo "    pushed: ${v1_tag}"
  echo
}

build_and_push "coordinator"   "${COORD_CTX}" "${COORD_CTX}/coordinator/Dockerfile"
build_and_push "coord-peer"    "${COORD_CTX}" "${COORD_CTX}/peer/Dockerfile"
build_and_push "origin"        "${COORD_CTX}" "${COORD_CTX}/origin/Dockerfile"
build_and_push "dht-bootstrap" "${COORD_CTX}" "${COORD_CTX}/bootstrap/Dockerfile"
build_and_push "dht-peer"      "${DHT_CTX}"   "${DHT_CTX}/peer/Dockerfile"

echo "==> All 5 images pushed successfully."
echo
echo "Image URIs (for reference / manifest updates):"
for name in coordinator coord-peer origin dht-bootstrap dht-peer; do
  echo "  ${REGISTRY}/${name}:${GIT_SHA}"
done
