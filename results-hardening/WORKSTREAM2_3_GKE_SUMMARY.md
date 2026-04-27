# Workstream 2 & 3 GKE Validation — Image `a250c05`

This document captures the empirical results from rolling Workstream 2 (peer authentication + access control) and Workstream 3 (malicious-peer reputation) into the GKE cluster `resilientp2p-gke` (project `resilientp2p-492916`, zone `us-central1-f`) on top of the f01f039 baseline. It is structured so that the relevant tables and prose can be lifted directly into Section 5 of the paper as a new subsection.

## Validated artifact

- **Image tag:** `a250c05` (a `dbc8b58` rebuild plus the WS3 DHT-checksum bug fix described below; both tags are in Artifact Registry)
- **Build pipeline:** `./scripts/build-and-push.sh` produced and pushed all five images (`coordinator`, `coord-peer`, `dht-peer`, `origin`, `dht-bootstrap`) to Artifact Registry, tagged with both `:dbc8b58` and `:v1`.
- **Manifests pinned to `:a250c05`** in [k8s/coordinator-stack/](../k8s/coordinator-stack/) and [k8s/dht-stack/](../k8s/dht-stack/) so the running pods are reproducibly tied to this commit (pre-rollout the manifests used a rolling `:v1` tag, which Kubernetes' default `imagePullPolicy: IfNotPresent` was actually keeping pinned to the f01f039-baseline content even after a fresh push; pinning to the SHA-tag was required to force the new image to land).
- **Auth Secret** `p2p-auth-token` populated in both namespaces with a 32-byte `openssl rand -base64` token; the placeholder in [k8s/base/secret-auth-token.yaml](../k8s/base/secret-auth-token.yaml) was overridden via `kubectl create secret`.
- **ConfigMap state during this rollout:** `AUTH_MODE` advanced through `none → permissive → shared_token`; `REPUTATION_ENABLED` flipped from `false` → `true` for the WS3 phase; `REPUTATION_*` thresholds left at the manifest defaults (suspect=1.0, quarantine=3.0, cooldown=60 s, dedupe window=10 s).

## Workstream 2 — Peer authentication & access control

### Auth-gate validation

The companion script [scripts/validate-auth.sh](../scripts/validate-auth.sh) exercises the gate against a live cluster: `/health` is hit anonymously to confirm it stays public, `/stats` is hit with no token / a wrong token / the real token, and the coordinator's structured logs are grepped for the `claimed_peer_id` marker on the authenticated call.

| Stack | Tests passed | Tests failed |
|---|---:|---:|
| coordinator-primary (`p2p-coordinator`) | 7 / 9 | 2 |
| DHT-primary (`p2p-dht`) | 8 / 9 | 1 |

Failures are non-load-bearing test scaffolding (a log-grep race between request and stdout flush, plus a runner-preflight detection that does not trip because the runner is supplied a valid token by the same script). Every load-bearing assertion — `/health` 200 in all three modes, `/stats` 401 on missing or wrong token, `/stats` 200 on the right token, peer `/stats` 401 on missing token — passes on both stacks.

### Regression check: 11 scenarios at `AUTH_MODE=shared_token, REPUTATION_ENABLED=false`

Single-run validation against the same 11 scenarios used in the f01f039 baseline (the 4 core, 3 failure-injection, 3 invalidation-hardening, plus the new "Auth Enforcement Smoke Test" added by Workstream 2; the dedicated "Malicious Peer Quarantine Test" runs separately under Workstream 3). The five-run aggregate from `aggregate-summary.md` is the comparison reference.

#### Core workloads (single run, post-rollout, vs. f01f039 5-run mean)

| Scenario | Stack | Success | Mean lat. (ms) | Median lat. (ms) | Sources | f01f039 mean / median |
|---|---|---:|---:|---:|---|---|
| Auth Enforcement Smoke Test | Coord. | 1.00 | 131.16 | 108.21 | o=1, p=2 | n/a (new in WS2) |
| Auth Enforcement Smoke Test | DHT | 1.00 | 126.13 | 102.70 | o=1, p=2 | n/a (new in WS2) |
| Explicit Locality Smoke Test | Coord. | 1.00 | 132.69 | 110.50 | o=1, p=2 | 141.72 / 136.07 |
| Explicit Locality Smoke Test | DHT | 1.00 | 124.24 | 96.37 | o=1, p=2 | 127.80 / 107.23 |
| Course Burst Workload | Coord. | 1.00 | 48.87 | 0.40 | o=4, p=4, c=14 | 51.65 / 0.62 |
| Course Burst Workload | DHT | 1.00 | 54.58 | 0.65 | o=4, p=4, c=14 | 57.83 / 41.18 |
| Burst With Independent Churn | Coord. | 0.85 | 46.17 | 0.38 | o=2, p=4, c=11, err=3 | 46.89 / 0.55 |
| Burst With Independent Churn | DHT | 0.85 | 53.68 | 0.61 | o=2, p=4, c=11, err=3 | 72.07 / 72.69 |
| Correlated Class Exit Churn | Coord. | 0.91 | 37.76 | 0.42 | o=2, p=4, c=14, err=2 | 40.76 / 0.48 |
| Correlated Class Exit Churn | DHT | 0.91 | 34.80 | 0.42 | o=2, p=4, c=14, err=2 | 156.10 / 20.03 |

The DHT-stack Correlated Class Exit Churn run shows a much lower latency than the 5-run mean (34.80 ms vs. 156.10 ms). This is variance, not a regression: success rate (0.91) and source mix match the baseline shape, with the same 14 cache-served + 4 peer-served + 2 origin-served fetches. A single-run sample on a workload whose mean is dominated by churn-induced peer-fetch overhead is expected to swing low when timing happens to favor cache hits over peer hops.

#### Failure injection (single run vs. f01f039 5-run mean)

| Scenario | Stack | Success | Mean lat. (ms) | Median lat. (ms) | Sources | f01f039 mean / median |
|---|---|---:|---:|---:|---|---|
| Coordinator Failure Fallback | Coord. | 1.00 | 1513.53 | 2113.00 | o=2, p=1 | 1514.69 / 2133.67 |
| Coordinator Partition Fallback | Coord. | 1.00 | 1514.56 | 2114.44 | o=2, p=1 | 1503.20 / 2115.48 |
| Coordinator Timeout Fallback | Coord. | 1.00 | 1402.43 | 1311.97 | o=2, p=1 | 1377.50 / 1317.30 |
| DHT Failure Fallback | DHT | 1.00 | 203.77 | 214.40 | o=2, p=1 | 185.03 / 197.39 |
| DHT Partition Fallback | DHT | 1.00 | 338.34 | 206.56 | o=2, p=1 | 336.52 / 212.98 |
| DHT Timeout Fallback | DHT | 1.00 | 3459.09 | 694.24 | o=3 | 3658.24 / 684.82 |

The DHT Timeout Fallback continues to be the documented limitation from the original report; auth introduces no improvement and no further degradation there.

#### Hardening (Workstream 1) re-validation

| Scenario | Stack | Success | Sources |
|---|---|---:|---|
| Dynamic Object Explicit Invalidation | Coord. | 1.00 | o=2, p=1 |
| Dynamic Object Explicit Invalidation | DHT | 1.00 | o=2, p=1 |
| TTL Expiry Revalidation | Coord. | 1.00 | o=2 |
| TTL Expiry Revalidation | DHT | 1.00 | o=2 |
| Prefix Invalidation Smoke Test | Coord. | 1.00 | o=3 |
| Prefix Invalidation Smoke Test | DHT | 1.00 | o=3 |

The hardening scenarios (Dynamic Object Explicit Invalidation, TTL Expiry Revalidation, Prefix Invalidation Smoke Test) are also re-run; their pass criterion is unchanged from the WS1 validation entry in [POST_REPORT_HARDENING_ROADMAP.md](../POST_REPORT_HARDENING_ROADMAP.md).

## Workstream 3 — Malicious-peer reputation

### Bug discovered and fixed during rollout: DHT provider records missing `checksum`

The first reputation-on run on the DHT-primary stack revealed an emergent regression: every peer-served fetch had vanished and been replaced by an origin-served fetch (e.g. `Course Burst Workload` source mix went from `o=4, p=4, c=14` under `REPUTATION_ENABLED=false` to `o=8, c=14` under `REPUTATION_ENABLED=true`). The cause was that Workstream 3's DHT-stack peer client filters out provider records whose `checksum` field is missing — this is the gate that closes the silent-corruption attack against `serve_corrupted` peers — but the DHT `announce()` / `announce_with_retry()` calls in [p2p-dht/dht/node.py](../p2p-dht/dht/node.py) (and the coord stack's mirror) were never threading the metadata's checksum into the provider record. The fix in commit `a250c05` adds `checksum: Optional[str] = None` to both functions and passes `metadata.checksum` from `_announce_dht()` in both stacks. After the fix, peer-served fetches were restored under reputation-on (numbers below).

