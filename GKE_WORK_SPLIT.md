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

### Swarup Owns

- shared cloud infrastructure scaffolding
- Artifact Registry and cluster setup
- DHT-primary stack deployment in GKE
- DHT-specific Kubernetes configuration

### Tanish Owns

- coordinator-primary stack deployment in GKE
- coordinator-side cloud validation
- result/metrics collection workflow for cloud MVP
- experiment validation against report claims

### Shared

- common base manifests and config conventions
- workload execution path
- final cloud testing
- repeated runs and final result generation

---

## Phase 1: Shared Cloud Foundations

These tasks must be completed first because they unblock both stacks.

### Swarup

- [ ] Create or verify GCP project setup
- [ ] Enable required APIs:
  - [ ] `container.googleapis.com`
  - [ ] `artifactregistry.googleapis.com`
  - [ ] `storage.googleapis.com`
- [ ] Create Artifact Registry repository
- [ ] Create initial GKE cluster
- [ ] Optionally create two node pools for placement:
  - [ ] `building-a-pool`
  - [ ] `building-b-pool`
- [ ] Share with Tanish:
  - [ ] cluster name
  - [ ] region
  - [ ] kube credentials workflow
  - [ ] Artifact Registry path

### Tanish

- [ ] Review and validate the base cloud config assumptions:
  - [ ] internal-only services
  - [ ] app-layer latency model remains enabled
  - [ ] peer identity/env var mapping
- [ ] Confirm which current experiment settings must remain unchanged in cloud:
  - [ ] cache capacity
  - [ ] topology delay values
  - [ ] peer IDs
  - [ ] scenario names
  - [ ] seeds

### Shared Exit Condition

- [ ] Both teammates can access the GKE cluster
- [ ] Both teammates can push/pull images from Artifact Registry

---

## Phase 2: Image Build and Registry

These tasks can happen in parallel after the registry exists.

### Swarup

- [ ] Build and push DHT-side images:
  - [ ] `dht-peer`
  - [ ] `dht-bootstrap`
- [ ] Use git SHA tags, not only static tags
- [ ] Document the pushed image URIs

### Tanish

- [ ] Build and push coordinator-side images:
  - [ ] `coordinator`
  - [ ] `coord-peer`
  - [ ] `origin`
- [ ] Use git SHA tags
- [ ] Document the pushed image URIs

### Shared Exit Condition

- [ ] All required images exist in Artifact Registry
- [ ] Image tag naming convention is agreed and reproducible

---

## Phase 3: Kubernetes Base Layer

This phase creates the common deployment foundation.

### Swarup

- [ ] Own the shared base Kubernetes structure:
  - [ ] namespaces
  - [ ] shared config conventions
  - [ ] base service naming conventions
- [ ] Verify DNS/service naming works for:
  - [ ] `coordinator`
  - [ ] `origin`
  - [ ] `dht-bootstrap`

### Tanish

- [ ] Define the required application env vars for cloud deployment:
  - [ ] `PEER_ID`
  - [ ] `LOCATION_ID`
  - [ ] `COORDINATOR_URL`
  - [ ] `ORIGIN_URL`
  - [ ] `DHT_BOOTSTRAP_HOST`
  - [ ] `DHT_BOOTSTRAP_PORT`
  - [ ] cache size
  - [ ] delay model values
- [ ] Verify these match current local behavior

### Shared Exit Condition

- [ ] Base manifests are consistent across both architectures
- [ ] Docker-compose service names are correctly mapped to Kubernetes DNS/service names

---

## Phase 4: Coordinator Stack Bring-Up (Tanish Lead)

### Tanish

- [ ] Update coordinator stack manifests with final image URIs
- [ ] Keep the current app-layer topology delay model enabled
- [ ] Deploy:
  - [ ] coordinator
  - [ ] origin
  - [ ] dht-bootstrap
  - [ ] initial peers
- [ ] Prefer stable peer identity in manifests
- [ ] Validate readiness of all coordinator-stack pods
- [ ] Run manual cloud validation:
  - [ ] origin fetch works
  - [ ] same-building peer fetch works
  - [ ] cross-building peer fetch works
  - [ ] coordinator crash fallback works
  - [ ] coordinator partition/timeout path can be exercised later if needed

### Swarup

- [ ] Review coordinator stack manifest assumptions for consistency with DHT stack
- [ ] Help validate bootstrap/DHT fallback connectivity if needed

### Exit Condition

- [ ] Coordinator-primary stack is working in GKE and matches the local system qualitatively

---

## Phase 5: DHT Stack Bring-Up (Swarup Lead)

### Swarup

- [ ] Update DHT stack manifests with final image URIs
- [ ] Keep the current app-layer topology delay model enabled
- [ ] Deploy:
  - [ ] coordinator fallback service
  - [ ] dht-bootstrap
  - [ ] origin
  - [ ] initial peers
- [ ] Validate readiness of all DHT-stack pods
- [ ] Run manual cloud validation:
  - [ ] origin fetch works
  - [ ] DHT lookup works
  - [ ] same-building peer fetch works
  - [ ] cross-building peer fetch works
  - [ ] DHT crash fallback works

