# GKE Deployment Guide for ResilientP2P

## Architecture

```
us-east1 (Cloud Run)          us-central1-a (Building-A)         us-central1-b (Building-B)
+--------------+              +--------------------------+       +------------------+
|  origin      |<--- WAN ----|  coordinator             |       |                  |
|  (Cloud Run) |  (20-60ms)  |  dht-bootstrap           |       |  peer-b1         |
+--------------+              |  peer-a1                 |       |                  |
                              |  peer-a2                 |       +------------------+
                              +----------+---------------+              ^
                                         |      cross-zone (~5-10ms)   |
                                         +-----------------------------+
```

- **Real latency** replaces simulated delays (all `DELAY_MS` env vars set to `0`)
- **Origin on Cloud Run** in a different region for real WAN latency
- **Peers pinned to zones** via node labels + nodeSelector

---

## Prerequisites

- Google Cloud account with billing enabled
- Tools installed: `gcloud`, `kubectl`, `docker`
- A GCP project ID (referred to as `$GCP_PROJECT_ID` below)

```bash
export GCP_PROJECT_ID="your-project-id"
gcloud config set project $GCP_PROJECT_ID
```

---

## Step 1: Enable APIs

```bash
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com
```

---

## Step 2: Create GKE Cluster

```bash
# Create regional cluster with no default node pool
gcloud container clusters create resilientp2p-cluster \
  --region us-central1 \
  --num-nodes 0 \
  --release-channel rapid

# Building-A node pool in us-central1-a
gcloud container node-pools create building-a-pool \
  --cluster resilientp2p-cluster \
  --region us-central1 \
  --node-locations us-central1-a \
  --machine-type e2-medium \
  --num-nodes 1 \
  --node-labels building=A

# Building-B node pool in us-central1-b
gcloud container node-pools create building-b-pool \
  --cluster resilientp2p-cluster \
  --region us-central1 \
  --node-locations us-central1-b \
  --machine-type e2-medium \
  --num-nodes 1 \
  --node-labels building=B

# Get credentials for kubectl
gcloud container clusters get-credentials resilientp2p-cluster --region us-central1
```

---

## Step 3: Create Artifact Registry

```bash
gcloud artifacts repositories create resilientp2p \
  --repository-format=docker \
  --location=us-central1

# Authenticate docker
gcloud auth configure-docker us-central1-docker.pkg.dev

export REGISTRY="us-central1-docker.pkg.dev/$GCP_PROJECT_ID/resilientp2p"
```

---

## Step 4: Build & Push Docker Images

5 images total. Build from the project root.

```bash
cd /path/to/ResilientP2P

# From p2p-coordinator/ context (coordinator, coord-peer, origin, dht-bootstrap)
cd p2p-coordinator
docker build -f coordinator/Dockerfile -t $REGISTRY/coordinator:v1 .
docker build -f peer/Dockerfile -t $REGISTRY/coord-peer:v1 .
docker build -f origin/Dockerfile -t $REGISTRY/origin:v1 .
docker build -f bootstrap/Dockerfile -t $REGISTRY/dht-bootstrap:v1 .

# From p2p-dht/ context (dht-peer)
cd ../p2p-dht
docker build -f peer/Dockerfile -t $REGISTRY/dht-peer:v1 .

# Push all
cd ..
docker push $REGISTRY/coordinator:v1
docker push $REGISTRY/coord-peer:v1
docker push $REGISTRY/origin:v1
docker push $REGISTRY/dht-bootstrap:v1
docker push $REGISTRY/dht-peer:v1
```

---

## Step 5: Deploy Origin to Cloud Run

Origin runs in `us-east1` (different region) for real WAN latency.

```bash
gcloud run deploy resilientp2p-origin \
  --image $REGISTRY/origin:v1 \
  --region us-east1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8001 \
  --set-env-vars ORIGIN_DELAY_MS=0 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 2

# Get the Cloud Run URL
ORIGIN_URL=$(gcloud run services describe resilientp2p-origin \
  --region us-east1 --format 'value(status.url)')
echo "Origin URL: $ORIGIN_URL"
```

Verify it works:

```bash
curl -s "$ORIGIN_URL/health"
# Expected: {"status":"ok","service":"origin"}
```

---

## Step 6: Update K8s Manifests

Before applying, replace the placeholders in the manifest files:

### 6a. Update image references

In **all** YAML files under `k8s/coordinator-stack/` and `k8s/dht-stack/`, replace:

```
image: REGISTRY/coordinator:v1    ->  image: us-central1-docker.pkg.dev/YOUR_PROJECT/resilientp2p/coordinator:v1
image: REGISTRY/coord-peer:v1     ->  image: us-central1-docker.pkg.dev/YOUR_PROJECT/resilientp2p/coord-peer:v1
image: REGISTRY/dht-peer:v1       ->  image: us-central1-docker.pkg.dev/YOUR_PROJECT/resilientp2p/dht-peer:v1
image: REGISTRY/dht-bootstrap:v1  ->  image: us-central1-docker.pkg.dev/YOUR_PROJECT/resilientp2p/dht-bootstrap:v1
```

Or use sed:

```bash
find k8s/ -name '*.yaml' -exec sed -i '' "s|REGISTRY|$REGISTRY|g" {} +
```

### 6b. Update Origin URL

In `k8s/base/configmap-coordinator.yaml` and `k8s/base/configmap-dht.yaml`, replace:

```
ORIGIN_URL: "REPLACE_WITH_CLOUD_RUN_URL"  ->  ORIGIN_URL: "https://resilientp2p-origin-XXXX-ue.a.run.app"
```

Or use sed:

```bash
sed -i '' "s|REPLACE_WITH_CLOUD_RUN_URL|$ORIGIN_URL|g" k8s/base/configmap-coordinator.yaml k8s/base/configmap-dht.yaml
```

---

## Step 7: Deploy Coordinator Stack (Config B)

```bash
# Create namespaces
kubectl apply -f k8s/base/namespaces.yaml

# Apply config
kubectl apply -f k8s/base/configmap-coordinator.yaml

# Deploy all services
kubectl apply -f k8s/coordinator-stack/

# Watch pods come up
kubectl get pods -n p2p-coordinator -w
```

Wait until all 5 pods show `Running` and `Ready` (1-2 minutes):

```
NAME                              READY   STATUS    AGE
coordinator-xxxxx                 1/1     Running   60s
dht-bootstrap-xxxxx               1/1     Running   60s
peer-a1-xxxxx                     1/1     Running   60s
peer-a2-xxxxx                     1/1     Running   60s
peer-b1-xxxxx                     1/1     Running   60s
```

Verify coordinator sees all peers:

```bash
kubectl port-forward -n p2p-coordinator svc/coordinator 8000:8000 &
curl -s localhost:8000/stats | python3 -m json.tool
# Should show peer_count: 3
```

---

## Step 8: Test Coordinator Stack

### Set up port-forwards (each in a separate terminal, or background them)

```bash
kubectl port-forward -n p2p-coordinator svc/coordinator 8000:8000 &
kubectl port-forward -n p2p-coordinator svc/peer-a1 7001:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-a2 7002:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-b1 7003:7000 &
```

### Test 1: Origin fetch (real WAN latency)

```bash
curl -s localhost:7001/trigger-fetch/test-object-1 | python3 -m json.tool
```

Expected: `source: "origin"`, latency ~20-60ms (real WAN to us-east1).

### Test 2: Same-building peer fetch (intra-zone)

```bash
curl -s localhost:7002/trigger-fetch/test-object-1 | python3 -m json.tool
```

Expected: `source: "peer"`, provider: peer-a1, latency ~1-5ms.

### Test 3: Cross-building peer fetch (cross-zone)

```bash
curl -s localhost:7003/trigger-fetch/test-object-1 | python3 -m json.tool
```

Expected: `source: "peer"`, latency ~5-15ms (higher than Test 2).

### Test 4: DHT fallback (kill coordinator)

```bash
kubectl scale deployment coordinator -n p2p-coordinator --replicas=0

# Wait 5 seconds for coordinator to be fully down
sleep 5

curl -s localhost:7003/trigger-fetch/test-object-1 | python3 -m json.tool
# Expected: source: "peer" via DHT fallback

# Bring coordinator back
kubectl scale deployment coordinator -n p2p-coordinator --replicas=1
```

### Test 5: Full pipeline (new object with coordinator down)

```bash
kubectl scale deployment coordinator -n p2p-coordinator --replicas=0
sleep 5

curl -s localhost:7003/trigger-fetch/brand-new-object | python3 -m json.tool
# Expected: source: "origin" (no peer has it, DHT has no entry, falls to origin)

kubectl scale deployment coordinator -n p2p-coordinator --replicas=1
```

---

## Step 9: Deploy & Test DHT Stack (Config A)

```bash
# Apply DHT config
kubectl apply -f k8s/base/configmap-dht.yaml

# Deploy all services
kubectl apply -f k8s/dht-stack/

# Watch pods come up
kubectl get pods -n p2p-dht -w
```