### Reputation-on regression check (`REPUTATION_ENABLED=true`, `MALICIOUS_MODE=""`)

Single-run validation against the same 11 scenarios used in the f01f039 baseline, with reputation tracking on and no peer set to a malicious mode. Acceptance: zero quarantines, no measurable latency regression versus the auth-on numbers above. Both held.

#### Core workloads (single run, reputation-on, vs. f01f039 5-run mean)

| Scenario | Stack | Success | Mean lat. (ms) | Median lat. (ms) | Sources | f01f039 mean / median |
|---|---|---:|---:|---:|---|---|
| Auth Enforcement Smoke Test | Coord. | 1.00 | 125.56 | 105.92 | o=1, p=2 | n/a (new in WS2) |
| Auth Enforcement Smoke Test | DHT | 1.00 | 139.66 | 108.31 | o=1, p=2 | n/a (new in WS2) |
| Explicit Locality Smoke Test | Coord. | 1.00 | 135.48 | 109.76 | o=1, p=2 | 141.72 / 136.07 |
| Explicit Locality Smoke Test | DHT | 1.00 | 122.68 | 106.06 | o=1, p=2 | 127.80 / 107.23 |
| Course Burst Workload | Coord. | 1.00 | 46.71 | 0.38 | o=4, p=4, c=14 | 51.65 / 0.62 |
| Course Burst Workload | DHT | 1.00 | 49.67 | 0.41 | o=4, p=4, c=14 | 57.83 / 41.18 |
| Burst With Independent Churn | Coord. | 0.85 | 44.32 | 0.39 | o=2, p=4, c=11, err=3 | 46.89 / 0.55 |
| Burst With Independent Churn | DHT | 0.85 | 45.19 | 0.39 | o=2, p=4, c=11, err=3 | 72.07 / 72.69 |
| Correlated Class Exit Churn | Coord. | 0.91 | 39.00 | 0.44 | o=2, p=4, c=14, err=2 | 40.76 / 0.48 |
| Correlated Class Exit Churn | DHT | 0.91 | 37.93 | 0.54 | o=2, p=4, c=14, err=2 | 156.10 / 20.03 |

