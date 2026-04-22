# GKE Deployment Guide for ResilientP2P

This document defines the corrected cloud MVP deployment path for the ResilientP2P project on Google Kubernetes Engine (GKE).

It is intentionally focused on:

- getting the existing local prototype running correctly in GCP
- preserving the behavior already validated locally
- validating both hybrid architectures in cloud
- preparing the system for repeated runs and final evaluation

This document is a **manual bring-up and validation guide**, not the final Terraform-only automation layer. Terraform and repeatable cloud experiment orchestration should be added on top of this flow after the MVP is confirmed.

---

## 1. What This Deployment Is Trying to Achieve

The goal of the cloud deployment is **not** to redesign the system. The goal is to reproduce the already-working local prototype in a private GKE environment and validate that:

1. `Coordinator-primary + DHT fallback` works in cloud
2. `DHT-primary + Coordinator fallback` works in cloud
3. locality-aware peer selection still behaves correctly
4. churn and fallback paths can be exercised in cloud
5. the system is ready for repeated runs and final results collection

The most important rule is:

> The cloud environment should preserve the validated local behavior before adding realism or scale.

---

## 2. Correct Cloud MVP Design

### 2.1 Use GKE Only

The cloud MVP uses:

- `GKE` for peers, coordinator, DHT bootstrap, and workload execution
- `Artifact Registry` for Docker images
- `GCS` for experiment artifacts

We do **not** use Cloud Run for peer services.

### 2.2 Controlled Latency Model

For this research project, the primary latency hierarchy should remain the **application-layer model already implemented in the codebase**:

- same-building peer fetch
- cross-building peer fetch
- origin fetch

This is more experimentally stable than depending entirely on raw GCP network latency.

Therefore:

- keep the existing app-layer delay model enabled in cloud
- treat real cloud latency as an additional background effect, not the primary topology mechanism

This preserves comparability between local and cloud runs.

### 2.3 Logical Buildings, Not Real Campus Subnets

For the MVP, buildings are modeled logically via:

- `LOCATION_ID`
- pod labels
- node placement

We do **not** require one real GCP subnet per building in the first cloud pass.

Instead:

- use a single private GKE cluster
- optionally place peers on different zones/node pools
- keep the experiment’s building identity in configuration

### 2.4 Deploy One Architecture at a Time

The two stacks should not be run simultaneously unless they are fully namespaced and isolated.

Recommended workflow:

1. deploy and validate `coordinator-primary`
2. tear it down or isolate it
3. deploy and validate `DHT-primary`

---

## 3. Target Cloud Architecture

Recommended cloud MVP:

```text
GCP Project
  ├── VPC
  ├── Private GKE Cluster
  │    ├── coordinator namespace
  │    ├── dht namespace
  │    └── infra namespace
  ├── Artifact Registry
  └── GCS bucket for results
```

Core services:

- `origin`
- `coordinator`
- `dht-bootstrap`
- `peer-a1`, `peer-a2`, `peer-b1` initially
- later: workload runner Job

Recommended deployment model:

- `Deployment` for:
  - origin
  - coordinator
  - dht-bootstrap
- `StatefulSet` for peers
- `Job` for workload execution

---

## 4. Prerequisites

Required locally:

- `gcloud`
- `kubectl`
- `docker`

Required in GCP:

- billing enabled
- GKE API enabled
- Artifact Registry API enabled
- GCS access

Set project:

```bash
export GCP_PROJECT_ID="your-project-id"
gcloud config set project $GCP_PROJECT_ID
```

Enable APIs:

```bash
gcloud services enable \
  container.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com
```

---

## 5. Build and Push Images

### 5.1 Required Images

Build and push:

- `coordinator`
- `coord-peer`
- `origin`
- `dht-bootstrap`
- `dht-peer`

### 5.2 Tagging Rule

Do not use only `v1`.

Use:

- git SHA tags for reproducibility
- optional convenience tag if needed

Example:

```bash
export GIT_SHA=$(git rev-parse --short HEAD)
export REGISTRY="us-central1-docker.pkg.dev/$GCP_PROJECT_ID/resilientp2p"
```

Build:

