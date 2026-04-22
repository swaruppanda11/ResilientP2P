# GKE Deployment Work Split

**Team:** Swarup Panda & Tanish Praveen Nagrani  
**References:** [GKE_DEPLOYMENT.md](GKE_DEPLOYMENT.md), [CLOUD_WORKFLOW.md](CLOUD_WORKFLOW.md)

This work split follows the corrected cloud plan:

- `GKE` is the primary platform
- the existing `application-layer delay model` stays enabled
- the two architectures are deployed and validated separately
- Terraform and repeated-run automation come later

The goal of this split is to let both teammates work independently as much as possible, then converge for integration testing and final cloud evaluation.

---

## Work Allocation Principles

Revised split (agreed 2026-04-11): Swarup owns everything up to the point both
stacks are live and smoke-tested in GKE. Tanish owns everything from experiment
workload migration through final evaluation and results.

### Swarup Owns (Infrastructure + Deployment, Phases 1–6)

- GCP project, cluster, Artifact Registry, node pools
- Build and push all 5 images
- Kubernetes manifests for both stacks (coordinator-primary and DHT-primary)
- Deploy both stacks into GKE
- Manual bring-up smoke tests for both stacks
- Confirm pods are reachable, configmaps applied, cross-zone placement correct

### Tanish Owns (Experiments + Evaluation, Phases 7–8)

- Adapt experiment runners for Kubernetes (kubectl scale / exec instead of compose)
- Create `workload-k8s.json` variants for both stacks
- Cloud failure injection (crash, delay, optionally partition)
- Run all 7 scenarios on both stacks in cloud
- Collect metrics, build comparison tables, feed the final report

### Shared (Phase 9 Integration + Phase 10 Later Work)

- Joint cloud validation against report claims
- Repeated-run automation (Phase 10)
- Terraform, GCS exports, plots (Phase 10)

---

## Phase 1: Shared Cloud Foundations

These tasks must be completed first because they unblock both stacks.

### Swarup

- [x] Create or verify GCP project setup
- [x] Enable required APIs:
  - [x] `container.googleapis.com`
  - [x] `artifactregistry.googleapis.com`
  - [x] `storage.googleapis.com`
- [x] Create Artifact Registry repository
- [x] Create initial GKE cluster
- [x] Optionally create two node pools for placement:
  - [x] `building-a-pool`
  - [x] `building-b-pool`
- [x] Share with Tanish:
  - [x] cluster name
  - [x] region
  - [x] kube credentials workflow
  - [x] Artifact Registry path

### Tanish

- [x] Review and validate the base cloud config assumptions:
  - [x] internal-only services
  - [x] app-layer latency model remains enabled
  - [x] peer identity/env var mapping
- [x] Confirm which current experiment settings must remain unchanged in cloud:
  - [x] cache capacity
  - [x] topology delay values
  - [x] peer IDs
  - [x] scenario names
  - [x] seeds

### Shared Exit Condition

- [x] Both teammates can access the GKE cluster
- [x] Both teammates can push/pull images from Artifact Registry

### Phase 1 Frozen Outputs

- GCP project: `resilientp2p-492916`
- Cluster: `resilientp2p-gke`
- Zone: `us-central1-f`
- Artifact Registry repo: `us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p`
- Kube credentials workflow:
  - `gcloud container clusters get-credentials resilientp2p-gke --zone us-central1-f --project resilientp2p-492916`
- Cloud config assumptions frozen for later phases:
  - internal-only Kubernetes Services
  - app-layer delays remain enabled in cloud
  - topology delays stay `5/35/120 ms`
  - cache capacity stays `10485760` bytes
  - peer IDs stay `peer-a1`, `peer-a2`, `peer-b1`
  - scenario names and seed stay unchanged from local experiment configs
  - internal origin DNS is used in-cluster instead of a Cloud Run placeholder
  - node placement labels use lowercase `building=a` and `building=b`

---

## Phase 2: Image Build and Registry