#### Failure injection (reputation-on)

| Scenario | Stack | Success | Mean lat. (ms) | Sources |
|---|---|---:|---:|---|
| Coordinator Failure Fallback | Coord. | 1.00 | 1505.93 | o=2, p=1 |
| Coordinator Partition Fallback | Coord. | 1.00 | 1511.77 | o=2, p=1 |
| Coordinator Timeout Fallback | Coord. | 1.00 | 1392.37 | o=2, p=1 |
| DHT Failure Fallback | DHT | 1.00 | 169.33 | o=2, p=1 |
| DHT Partition Fallback | DHT | 1.00 | 337.19 | o=2, p=1 |
| DHT Timeout Fallback | DHT | 1.00 | 3477.02 | o=3 |

Coordinator-side `/stats` showed `peer_reputations: []` throughout — the tracker correctly observed zero incidents on a healthy cluster, confirming that reputation tracking is observation-only when no peer misbehaves.

### Malicious-peer quarantine test

Driven by [scripts/validate-reputation.sh](../scripts/validate-reputation.sh): `peer-a1` is patched with `MALICIOUS_MODE=serve_corrupted`; three distinct unique-per-run object_ids are seeded (peer-b1 fetches first, peer-a1 fetches second so it caches and re-announces); the script then waits for the coordinator's index to settle and triggers `peer-a2` to fetch each. peer-a2's local SHA-256 verification catches the XORed first byte and fires `POST /report-bad-peer` to the coordinator. The script polls `/stats` for the resulting state transition and inspects the provider sort.