```bash
cd p2p-coordinator
docker build -f coordinator/Dockerfile -t $REGISTRY/coordinator:$GIT_SHA .
docker build -f peer/Dockerfile -t $REGISTRY/coord-peer:$GIT_SHA .
docker build -f origin/Dockerfile -t $REGISTRY/origin:$GIT_SHA .
docker build -f bootstrap/Dockerfile -t $REGISTRY/dht-bootstrap:$GIT_SHA .

cd ../p2p-dht
docker build -f peer/Dockerfile -t $REGISTRY/dht-peer:$GIT_SHA .
```

Push:

```bash
docker push $REGISTRY/coordinator:$GIT_SHA
docker push $REGISTRY/coord-peer:$GIT_SHA
docker push $REGISTRY/origin:$GIT_SHA
docker push $REGISTRY/dht-bootstrap:$GIT_SHA
docker push $REGISTRY/dht-peer:$GIT_SHA
```

---

## 6. GKE Cluster Setup

### 6.1 Recommended MVP Cluster

Use one private GKE cluster in `us-central1`.

You may use multiple node pools to emulate placement separation, but do not overcomplicate the first deployment.

Suggested starting point:

- cluster: `resilientp2p-cluster`
- region: `us-central1`
- node pools:
  - `building-a-pool`
  - `building-b-pool`

Example:

```bash
gcloud container clusters create-auto resilientp2p-cluster \
  --region us-central1
```

Or, if you want manual node pools:

```bash
gcloud container clusters create resilientp2p-cluster \
  --region us-central1 \
  --num-nodes 1 \
  --machine-type e2-standard-2
```

Optional node pools for placement:

```bash
gcloud container node-pools create building-a-pool \
  --cluster resilientp2p-cluster \
  --region us-central1 \
  --node-locations us-central1-a \
  --machine-type e2-medium \
  --num-nodes 1 \
  --node-labels building=A

gcloud container node-pools create building-b-pool \
  --cluster resilientp2p-cluster \
  --region us-central1 \
  --node-locations us-central1-b \
  --machine-type e2-medium \
  --num-nodes 1 \
  --node-labels building=B
```

Fetch credentials:

```bash
gcloud container clusters get-credentials resilientp2p-cluster --region us-central1
```

### 6.2 Important Note

Zone placement is only a **secondary realism aid**. It does not replace the application-layer locality model.

---

## 7. Artifact Registry

Create repository:

```bash
gcloud artifacts repositories create resilientp2p \
  --repository-format=docker \
  --location=us-central1
```

Authenticate docker:

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

---

## 8. Origin Service Strategy

### 8.1 Recommended MVP Choice

For the first cloud pass, prefer **an internal origin service in GKE** using the same origin image.

Reason:

- simpler
- more controllable
- fully private
- easier to keep reproducible

### 8.2 If You Still Want External Origin

An external origin is acceptable as a second step. If used:

- place it in another region
- clearly record that this adds uncontrolled cloud-network variance

If you keep Cloud Run for the origin, treat it as a realism layer, not as the primary basis of your topology model.

---

## 9. Kubernetes Deployment Model

### 9.1 Namespaces

Recommended namespaces:

- `p2p-coordinator`
- `p2p-dht`
- `p2p-infra`

### 9.2 Services

Deploy the following as internal cluster services:

- `coordinator`
- `origin`
- `dht-bootstrap`
- one service per peer or headless service for peer StatefulSet access

### 9.3 Peers

Use `StatefulSet` for peers if you want stable peer IDs and DNS names.

Each peer must receive:

- `PEER_ID`
- `LOCATION_ID`
- `COORDINATOR_URL`
- `ORIGIN_URL`
- `DHT_BOOTSTRAP_HOST`
- `DHT_BOOTSTRAP_PORT`
- `CACHE_CAPACITY_BYTES`
- topology delay variables

### 9.4 Service Discovery Mapping

Replace docker-compose hostnames with Kubernetes DNS names.

Examples:

- `http://coordinator:8000`
- `http://origin:8001`
- `dht-bootstrap`

should become their correct Kubernetes service names in the appropriate namespace.

---

## 10. Keep the Existing Delay Model

Do **not** set all latency variables to zero for the main experiments.

Keep the current controlled values unless you are explicitly running a “raw cloud latency” comparison:

- same-building / intra-location delay
- cross-building / inter-location delay
- origin delay

This is necessary to preserve:

- local-vs-cloud comparability
- experimental control
- the report’s locality claims

Raw cloud network differences are too noisy and too weakly separated to replace the modeled hierarchy by themselves.

---

## 11. Manual Validation Workflow