These tasks can happen in parallel after the registry exists.

### Swarup (drove all 5 via scripts/build-and-push.sh)

- [x] Build and push DHT-side images:
  - [x] `dht-peer`
  - [x] `dht-bootstrap`
- [x] Build and push coordinator-side images:
  - [x] `coordinator`
  - [x] `coord-peer`
  - [x] `origin`
- [x] Use git SHA tags (`bf3db98`) plus `:v1` alias
- [x] Document the pushed image URIs

### Pushed Image URIs

```
us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p/coordinator:bf3db98
us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p/coord-peer:bf3db98
us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p/origin:bf3db98
us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p/dht-bootstrap:bf3db98
us-central1-docker.pkg.dev/resilientp2p-492916/resilientp2p/dht-peer:bf3db98
```

Each image is also tagged `:v1`, which is what the manifests reference.

### Shared Exit Condition

- [x] All required images exist in Artifact Registry
- [x] Image tag naming convention is agreed and reproducible (git SHA + `v1`)

---

## Phases 3–5: Deploy + Smoke Test — COMPLETE (Swarup, 2026-04-11)

All done by Swarup. Both stacks are live in GKE, smoke-tested, and working.

### What was deployed

- Namespaces: `p2p-coordinator`, `p2p-dht`
- ConfigMaps: `p2p-common-config` in each namespace
- 6 pods per stack: coordinator, origin, dht-bootstrap, peer-a1, peer-a2, peer-b1
- All pods `Running 1/1`, zero restarts
- Image tag on all manifests: `:v1` (git SHA `bf3db98`)

### Smoke test results (2026-04-11)

| Step | Coordinator Stack | DHT Stack |
|------|-------------------|-----------|
| Cold fetch (origin) | 195 ms, source=origin | 193 ms, source=origin |
| Same-building peer fetch (peer-a2 → peer-a1) | 95 ms, source=peer | 74 ms, source=peer |
| Cross-building peer fetch (peer-b1 → peer-a2) | 107 ms, source=peer | 111 ms, source=peer |

Latency ordering is correct in both stacks: origin > cross-building > same-building.

---

## Phase 6+: Tanish's Handoff — Experiments + Evaluation

Everything below is Tanish's responsibility. Swarup is available for infra help if needed.

### Completed status (2026-04-12)

- [x] Both experiment runners were adapted for Kubernetes:
  - [x] `p2p-coordinator/experiments/runner.py`
  - [x] `p2p-dht/experiments/runner.py`
- [x] Both cloud workload specs were created:
  - [x] `p2p-coordinator/experiments/workload-k8s.json`
  - [x] `p2p-dht/experiments/workload-k8s.json`
- [x] One failure-injection path per stack was manually validated first
- [x] The coordinator cloud fallback issue was investigated and fixed
- [x] All 7 scenarios were executed on both stacks in GKE
- [x] Cloud result artifacts were collected under each stack's `results-k8s/`
- [x] A consolidated single-run cloud comparison table was generated:
  - [x] [CLOUD_RESULTS_COMPARISON.md](CLOUD_RESULTS_COMPARISON.md)

Known remaining limitation from the completed single-run cloud suite:

- `DHT Timeout Fallback Test` still degrades to origin service for the warm-object request. This is a measured system limitation, not a runner or deployment failure, and should be reported as such.

### Getting started — cluster access

```bash
# 1. Auth and get cluster credentials
gcloud auth login
gcloud config set project resilientp2p-492916
gcloud container clusters get-credentials resilientp2p-gke \
  --zone us-central1-f --project resilientp2p-492916

# 2. Verify both stacks are running
kubectl get pods -n p2p-coordinator
kubectl get pods -n p2p-dht
```

### Port-forward commands

To reach pods from your local machine:

```bash
# Coordinator stack (ports 7001-7003)
kubectl port-forward -n p2p-coordinator svc/peer-a1 7001:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-a2 7002:7000 &
kubectl port-forward -n p2p-coordinator svc/peer-b1 7003:7000 &
kubectl port-forward -n p2p-coordinator svc/coordinator 8000:8000 &

# DHT stack (ports 9001-9003)
kubectl port-forward -n p2p-dht svc/peer-a1 9001:7000 &
kubectl port-forward -n p2p-dht svc/peer-a2 9002:7000 &
kubectl port-forward -n p2p-dht svc/peer-b1 9003:7000 &
kubectl port-forward -n p2p-dht svc/coordinator 9000:8000 &
```

Quick health check after port-forward:

```bash
curl -s http://localhost:7001/health   # coordinator stack peer-a1
curl -s http://localhost:9001/health   # DHT stack peer-a1
```

### Useful kubectl commands

```bash
# View logs for a specific pod
kubectl logs -n p2p-coordinator deployment/peer-a1
kubectl logs -n p2p-dht deployment/peer-a1

# Extract METRIC lines from all coordinator-stack peers
kubectl logs -n p2p-coordinator deployment/peer-a1 | grep "^METRIC:"
kubectl logs -n p2p-coordinator deployment/peer-a2 | grep "^METRIC:"
kubectl logs -n p2p-coordinator deployment/peer-b1 | grep "^METRIC:"

# Get cache stats from a peer
curl -s http://localhost:7001/stats | python3 -m json.tool

# Check which node a pod landed on (verify zone placement)
kubectl get pods -n p2p-coordinator -o wide
```

### Task 1: Adapt runner.py for Kubernetes

Status: [x] Complete

Both `p2p-coordinator/experiments/runner.py` and `p2p-dht/experiments/runner.py`
currently use Docker Compose commands. These need K8s equivalents:

| Local (Docker Compose) | Cloud (Kubernetes) |
|---|---|
| `docker compose kill <service>` | `kubectl scale deployment/<service> -n <namespace> --replicas=0` |
| `docker compose up -d <service>` (restart) | `kubectl scale deployment/<service> -n <namespace> --replicas=1` |
| `docker network disconnect <network> <container>` | `kubectl exec deployment/<service> -n <namespace> -- tc qdisc add dev eth0 root netem loss 100%` |
| `docker network connect <network> <container>` | `kubectl exec deployment/<service> -n <namespace> -- tc qdisc del dev eth0 root` |
| `docker compose exec <service> tc qdisc add dev eth0 root netem delay <N>ms` | `kubectl exec deployment/<service> -n <namespace> -- tc qdisc add dev eth0 root netem delay <N>ms` |
| `docker compose exec <service> tc qdisc del dev eth0 root` | `kubectl exec deployment/<service> -n <namespace> -- tc qdisc del dev eth0 root` |

All pods already have `NET_ADMIN` capability, so `tc` commands will work.

After scaling to 0 and back to 1, wait for the pod to pass its readiness probe
before continuing:

```bash
kubectl rollout status deployment/<service> -n <namespace> --timeout=60s
```

### Task 2: Create workload-k8s.json

Status: [x] Complete

Copy `workload.json` and change:

- `compose_file` → remove or replace with a `namespace` field
- `peer_map` URLs → use `localhost` port-forward ports (7001/7002/7003 for coordinator, 9001/9002/9003 for DHT)
- `coordinator_url` → `http://localhost:8000` (coordinator stack) or `http://localhost:9000` (DHT stack)
- `bootstrap_wait_seconds` → increase to 8–10 (pod restart is slower than compose restart)
- `service_ready_timeout_seconds` → increase to 90

All 7 scenarios, seed, topology, and object names stay unchanged.

### Task 3: Run all 7 scenarios on both stacks

Status: [x] Complete

For each stack:

1. Start the port-forwards
2. Run `python runner.py --config workload-k8s.json`
3. Collect the results from the `results/` directory
4. Also collect pod logs: `kubectl logs -n <namespace> deployment/<peer> > logs/<peer>.log`

### Task 4: Collect metrics and build comparison

