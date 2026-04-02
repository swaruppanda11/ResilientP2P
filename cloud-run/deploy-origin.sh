#!/bin/bash
set -euo pipefail

# Deploy origin server to Cloud Run in a different region for real WAN latency.
# The cluster runs in us-central1; origin in us-east1 gives ~20-60ms real WAN.

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="us-east1"
REGISTRY="us-central1-docker.pkg.dev/${PROJECT_ID}/resilientp2p"
IMAGE="${REGISTRY}/origin:v1"

echo "==> Building origin image..."
docker build -f ../p2p-coordinator/origin/Dockerfile -t "${IMAGE}" ../p2p-coordinator/

echo "==> Pushing to Artifact Registry..."
docker push "${IMAGE}"

echo "==> Deploying to Cloud Run in ${REGION}..."
gcloud run deploy resilientp2p-origin \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8001 \
  --set-env-vars ORIGIN_DELAY_MS=0 \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 2 \
  --min-instances 1 \
  --project "${PROJECT_ID}"

echo ""
echo "==> Origin deployed. Get the URL with:"
echo "    gcloud run services describe resilientp2p-origin --region ${REGION} --format 'value(status.url)'"
echo ""
echo "==> Update ORIGIN_URL in k8s/base/configmap-coordinator.yaml and configmap-dht.yaml with this URL."