This section is for initial bring-up only.

### 11.1 Deploy Coordinator Stack

Apply namespace and config:

```bash
kubectl apply -f k8s/base/namespaces.yaml
kubectl apply -f k8s/base/configmap-coordinator.yaml
kubectl apply -f k8s/coordinator-stack/
```

Wait for readiness:

```bash
kubectl get pods -n p2p-coordinator -w
```

### 11.2 Port-Forward for Manual Validation

```bash
kubectl port-forward -n p2p-coordinator svc/coordinator 8000:8000 &
kubectl port-forward -n p2p-coordinator svc/peer-a1 7001:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-a2 7002:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-b1 7003:7000 &
```

### 11.3 Minimal Validation Tests

1. Warm object from origin:

```bash
curl -s localhost:7001/trigger-fetch/test-object-1
```

2. Same-building peer fetch:

```bash
curl -s localhost:7002/trigger-fetch/test-object-1
```

3. Cross-building peer fetch:

```bash
curl -s localhost:7003/trigger-fetch/test-object-1
```

4. Coordinator crash fallback:

```bash
kubectl scale deployment coordinator -n p2p-coordinator --replicas=0
sleep 5
curl -s localhost:7003/trigger-fetch/test-object-1
kubectl scale deployment coordinator -n p2p-coordinator --replicas=1
```

### 11.4 Deploy DHT Stack

```bash
kubectl apply -f k8s/base/configmap-dht.yaml
kubectl apply -f k8s/dht-stack/
kubectl get pods -n p2p-dht -w
```

Port-forward:

```bash
kubectl port-forward -n p2p-dht svc/coordinator 9000:8000 &
kubectl port-forward -n p2p-dht svc/peer-a1 9001:7000 &
kubectl port-forward -n p2p-dht svc/peer-a2 9002:7000 &
kubectl port-forward -n p2p-dht svc/peer-b1 9003:7000 &
```

Test DHT crash fallback:

```bash
kubectl scale deployment dht-bootstrap -n p2p-dht --replicas=0
sleep 5
curl -s localhost:9003/trigger-fetch/test-object-1
kubectl scale deployment dht-bootstrap -n p2p-dht --replicas=1
```

---

## 12. What This Guide Does Not Yet Cover

This guide intentionally stops short of the full final cloud workflow.

It does **not** yet define:

- Terraform modules
- automated result export to GCS
- in-cluster workload runner Jobs
- repeated-run orchestration
- full Prometheus/Grafana deployment
- advanced partition injection in Kubernetes
- coordinator HA / Redis

Those belong to the next layer after the cloud MVP is validated.

---

## 13. Metrics Collection for MVP

For the cloud MVP, the minimum acceptable metrics sources are:

1. application logs
2. `/stats` endpoints
3. structured result JSON artifacts once workload Jobs are added

Manual collection examples:

```bash
kubectl logs -n p2p-coordinator <peer-pod-name>
kubectl logs -n p2p-dht <peer-pod-name>
```

For richer evaluation later:

- add a workload runner Job
- upload result JSON to GCS
- aggregate offline or via notebooks/scripts

---

## 14. Recommended Next Step After This Guide

After the manual GKE bring-up works, the next work items should be:

1. add Terraform for:
   - GKE
   - Artifact Registry
   - GCS
2. create a workload runner Job
3. export result artifacts automatically
4. add repeated-run support
5. only then produce final plots/tables

---

## 15. Post-Report Hardening Deployment Notes

These notes cover the next workstreams identified after the report: dynamic invalidation, peer authentication/access control, and malicious-peer resilience. They are not required for reproducing the completed evaluation, but they affect future Kubernetes configuration and validation.

The implementation checklist is maintained in [POST_REPORT_HARDENING_ROADMAP.md](POST_REPORT_HARDENING_ROADMAP.md).

### 15.1 Dynamic Object Invalidation

Expected deployment/config changes:

- Add environment variables for cache consistency behavior:
  - `DEFAULT_CACHEABILITY=immutable|ttl|dynamic`
  - `DEFAULT_MAX_AGE_SECONDS`
  - `ENABLE_INVALIDATION_API=true|false`