Status: [x] Complete for single-run cloud results

From pod logs, extract `METRIC:` lines. Key metrics to compare:

- **Cache hit rate** per scenario per stack
- **p50/p95 latency** for peer fetches (same-building vs cross-building)
- **Origin fallback rate** — how often did the system fail all the way to origin?
- **Fallback event count** — `DHT_FALLBACK` events in coordinator stack, coordinator fallback events in DHT stack
- **Recovery time** — after crash/restart, how quickly does the first peer-fetch succeed?

Result naming convention: `<stack>_<scenario>_<timestamp>_<git-sha>.json`

Example: `coordinator_locality-smoke_20260411T1830_bf3db98.json`

### Task 5: Failure injection validation

Status: [x] Complete

Before running the full 7-scenario suite, manually verify fault injection works:

```bash
# Kill coordinator in coordinator stack
kubectl scale deployment/coordinator -n p2p-coordinator --replicas=0

# Fetch should still work via DHT fallback
curl -s http://localhost:7001/trigger-fetch/fallback-test-1 | python3 -m json.tool

# Bring it back
kubectl scale deployment/coordinator -n p2p-coordinator --replicas=1
kubectl rollout status deployment/coordinator -n p2p-coordinator --timeout=60s
```

Repeat for DHT stack (kill dht-bootstrap instead).

### Exit Condition

- [x] All 7 scenarios run on both stacks in cloud
- [x] Metrics collected and consolidated comparison table generated
- [x] Results match the expected behavior from local tests qualitatively

Notes:

- The comparison closeout for Phase 6/9 is captured in [CLOUD_RESULTS_COMPARISON.md](CLOUD_RESULTS_COMPARISON.md).
- Plot generation and repeated-run aggregation remain Phase 10 work.

---

## Phase 9: Final Joint Testing

After Tanish has cloud results, both teammates validate together:

- [x] Warm-object fallback paths behave correctly in both architectures, with the documented exception of the DHT timeout scenario
- [x] Cold-object misses degrade to origin as expected
- [x] The latency ordering (same-building < cross-building < origin) holds in the cloud smoke results
- [x] The metrics are sufficient for the current report update and single-run cloud comparison
- [x] A side-by-side comparison table exists for the current cloud run

Joint-validation output:

- [x] [CLOUD_RESULTS_COMPARISON.md](CLOUD_RESULTS_COMPARISON.md)

---

## Phase 10: Repeated Runs and Aggregation

Completed Phase 10 deliverables now present in the repo:

- [x] Repeated-run execution script added:
  - [x] [run-k8s-suite.sh](scripts/run-k8s-suite.sh)
- [x] Aggregate summary script added:
  - [x] [aggregate-results.py](scripts/aggregate-results.py)
- [x] Plot generation script added:
  - [x] [plot-results.py](scripts/plot-results.py)
- [x] GCS export script added:
  - [x] [export-to-gcs.sh](scripts/export-to-gcs.sh)
- [x] Terraform baseline for reproducible cloud infra added:
  - [x] [infra/terraform/main.tf](infra/terraform/main.tf)
  - [x] [infra/terraform/README.md](infra/terraform/README.md)
- [x] Aggregate repeated-run outputs generated:
  - [x] [aggregate-summary.json](results-aggregate/aggregate-summary.json)
  - [x] [aggregate-summary.md](results-aggregate/aggregate-summary.md)
  - [x] [PHASE10_REPORT_HANDOFF.md](results-aggregate/PHASE10_REPORT_HANDOFF.md)
  - [x] plot artifacts under [results-aggregate/plots](results-aggregate/plots)

Phase 10 execution summary:

- Coordinator stack aggregate uses **5 runs**
- DHT stack aggregate uses **5 runs**
- Core workload aggregation is complete
- Failure-injection aggregation is complete
- Report-ready markdown tables and PNG plots are present

Interpretation notes:

- The aggregate results make sense and are consistent with the earlier single-run cloud behavior.
- Source-count means are effectively deterministic across runs, which is why many standard deviations are `0.0`.
- Bandwidth-reduction values are stable and high in the core workloads:
  - `66.7%` for locality smoke
  - `81.8%` for course burst
  - `88.2%` for independent churn
  - `90.0%` coordinator / `85.0%` DHT for correlated churn
- Coordinator-primary remains lower-latency in the churn-heavy workloads.
- DHT timeout remains the weakest case:
  - all requests go to `origin`
  - mean and p95 latencies are much higher than all other scenarios

Practical note:

- Raw `results-k8s-multi/` directories are intentionally not versioned in git (see `.gitignore`), so the committed aggregate outputs are the durable summary artifacts in the repository.

---

## Future Works

These items are not required to claim the current cloud evaluation, but they are still open beyond the completed Phase 10 aggregation work.

- [ ] Validate the Terraform baseline end-to-end as the primary provisioning path, not just as checked-in IaC
- [ ] Integrate Kubernetes application deployment more tightly with Terraform or a higher-level deployment workflow
- [ ] Perform and document a full GCS export/archive run if long-term artifact storage is required for submission
- [ ] Add optional Prometheus/Grafana monitoring
- [ ] Add optional richer partition experiments beyond the current failure-injection set
- [ ] Extend repeated-run analysis with confidence intervals and additional statistical tests in report-facing summaries
- [ ] Add stricter archival conventions for raw multi-run artifacts if the full raw dataset needs to be shared outside GCS

---

## Phase 11: Post-Report Cache Correctness and Security Hardening

Phase 11 converts the report's future-work limitations into implementation work. This phase should be done incrementally and should preserve the existing cloud evaluation behavior by default.

Detailed step-by-step implementation notes are tracked in [POST_REPORT_HARDENING_ROADMAP.md](POST_REPORT_HARDENING_ROADMAP.md).

### Recommended Order

| Order | Workstream | Difficulty | Primary Risk | Status |
|---:|---|---|---|---|
| 1 | Dynamic object invalidation | Medium | Stale cache/provider state across coordinator and DHT | Complete |
| 2 | Peer authentication and access control | Medium-Hard | Breaking current local/GKE smoke tests | Planned |
| 3 | Malicious-peer resilience | Hard | Reputation requires stable identity and careful false-positive handling | Planned |

### Phase 11A: Dynamic Object Invalidation

Goal: support mutable/dynamic objects without serving stale peer-cached content.

- [x] Extend `ObjectMetadata` in both stacks with version/cacheability fields:
  - [x] `version`
  - [x] `cacheability` (`immutable`, `ttl`, `dynamic`)
  - [x] `max_age_seconds`
  - [x] `expires_at`
  - [x] optional `etag`
- [x] Update peer caches to reject or evict expired/stale entries before serving `/get-object/{object_id}`
- [x] Add coordinator invalidation endpoints:
  - [x] `POST /invalidate/{object_id}`
  - [x] `POST /invalidate-prefix`
  - [x] optional `POST /revalidate/{object_id}`
- [x] Propagate invalidation to coordinator provider index and peer/DHT provider records
- [x] Update DHT provider descriptors to include object version and expiry metadata
- [x] Add tests/scenarios:
  - [x] warm object, invalidate, next peer request returns `source=origin`
  - [x] short TTL expires, next peer request revalidates/refetches
  - [x] stale DHT provider ignored because version mismatches requested version
  - [x] prefix invalidation clears matching mutable object groups

Exit condition:

- [x] Existing immutable workloads still pass unchanged by default because new metadata fields are backwards-compatible
- [x] Dynamic invalidation scenario proves stale peer data is not served through deterministic validation and GKE hardening runs for both hybrid stacks

### Phase 11B: Peer Authentication and Access Control

Goal: restrict discovery and transfer operations to authenticated campus peers.