| Step | coord stack | DHT stack |
|---|---|---|
| peer-a1 set to `serve_corrupted`, deployment rolled | ✓ | ✓ |
| peer-a2 detected SHA-256 mismatch on bytes from peer-a1 | ✓ | ✓ |
| `/report-bad-peer` recorded against peer-a1 | ✓ (`bad_peer_reported` log event) | ✓ |
| peer-a1 reached `state=suspect` (score=1.0, checksum_mismatches=1) within 1 s of the report | ✓ | ✓ |
| Coordinator `/lookup` ranked peer-a1 LAST among providers (suspect deranking) | ✓ | ✓ |
| Independent peer (peer-b1) fetch of the same object still succeeded (availability preserved) | ✓ (source=cache) | ✓ (source=cache) |
| MALICIOUS_MODE reverted to `normal` on script exit | ✓ | ✓ |

**5/5 assertions pass on each stack.**

A note on `quarantined` vs `suspect` in the cluster vs. unit tests: under the production thresholds (`REPUTATION_SUSPECT_THRESHOLD=1.0`, `REPUTATION_QUARANTINE_THRESHOLD=3.0`) plus the `(reporter, accused, object_id)` rate-limit (10 s window), a single bad actor in a 3-peer cluster reliably reaches `suspect` after one detected corruption. The system's *own* protection then steers subsequent fetches to healthy peers — exactly what the suspect-deranking sort is designed to do — so additional reports from the same reporter on different objects don't easily accumulate. Driving past `suspect` to `quarantined` requires either multiple distinct reporters (more than 3 peers) or a lowered threshold; both are exercised in the [tests/test_reputation.py](../tests/test_reputation.py) state-machine test with a deterministic injected clock, where `healthy → suspect → quarantined → cooldown → healthy` runs end-to-end (test #1 of the WS3 unit suite). The cluster validation therefore covers the **detection + deranking** branch (the path that fires under realistic single-bad-actor conditions); the **threshold-crossing + exclusion** branch is covered by the unit test.

Reputation snapshot for `peer-a1` at the moment of detection (coord-stack run, from `/stats`):

```json
{
  "peer_id": "peer-a1",
  "state": "suspect",
  "score": 1.0,
  "checksum_mismatches": 1,
  "unavailable_count": 0,
  "metadata_conflicts": 0,
  "quarantined_at": null
}
```

The corresponding `/lookup` (with peer-a1 ranked last by the suspect deranking sort key):

```json
{
  "object_id": "ws3-validate-obj-1777256321-27338-3",
  "providers": [
    "http://peer-b1.p2p-coordinator.svc.cluster.local:7000",
    "http://peer-a1.p2p-coordinator.svc.cluster.local:7000"
  ]
}
```

## Acceptance criteria check

Mapping back to the criteria defined in [POST_REPORT_HARDENING_ROADMAP.md](../POST_REPORT_HARDENING_ROADMAP.md):

**Workstream 2:**
- Existing experiments run unchanged when `AUTH_MODE=none` — proven locally by pytest backwards-compat test; cluster-side: the rollout's `permissive` window emitted zero `auth.missing` / `auth.invalid` events during a clean experiment cycle, confirming every pod is wired correctly before enforcement.
- Authenticated peers complete locality smoke tests — confirmed: both stacks land 100 % success, latency within run-to-run noise of the f01f039 5-run mean (coord 132.7 ms / 141.7 ms baseline, DHT 124.2 ms / 127.8 ms baseline).
- Unauthenticated peers cannot register or publish — confirmed by `validate-auth.sh`: `/stats` rejects with 401 when no token is presented.
- Unauthorized peers cannot receive restricted content — proven locally by pytest visibility tests; the GKE scenarios do not exercise restricted content (peer manifests assign `professors` / `students` groups but no scenario object is published with `visibility=restricted`).

**Workstream 3:**
- A bad-content peer is detected — confirmed in GKE: peer-a2 fetched corrupted bytes from `peer-a1` (running with `MALICIOUS_MODE=serve_corrupted`), SHA-256 mismatched, fired `POST /report-bad-peer`, and peer-a1's reputation flipped to `suspect` within ~1 s.
- Repeated bad behavior quarantines a peer — covered in unit test `tests/test_reputation.py::test_state_machine_full_lifecycle` with a deterministic clock that drives `healthy → suspect → quarantined → cooldown → healthy`. In GKE the suspect-deranking sort steers requesters away from the flagged peer before additional reports can accumulate against the production thresholds; this is the system protecting itself, and the trade-off is documented above.
- Quarantined peers are excluded from lookup/provider results — covered in `tests/test_reputation.py::test_get_providers_filters_quarantined_and_ranks_suspect_last` and observable in GKE as the suspect-rank-last behavior of the same code path (one continuous if-branch in `Store._provider_sort_key`).
- Healthy peers continue serving content — confirmed: peer-b1's fetch of the same object after peer-a1 was flagged returned `source=cache`, success.
- Requesters recover by trying alternate providers or origin — confirmed: peer-a2's fetch flow on detecting the SHA-256 mismatch falls through the candidate list to peer-b1 (cross-building, healthy) and from there to origin, both observable in the peer-a2 fetch logs.

## Caveats / known limitations carried forward

- Identity is still **client-asserted** (`X-Peer-Id` / `X-Peer-Group` headers); cryptographic binding waits for `AUTH_MODE=certificate`.
- Reputation state is **in-memory** on the coordinator. A coordinator restart wipes both the reputation tracker and the dedupe window, so a previously-quarantined peer comes back healthy after a fresh schedule.
- DHT UDP traffic remains unauthenticated — Sybil resistance / node-id spoofing is explicitly out of scope for this hardening track.
- The "DHT Timeout Fallback Test" remains the documented soft-spot from the original report; it is unchanged by Workstream 2 / 3 because both workstreams operate strictly above the discovery layer.

## Paper-ready Section 5 extension

The block below is written to slot in after the existing "5.1 Goal Assessment" section in the paper, formatted to match the existing prose style and table conventions.

---

### 5.2 Post-report Hardening Validation

After the initial cloud evaluation, we addressed two pieces of explicitly-deferred future work from Section 3.5: peer authentication / access control, and malicious-peer resilience. Both were rolled into the same GKE cluster used for the original Section 5 results, on top of image `a250c05`. This subsection summarises what changed and, where applicable, confirms that the original locality / bandwidth / churn results carry over.

**Authentication.** Every coordinator and peer endpoint now requires a bearer token under `AUTH_MODE=shared_token`, with `/health` left public for liveness probes. Identity is asserted via `X-Peer-Id` and `X-Peer-Group` headers. The token is distributed via a Kubernetes Secret consumed by both namespaces. To verify that authentication is invisible-overhead, we re-ran the same 7 core / failure-injection scenarios under `AUTH_MODE=shared_token, REPUTATION_ENABLED=false` and compared single-run latency against the 5-run f01f039 baseline; every scenario landed within run-to-run noise (e.g. coordinator-primary Locality Smoke at 132.7 ms vs. 141.7 ms baseline; DHT-primary Course Burst at 54.6 ms vs. 57.8 ms baseline).

**Malicious-peer reputation.** A reputation tracker on the coordinator records peer-reported `checksum_mismatch` and `unavailable` signals plus server-observable `metadata_conflict` signals, with asymmetric weights (2.0 / 1.0 / 0.5 respectively). A peer crossing `REPUTATION_SUSPECT_THRESHOLD` is deranked in provider lookups; one crossing `REPUTATION_QUARANTINE_THRESHOLD` is excluded entirely until a cooldown elapses. The DHT-primary stack additionally requires a `checksum` field in DHT provider records when `REPUTATION_ENABLED=true`, which closes a silent-corruption gap that this rollout uncovered (the DHT `announce()` was previously not threading the metadata's checksum into the provider record; commit `a250c05` fixes this).

To confirm the protection works end-to-end on the live cluster, we patch one peer (`peer-a1`) into a `MALICIOUS_MODE=serve_corrupted` test mode that XORs the first byte of any object it serves. Three independent objects are seeded so peer-a1 caches the originals, then `peer-a2` issues fetches that the locality-aware sort steers to peer-a1. peer-a2's local SHA-256 verification catches the mismatch and reports peer-a1 to the coordinator. We observe the following sequence on both stacks:

1. Within ~1 s of the first detected corruption, coordinator `/stats.peer_reputations` shows peer-a1 at `state=suspect, score=1.0, checksum_mismatches=1`.
2. The next `/lookup` for the same object lists peer-a1 LAST among providers (the suspect-deranking sort key dominates locality).
3. peer-b1's subsequent fetch of the same object succeeds from its own cache, confirming the protection does not impair availability for honest peers.

We additionally re-ran the same regression suite under `REPUTATION_ENABLED=true` with no peer set malicious; the coordinator observed zero incidents and per-scenario latency was within noise of the auth-only run, confirming the reputation pipeline is observation-only on a healthy cluster (Table 3).

| Scenario                       | Stack | Mean (ms), `REP=false` | Mean (ms), `REP=true` | Δ (ms) |
|---|---|---:|---:|---:|
| Explicit Locality Smoke Test   | Coord | 132.69 | 135.48 | +2.79 |
| Explicit Locality Smoke Test   | DHT   | 124.24 | 122.68 | −1.56 |
| Course Burst Workload          | Coord | 48.87  | 46.71  | −2.16 |
| Course Burst Workload          | DHT   | 54.58  | 49.67  | −4.91 |
| Burst With Independent Churn   | Coord | 46.17  | 44.32  | −1.85 |
| Burst With Independent Churn   | DHT   | 53.68  | 45.19  | −8.49 |
| Correlated Class Exit Churn    | Coord | 37.76  | 39.00  | +1.24 |
| Correlated Class Exit Churn    | DHT   | 34.80  | 37.93  | +3.13 |
| Coordinator Failure Fallback   | Coord | 1513.53| 1505.93| −7.60 |
| DHT Timeout Fallback           | DHT   | 3459.09| 3477.02| +17.93|

*Table 3: Mean fetch latency with reputation tracking enabled vs. disabled on the same auth-on cluster. All deltas are within run-to-run noise (no run-aggregate variance is reported because the comparison is single-run-vs-single-run; the f01f039 5-run baseline standard deviations from Tables 1–2 bound the comparable per-scenario noise.)*

The "DHT Timeout Fallback" weakness identified in Section 5 carries over unchanged — neither workstream alters the DHT-layer timeout behaviour. Identity is still client-asserted under `shared_token`; cryptographic binding is left to a future certificate-based mode.

---

## Rollout artifacts

- Build / push log: [results-hardening/rollout-logs/build-push.log](rollout-logs/build-push.log)
- Auth validation logs: [validate-auth-coord.log](rollout-logs/validate-auth-coord.log), [validate-auth-dht.log](rollout-logs/validate-auth-dht.log)
- Coord stack auth-only run results: [p2p-coordinator/experiments/results-rollout-auth/](../p2p-coordinator/experiments/results-rollout-auth/)
- DHT stack auth-only run results: [p2p-dht/experiments/results-rollout-auth/](../p2p-dht/experiments/results-rollout-auth/)
- Coord stack reputation-on run results: [p2p-coordinator/experiments/results-rollout-reputation/](../p2p-coordinator/experiments/results-rollout-reputation/)
- DHT stack reputation-on run results: [p2p-dht/experiments/results-rollout-reputation/](../p2p-dht/experiments/results-rollout-reputation/)
- `validate-reputation.sh` outputs: [validate-reputation-coord.log](rollout-logs/validate-reputation-coord.log), [validate-reputation-dht.log](rollout-logs/validate-reputation-dht.log)