Port-forward (use different local ports if coordinator stack is still running):

```bash
kubectl port-forward -n p2p-dht svc/coordinator 9000:8000 &
kubectl port-forward -n p2p-dht svc/peer-a1 9001:7000 &
kubectl port-forward -n p2p-dht svc/peer-a2 9002:7000 &
kubectl port-forward -n p2p-dht svc/peer-b1 9003:7000 &
```

Run the same tests on ports 9001-9003. For coordinator fallback test, kill dht-bootstrap instead:

```bash
kubectl scale deployment dht-bootstrap -n p2p-dht --replicas=0
sleep 5
curl -s localhost:9003/trigger-fetch/test-object-1 | python3 -m json.tool
# Expected: source: "peer" via coordinator fallback
kubectl scale deployment dht-bootstrap -n p2p-dht --replicas=1
```

---

## Collecting Metrics

### From container logs

```bash
# Extract METRIC lines from all peers
for pod in peer-a1 peer-a2 peer-b1; do
  kubectl logs -n p2p-coordinator deployment/$pod | grep "^METRIC:" > metrics-coord-$pod.jsonl
done

for pod in peer-a1 peer-a2 peer-b1; do
  kubectl logs -n p2p-dht deployment/$pod | grep "^METRIC:" > metrics-dht-$pod.jsonl
done
```

### From coordinator stats

```bash
curl -s localhost:8000/stats | python3 -m json.tool  # coordinator stack
curl -s localhost:9000/stats | python3 -m json.tool  # DHT stack
```

### From Cloud Logging (GCP Console)

All container stdout is automatically shipped to Cloud Logging. Query with:

```
resource.type="k8s_container"
textPayload:"METRIC:"
```

---

## Latency Comparison: Local vs Cloud

| Path | Docker Compose (simulated) | GKE (real) |
|------|---------------------------|------------|
| Intra-building (same zone) | 5ms | ~1-5ms |
| Cross-building (cross zone) | 35ms | ~5-10ms |
| Origin (WAN) | 120ms | ~20-60ms |
| DHT fallback | ~115ms | real network latency |
| Coordinator fallback | ~86ms | real network latency |

---

## Scaling (Adding More Peers)

To add `peer-a3` in Building-A:
1. Copy `k8s/coordinator-stack/peer-a1.yaml`
2. Replace: `peer-a1` -> `peer-a3` everywhere in the file
3. `kubectl apply -f k8s/coordinator-stack/peer-a3.yaml`

To add a third building (Building-C):
1. Create a new node pool:
   ```bash
   gcloud container node-pools create building-c-pool \
     --cluster resilientp2p-cluster --region us-central1 \
     --node-locations us-central1-c --machine-type e2-medium \
     --num-nodes 1 --node-labels building=C
   ```
2. Create peer YAML with `LOCATION_ID: Building-C` and `nodeSelector: building: C`

---

## Teardown (Stop Billing)

```bash
# Delete the GKE cluster (removes all pods, services, node pools)
gcloud container clusters delete resilientp2p-cluster --region us-central1 --quiet

# Delete Cloud Run origin
gcloud run services delete resilientp2p-origin --region us-east1 --quiet

# (Optional) Delete Artifact Registry images
gcloud artifacts repositories delete resilientp2p --location=us-central1 --quiet
```

Estimated cost while running: ~$65/month (2 nodes + Cloud Run). Tear down after testing to avoid charges.

---

## Troubleshooting

### Pods stuck in Pending
```bash
kubectl describe pod <pod-name> -n p2p-coordinator
```
Usually means node pool doesn't have capacity. Check node labels match `nodeSelector`.

### Peer can't reach coordinator
```bash
kubectl exec -n p2p-coordinator deployment/peer-a1 -- curl -s http://coordinator.p2p-coordinator.svc.cluster.local:8000/health
```
Should return `{"status":"ok"}`. If not, check Service and DNS.

### DHT UDP not working
```bash
kubectl exec -n p2p-coordinator deployment/peer-a1 -- python3 -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(b'test', ('dht-bootstrap.p2p-coordinator.svc.cluster.local', 6000)); print('UDP ok')"
```
GKE default network policy allows all intra-cluster traffic including UDP.

### Cloud Run origin returning 502
Check Cloud Run logs in GCP Console. Likely a cold start issue — verify `min-instances=1` is set.

### Port-forward keeps dropping
Use `while true; do kubectl port-forward ...; sleep 1; done` to auto-reconnect. For production testing, use the in-cluster experiment runner Job instead.