### Tanish

- [ ] Review DHT stack behavior relative to report claims
- [ ] Cross-check fallback outputs against local expected behavior

### Exit Condition

- [ ] DHT-primary stack is working in GKE and matches the local system qualitatively

---

## Phase 6: Cloud Result Collection MVP

### Tanish

- [ ] Define the MVP cloud result collection method
- [ ] For initial cloud bring-up, collect:
  - [ ] pod logs
  - [ ] `/stats` outputs
  - [ ] any JSON artifacts already available
- [ ] Create a result naming convention by:
  - [ ] architecture
  - [ ] scenario
  - [ ] timestamp
  - [ ] git SHA

### Swarup

- [ ] Ensure pods expose the endpoints needed for result collection
- [ ] Help verify log access and namespace separation

### Exit Condition

- [ ] Both stacks produce cloud-observable outputs that can be compared to local runs

---

## Phase 7: Workload Runner Migration

This is the first phase where work becomes more collaborative again.

### Swarup

- [ ] Adapt DHT-side workload execution path for Kubernetes
- [ ] Define how DHT-side workload runs are launched in-cluster

### Tanish

- [ ] Adapt coordinator-side workload execution path for Kubernetes
- [ ] Define how coordinator-side workload runs are launched in-cluster

### Shared

- [ ] Decide whether the runner is:
  - [ ] a Kubernetes Job
  - [ ] a manually executed pod/script for MVP
- [ ] Preserve the same scenario names and semantics as local:
  - [ ] locality
  - [ ] burst
  - [ ] independent churn
  - [ ] correlated churn
  - [ ] fallback/failure scenarios

### Exit Condition

- [ ] At least one scenario can be run in cloud without manual per-request curl commands

---

## Phase 8: Cloud Failure Injection

### Swarup

- [ ] Lead DHT-side failure injection implementation
- [ ] Validate:
  - [ ] DHT crash
  - [ ] DHT delay

### Tanish

- [ ] Lead coordinator-side failure injection implementation
- [ ] Validate:
  - [ ] coordinator crash
  - [ ] coordinator delay

### Shared

- [ ] Decide whether partition injection is:
  - [ ] required in MVP
  - [ ] deferred until after crash/delay validation
- [ ] Keep the first cloud failure injection simple and reproducible

### Exit Condition

- [ ] Both stacks support at least crash and delay fault experiments in cloud

---

## Phase 9: Final Joint Testing Before Repeated Runs

This is the first true integration/testing checkpoint after independent work.

### Required Joint Tests

- [ ] Coordinator locality smoke test in cloud
- [ ] DHT locality smoke test in cloud
- [ ] Coordinator fallback smoke/failure test in cloud
- [ ] DHT fallback smoke/failure test in cloud
- [ ] One workload scenario per stack in cloud
- [ ] Compare cloud outputs to local expected behavior

### Questions to Answer Before Proceeding

- [ ] Do warm-object fallback paths behave correctly in both architectures?
- [ ] Do cold-object misses degrade to origin as expected?
- [ ] Do cloud latencies preserve the intended same-building vs cross-building vs origin ordering under the app-layer model?
- [ ] Are the metrics and logs sufficient for repeated runs?

### Exit Condition

- [ ] Both teammates agree the cloud MVP is correct and ready for repeated experiments

---

## Phase 10: After MVP Validation

Only start this after all phases above are complete.

### Shared Later Work

- [ ] Add Terraform for reproducible infra provisioning
- [ ] Add GCS artifact export
- [ ] Add repeated-run automation
- [ ] Add aggregate summary scripts / plots
- [ ] Add optional Prometheus/Grafana
- [ ] Add optional richer partition experiments

---

## Coordination Checkpoints

| # | Checkpoint | Owner | Unblocks |
|---|------------|-------|----------|
| 1 | GCP project, cluster, and registry ready | Swarup | Both can build/push/deploy |
| 2 | Shared image tags and service naming finalized | Both | Stack manifests can be finalized |
| 3 | Coordinator stack validated in GKE | Tanish | Coordinator-side cloud testing |
| 4 | DHT stack validated in GKE | Swarup | DHT-side cloud testing |
| 5 | Cloud result collection path defined | Tanish | Workload execution in cloud |
| 6 | Both stacks pass manual cloud validation | Both | Repeated runs can begin later |

---

## Recommended Immediate Execution Order

1. Swarup sets up cluster + registry
2. Tanish freezes env/config assumptions from local
3. Both push their images
4. Swarup finalizes shared base manifests
5. Tanish deploys and validates coordinator stack
6. Swarup deploys and validates DHT stack
7. Both do final joint cloud validation
8. Then move to workload jobs and repeated experiments

---

## Important Notes

- Do **not** remove the application-layer delay model in cloud MVP.
- Do **not** treat raw GCP latency as a replacement for the campus simulation model.
- Do **not** start with repeated runs before manual cloud validation succeeds.
- Do **not** mix both architectures in one test session unless namespaces, services, and result collection are clearly isolated.
