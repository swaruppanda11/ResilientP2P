# Post-Report Hardening Roadmap

This document is the working plan for the next phase after the report submission. It focuses on the future-work items explicitly called out in the report:

1. explicit invalidation for dynamic web objects
2. peer authentication and access control
3. malicious-peer resilience

The goal is to implement these incrementally without breaking the existing report evaluation workflows.

---

## Recommended Order

| Order | Workstream | Difficulty | Why this order |
|---:|---|---|---|
| 1 | Dynamic object invalidation | Medium | Fixes cache correctness first and can be tested deterministically |
| 2 | Peer authentication and access control | Medium-Hard | Establishes stable peer identity and campus trust boundary |
| 3 | Malicious-peer resilience | Hard | Depends on identity, metadata integrity, and behavioral history |

---

## Workstream 1: Dynamic Object Invalidation

**Status:** Complete. The coordinator-primary and DHT-primary stacks support version/cacheability metadata, TTL expiry, single-object invalidation, prefix invalidation, revalidation-by-invalidation, peer-side stale eviction, DHT provider expiry/version filtering, deterministic local validation, and GKE validation for both hybrid architectures.

### Goal

Prevent stale cached content from being served when an object changes at the origin.

### Current Limitation

The current system treats content as immutable per `object_id`. This is safe for versioned objects like `lecture-1-video-v1`, but unsafe for mutable URLs or dynamic web objects.

### Implementation Steps

1. Extend `ObjectMetadata` in both stacks. [done]
   - Add `version` [done]
   - Add `cacheability` [done]
   - Add `max_age_seconds` [done]
   - Add `expires_at` [done]
   - Optionally add `etag` [done]

2. Update origin behavior. [done]
   - Allow test objects to return versioned metadata. [done]
   - Add a way to simulate an origin update for the same `object_id`. [done]

3. Update peer cache behavior. [done]
   - Reject expired cache entries before local `CACHE_HIT`. [done]
   - Refuse to serve expired or invalidated objects through `/get-object/{object_id}`. [done]
   - Evict stale entries on invalidation. [done]
   - Support prefix invalidation for mutable URL groups. [done]
   - Reject peer-served bytes when version or checksum does not match requested metadata. [done]

4. Update coordinator behavior. [done]
   - Add invalidation endpoint for a single object. [done]
   - Add prefix invalidation endpoint. [done]
   - Add revalidation endpoint that clears stale discovery/cache state before the next origin fetch. [done]
   - Remove invalidated provider entries. [done]
   - Track current object version. [done]

5. Update DHT behavior. [done]
   - Include version/expiry in provider descriptors. [done]
   - Ignore stale provider records on lookup. [done]
   - Re-announce only current object versions. [done]
   - Filter provider records by requested version when one is supplied. [done]

6. Add tests. [done]
   - Warm object, invalidate, then peer fetch should go to origin. [done]
   - TTL object expires, then peer fetch should not serve stale cache. [done]
   - DHT stale provider should be ignored after version mismatch. [done]
   - Prefix invalidation clears all matching local/provider entries. [done]

### Acceptance Criteria

- Existing immutable-object experiments still pass unchanged by default because new metadata fields are backwards-compatible and default to `cacheability=immutable`.
- Invalidated objects are not served from local cache. [validated locally and on GKE]
- Invalidated objects are not served from peer cache. [validated locally and on GKE]
- Coordinator lookup does not return stale providers. [validated locally and on GKE]
- DHT lookup does not use stale provider records. [validated locally and on GKE]

### GKE Validation

- Validated image tag: `f01f039`
- Coordinator-primary scenarios passed with `success_rate=1.0`:
  - `Dynamic Object Explicit Invalidation`
  - `TTL Expiry Revalidation`
  - `Prefix Invalidation Smoke Test`
- DHT-primary scenarios passed with `success_rate=1.0`:
  - `Dynamic Object Explicit Invalidation`
  - `TTL Expiry Revalidation`
  - `Prefix Invalidation Smoke Test`
- Result directories:
  - `p2p-coordinator/experiments/results-k8s-hardening/`
  - `p2p-dht/experiments/results-k8s-hardening/`