- [ ] Add `AUTH_MODE` config with:
  - [ ] `none` for current local/GKE experiments
  - [ ] `shared_token` for first implementation
  - [ ] future `certificate` or `oidc`
- [ ] Add auth middleware or dependency to coordinator and peer FastAPI apps
- [ ] Require authenticated identity for:
  - [ ] peer registration
  - [ ] heartbeat
  - [ ] content publication
  - [ ] lookup
  - [ ] transfer report
  - [ ] peer object fetch
- [ ] Add object access metadata:
  - [ ] `visibility`
  - [ ] `allowed_groups`
- [ ] Enforce access checks before returning providers and before serving content bytes
- [ ] Add Kubernetes Secret support for demo tokens/certs
- [ ] Add tests:
  - [ ] missing token is rejected
  - [ ] invalid token is rejected
  - [ ] authorized peer can run locality smoke test
  - [ ] unauthorized peer cannot fetch restricted object

Exit condition:

- [ ] `AUTH_MODE=none` preserves current experiments
- [ ] `AUTH_MODE=shared_token` protects registration, lookup, publication, and peer transfer paths

### Phase 11C: Malicious-Peer Resilience

Goal: detect and reduce the impact of peers that advertise false metadata or serve invalid content.

- [ ] Add peer behavior counters:
  - [ ] checksum mismatch count
  - [ ] failed peer fetch count
  - [ ] inconsistent metadata publication count
  - [ ] unavailable provider count
- [ ] Add provider reputation states:
  - [ ] `healthy`
  - [ ] `suspect`
  - [ ] `quarantined`
- [ ] Update coordinator provider selection to exclude quarantined peers and deprioritize suspect peers
- [ ] Update peer fetch pipeline to try alternate candidates after invalid content or unavailable provider
- [ ] Reject conflicting metadata claims for the same object version
- [ ] Add optional signed metadata as a later subphase
- [ ] Add tests:
  - [ ] bad-content peer is detected
  - [ ] repeated bad peer is quarantined
  - [ ] requester retries healthy provider after bad provider fails
  - [ ] conflicting metadata publication is rejected

Exit condition:

- [ ] Bad peers no longer poison lookup results indefinitely
- [ ] Healthy peers remain usable while suspect/quarantined peers are deprioritized or excluded

### Phase 11 Documentation Outputs

- [ ] Update `Resilience_PRD.md` acceptance criteria as each workstream lands
- [ ] Update `GKE_DEPLOYMENT.md` with required Secrets/config for auth
- [ ] Add new workload scenarios for invalidation/auth/malicious-peer testing
- [ ] Add result summaries under a new `results-hardening/` directory if cloud validation is repeated

---

## Coordination Checkpoints

| # | Checkpoint | Owner | Status |
|---|------------|-------|--------|
| 1 | GCP project, cluster, and registry ready | Swarup | done |
| 2 | All 5 images built and pushed | Swarup | done |
| 3 | Both stacks deployed and smoke-tested | Swarup | done |
| 4 | Runner adapted for K8s | Tanish | done |
| 5 | All 7 scenarios run on both stacks | Tanish | done |
| 6 | Single-run cloud comparison table / results closeout | Both | done |
| 7 | Repeated-run automation and aggregate outputs | Both | done |

---

## Important Notes

- Do **not** remove the application-layer delay model in cloud MVP.
- Do **not** treat raw GCP latency as a replacement for the campus simulation model.
- Do **not** start with repeated runs before manual cloud validation succeeds.
- Do **not** mix both architectures in one test session unless namespaces, services, and result collection are clearly isolated.
- Single-run cloud comparison is preserved for traceability, but repeated-run aggregate outputs now exist under `results-aggregate/`.
- The cluster costs ~$65/month. Tear down after evaluation is done:

```bash
gcloud container clusters delete resilientp2p-gke --zone us-central1-f --project resilientp2p-492916 --quiet
gcloud artifacts repositories delete resilientp2p --location=us-central1 --project=resilientp2p-492916 --quiet
```