- Add coordinator endpoints for invalidation and revalidation.
- Add workload scenarios that warm an object, invalidate it, and verify the next peer request does not serve stale data.
- Keep `immutable` as the default so current report workloads remain reproducible.
- Current implementation includes `POST /invalidate/{object_id}`, `POST /invalidate-prefix`, and `POST /revalidate/{object_id}`. The local and GKE workload files include dynamic invalidation, TTL expiry, and prefix invalidation scenarios for both coordinator-primary and DHT-primary stacks.

Kubernetes validation checklist:

- [x] Invalidate a warmed object through the coordinator service path in deterministic validation and GKE validation.
- [x] Verify peer cache stats/behavior show eviction or stale-entry rejection in deterministic validation and GKE validation.
- [x] Verify coordinator lookup no longer returns stale providers in deterministic validation and GKE validation.
- [x] Verify DHT lookup ignores provider records with stale version/expiry metadata in deterministic validation and GKE validation.
- [x] Re-run the new scenarios on GKE after rebuilding/pushing updated images.

GKE validation result:

- Image tag validated: `f01f039`
- Coordinator-primary hardening scenarios: `Dynamic Object Explicit Invalidation`, `TTL Expiry Revalidation`, and `Prefix Invalidation Smoke Test` all passed with `success_rate=1.0`
- DHT-primary hardening scenarios: `Dynamic Object Explicit Invalidation`, `TTL Expiry Revalidation`, and `Prefix Invalidation Smoke Test` all passed with `success_rate=1.0`
- Result directories: `p2p-coordinator/experiments/results-k8s-hardening/` and `p2p-dht/experiments/results-k8s-hardening/`

### 15.2 Peer Authentication and Access Control

Expected deployment/config changes:

- Add `AUTH_MODE`:
  - `none` for current experiments
  - `shared_token` for first secured test
  - later `certificate` or `oidc`
- Add Kubernetes Secrets for shared-token or certificate material.
- Mount or inject secrets into coordinator, peer, and DHT bootstrap pods as needed.
- Add object access metadata such as `visibility` and `allowed_groups`.

Kubernetes validation checklist:

- [ ] With `AUTH_MODE=none`, existing smoke tests still pass.
- [ ] With `AUTH_MODE=shared_token`, requests without token are rejected.
- [ ] Authenticated peers can register, publish, lookup, and transfer content.
- [ ] Unauthorized peers cannot receive restricted provider lists or object bytes.

Example Secret placeholder:

```bash
kubectl create secret generic p2p-auth \
  -n p2p-coordinator \
  --from-literal=shared-token='replace-with-dev-token'

kubectl create secret generic p2p-auth \
  -n p2p-dht \
  --from-literal=shared-token='replace-with-dev-token'
```

### 15.3 Malicious-Peer Resilience

Expected deployment/config changes:

- Add optional fault-injection mode for test peers so a peer can intentionally:
  - advertise an object it does not have
  - serve corrupted bytes
  - publish conflicting metadata
- Add coordinator/peer metrics for:
  - checksum mismatches
  - metadata conflicts
  - provider fetch failures
  - suspect/quarantined peer counts
- Add configurable thresholds:
  - `SUSPECT_THRESHOLD`
  - `QUARANTINE_THRESHOLD`
  - `QUARANTINE_TTL_SECONDS`

Kubernetes validation checklist:

- [ ] A bad-content peer is detected by checksum validation.
- [ ] Repeated bad behavior moves a peer to `quarantined`.
- [ ] Quarantined peers are excluded from provider results.
- [ ] Requesters retry healthy providers or origin after rejecting a bad provider.

---

## 16. Teardown

Delete cluster when done:

```bash
gcloud container clusters delete resilientp2p-cluster --region us-central1 --quiet
```

Delete Artifact Registry repository if needed:

```bash
gcloud artifacts repositories delete resilientp2p --location=us-central1 --quiet
```

If using Cloud Run origin, delete it separately:

```bash
gcloud run services delete resilientp2p-origin --region us-east1 --quiet
```

---

## 17. Key Design Corrections from the Earlier Version

This corrected guide differs from the earlier version in these important ways:

1. It uses `GKE` as the primary platform and no longer treats Cloud Run as part of the core peer architecture.
2. It keeps the `application-layer delay model` for controlled evaluation.
3. It treats `zone placement` as a realism aid, not as the full topology model.
4. It treats this document as a `manual MVP bring-up guide`, not the full final experiment framework.
5. It explicitly defers Terraform, workload Jobs, and repeated-run automation to the next phase instead of pretending they are already solved here.
