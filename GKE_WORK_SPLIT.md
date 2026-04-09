# GKE Deployment — Work Split

**Team:** Swarup Panda & Tanish Praveen Nagrani  
**Reference:** [GKE_DEPLOYMENT.md](GKE_DEPLOYMENT.md)

---

## Swarup — Infrastructure & DHT Stack (Config A)

### Day 1: Cluster + Origin
- [ ] Enable GCP APIs (container, artifactregistry, run)
- [ ] Create GKE cluster (`resilientp2p-cluster`, us-central1)
- [ ] Create node pool `building-a-pool` (us-central1-a, label `building=A`)
- [ ] Create node pool `building-b-pool` (us-central1-b, label `building=B`)
- [ ] Create Artifact Registry (`resilientp2p`, us-central1)
- [ ] Build & push origin image to registry
- [ ] Deploy origin to Cloud Run (us-east1, `ORIGIN_DELAY_MS=0`, min-instances=1)
- [ ] Verify origin health endpoint
- [ ] **Share with Tanish:** `ORIGIN_URL`, `REGISTRY` path, cluster credentials

### Day 2: DHT Stack + Experiment Runner
- [ ] Build & push `dht-bootstrap` image
- [ ] Build & push `dht-peer` image
- [ ] Update `k8s/base/configmap-dht.yaml` with real `ORIGIN_URL`
- [ ] Update `k8s/dht-stack/*.yaml` with real `REGISTRY`
- [ ] Apply namespaces: `kubectl apply -f k8s/base/namespaces.yaml`
- [ ] Deploy DHT stack: `kubectl apply -f k8s/base/configmap-dht.yaml && kubectl apply -f k8s/dht-stack/`
- [ ] Verify all 4 pods running in `p2p-dht` namespace
- [ ] Run smoke tests (origin fetch, intra-zone, cross-zone)
- [ ] Test coordinator fallback (kill dht-bootstrap, verify peer still serves)
- [ ] Adapt `p2p-dht/experiments/runner.py` for K8s (kubectl scale for kill/restart)
- [ ] Create `p2p-dht/experiments/workload-k8s.json` (zero delays, longer timeouts)

---

## Tanish — Coordinator Stack (Config B) & Evaluation

### Day 1: Build Images + Deploy Coordinator Stack
- [ ] Get cluster credentials, REGISTRY, ORIGIN_URL from Swarup
- [ ] Build & push `coordinator` image
- [ ] Build & push `coord-peer` image
- [ ] Build & push `dht-bootstrap` image (coordinator stack also uses it)
- [ ] Update `k8s/base/configmap-coordinator.yaml` with real `ORIGIN_URL`
- [ ] Update `k8s/coordinator-stack/*.yaml` with real `REGISTRY`
- [ ] Deploy coordinator stack: `kubectl apply -f k8s/base/configmap-coordinator.yaml && kubectl apply -f k8s/coordinator-stack/`
- [ ] Verify all 5 pods running in `p2p-coordinator` namespace
- [ ] Run smoke tests (origin fetch, intra-zone, cross-zone)
- [ ] Test DHT fallback (kill coordinator, verify DHT path works)
- [ ] Test full pipeline (new object with coordinator down)

### Day 2: Experiment Runner + Evaluation
- [ ] Adapt `p2p-coordinator/experiments/runner.py` for K8s
- [ ] Create `p2p-coordinator/experiments/workload-k8s.json`
- [ ] Run all 7 scenarios on coordinator stack
- [ ] Run all 7 scenarios on DHT stack
- [ ] Collect metrics from pod logs (`kubectl logs | grep "^METRIC:"`)
- [ ] Collect coordinator/DHT stats endpoints
- [ ] Build latency comparison table (local Docker vs GKE)

---

## Coordination Checkpoints

| # | Blocker | Who | Unblocks |
|---|---------|-----|----------|
| 1 | Cluster + Registry + Cloud Run origin ready | Swarup | Tanish can start building/pushing images |
| 2 | ORIGIN_URL shared | Swarup | Tanish can update configmaps |
| 3 | Both stacks deployed and smoke-tested | Both | Evaluation can begin |
| 4 | Experiment runners adapted for K8s | Both | Full scenario runs |

---

## Quick Reference

```bash
# Get cluster credentials (both need this)
gcloud container clusters get-credentials resilientp2p-cluster --region us-central1

# Check pods
kubectl get pods -n p2p-coordinator
kubectl get pods -n p2p-dht

# Port-forward (coordinator stack)
kubectl port-forward -n p2p-coordinator svc/coordinator 8000:8000 &
kubectl port-forward -n p2p-coordinator svc/peer-a1 7001:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-a2 7002:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-b1 7003:7000 &

# Port-forward (DHT stack)
kubectl port-forward -n p2p-dht svc/coordinator 9000:8000 &
kubectl port-forward -n p2p-dht svc/peer-a1 9001:7000 &
kubectl port-forward -n p2p-dht svc/peer-a2 9002:7000 &
kubectl port-forward -n p2p-dht svc/peer-b1 9003:7000 &
```

---

## Teardown (after evaluation)

```bash
gcloud container clusters delete resilientp2p-cluster --region us-central1 --quiet
gcloud run services delete resilientp2p-origin --region us-east1 --quiet
gcloud artifacts repositories delete resilientp2p --location=us-central1 --quiet
```

Estimated cost while running: ~$65/month. Tear down after testing.