---

## Workstream 2: Peer Authentication and Access Control

### Goal

Ensure only trusted campus peers can participate in discovery, publication, and content transfer.

### Current Limitation

Any peer that can reach the service endpoints can register, publish metadata, perform lookups, and fetch peer content. The report scopes this to benign peers only.

### Implementation Steps

1. Add authentication configuration.
   - `AUTH_MODE=none`
   - `AUTH_MODE=shared_token`
   - Future: `AUTH_MODE=certificate`
   - Future: `AUTH_MODE=oidc`

2. Add auth middleware/dependencies.
   - Coordinator FastAPI app
   - Peer FastAPI app
   - Optional DHT advertisement wrapper

3. Protect coordinator endpoints.
   - `/register`
   - `/publish`
   - `/lookup/{object_id}`
   - `/heartbeat`
   - `/report-transfer`
   - `/stats` if needed

4. Protect peer endpoints.
   - `/get-object/{object_id}`
   - `/trigger-fetch/{object_id}` if used outside trusted runners
   - `/stats` if needed

5. Add access-control metadata.
   - `visibility`
   - `allowed_groups`
   - `owner`

6. Add Kubernetes Secret support.
   - Shared token for both namespaces.
   - Future certificate or OIDC config.

7. Add tests.
   - Missing token rejected.
   - Invalid token rejected.
   - Valid token allowed.
   - Unauthorized group cannot fetch restricted object.
   - `AUTH_MODE=none` keeps existing experiments working.

### Acceptance Criteria

- Existing experiments run unchanged when `AUTH_MODE=none`.
- Authenticated peers can complete locality smoke tests.
- Unauthenticated peers cannot register or publish.
- Unauthorized peers cannot receive restricted provider lists or content bytes.

---

## Workstream 3: Malicious-Peer Resilience

### Goal

Detect, isolate, and reduce the impact of peers that advertise false metadata, claim objects they do not have, or serve invalid content.

### Current Limitation

Checksum validation catches corrupted bytes only when the requester already has correct metadata. It does not prevent malicious metadata advertisements or repeated bad behavior.

### Implementation Steps

1. Add peer behavior tracking.
   - checksum mismatch count
   - failed peer fetch count
   - unavailable provider count
   - conflicting metadata publication count
   - version regression count

2. Add reputation states.
   - `healthy`
   - `suspect`
   - `quarantined`

3. Update provider selection.
   - Prefer healthy peers.
   - Deprioritize suspect peers.
   - Exclude quarantined peers.

4. Update coordinator conflict handling.
   - Reject conflicting checksum/size/version for same object version.
   - Attribute conflict to the publishing peer.
   - Increment peer suspicion score.

5. Update peer fetch pipeline.
   - On checksum mismatch, reject content.
   - Report bad provider behavior.
   - Retry next candidate provider.
   - Fall back to origin if no healthy peer succeeds.

6. Add malicious test modes.
   - Serve corrupted bytes.
   - Advertise object without having it.
   - Publish conflicting metadata.

7. Add optional signed metadata later.
   - Origin signs object metadata.
   - Peers advertise signed metadata.
   - Requesters verify signatures before accepting metadata.

### Acceptance Criteria

- A bad-content peer is detected.
- Repeated bad behavior quarantines a peer.
- Quarantined peers are excluded from lookup/provider results.
- Healthy peers continue serving content.
- Requesters recover by trying alternate providers or origin.

---

## Cross-Cutting Requirements

- Preserve both architecture stacks:
  - `p2p-coordinator`
  - `p2p-dht`
- Keep current cloud evaluation reproducible.
- Add feature flags for all hardening behavior.
- Add local tests before GKE validation.
- Add scenario-level result JSON for each new hardening test.
- Document each new endpoint and environment variable.

---

## First Implementation Target

Start with Workstream 1, Step 1:

> Extend `ObjectMetadata` in both stacks with version/cacheability fields while preserving backwards compatibility for existing experiments.

This is the safest first change because it should not alter existing behavior if defaults are chosen carefully.
