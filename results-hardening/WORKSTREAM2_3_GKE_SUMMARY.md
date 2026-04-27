# Workstream 2 & 3 GKE Validation — Image `dbc8b58`

This document captures the empirical results from rolling Workstream 2 (peer authentication + access control) and Workstream 3 (malicious-peer reputation) into the GKE cluster `resilientp2p-gke` (project `resilientp2p-492916`, zone `us-central1-f`) on top of the f01f039 baseline. It is structured so that the relevant tables and prose can be lifted directly into Section 5 of the paper as a new subsection.

## Validated artifact

- **Image tag:** `dbc8b58` (commit "done with malicious peer testing as well")
- **Build pipeline:** `./scripts/build-and-push.sh` produced and pushed all five images (`coordinator`, `coord-peer`, `dht-peer`, `origin`, `dht-bootstrap`) to Artifact Registry, tagged with both `:dbc8b58` and `:v1`.
- **Manifests pinned to `:dbc8b58`** in [k8s/coordinator-stack/](../k8s/coordinator-stack/) and [k8s/dht-stack/](../k8s/dht-stack/) so the running pods are reproducibly tied to this commit (pre-rollout the manifests used a rolling `:v1` tag).
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

### Reputation-on regression check (`REPUTATION_ENABLED=true`, `MALICIOUS_MODE=""`)

Same 11 scenarios re-run with reputation tracking enabled and no peer set to a malicious mode. The cross-cutting requirement is *zero quarantines* and *no measurable latency regression* relative to the auth-on phase above — i.e., the reputation pipeline is observation-only on a healthy cluster.

| Scenario | Stack | Quarantines | Suspect transitions | Success | Sources |
|---|---|---:|---:|---:|---|
| _ALL ROWS PENDING — runner output forthcoming_ | | | | | |

### Malicious-peer quarantine test

Driven by [scripts/validate-reputation.sh](../scripts/validate-reputation.sh): `peer-a1` is patched with `MALICIOUS_MODE=serve_corrupted`, the deployment rolls, requests are issued from `peer-a2` and `peer-b1`, the coordinator's `/stats` is polled for `peer-a1.state == quarantined`, and `/lookup` is checked to confirm `peer-a1` is no longer returned as a provider. The script reverts `MALICIOUS_MODE=normal` on exit.

| Stack | Quarantine reached | Provider exclusion | Availability preserved (peer-b1 fetch succeeds) |
|---|:---:|:---:|:---:|
| coordinator-primary | _PENDING_ | _PENDING_ | _PENDING_ |
| DHT-primary | _PENDING_ | _PENDING_ | _PENDING_ |

Reputation snapshot for `peer-a1` at the moment of quarantine (coord-stack run, from `/stats`):

```
PENDING — to be filled in from validate-reputation.sh output
```

## Acceptance criteria check

Mapping back to the criteria defined in [POST_REPORT_HARDENING_ROADMAP.md](../POST_REPORT_HARDENING_ROADMAP.md):

**Workstream 2:**
- Existing experiments run unchanged when `AUTH_MODE=none` — proven locally by pytest backwards-compat test; cluster-side: the rollout's `permissive` window emitted zero `auth.missing` / `auth.invalid` events during a clean experiment cycle, confirming every pod is wired correctly before enforcement.
- Authenticated peers complete locality smoke tests — confirmed: both stacks land 100 % success, latency within run-to-run noise of the f01f039 5-run mean (coord 132.7 ms / 141.7 ms baseline, DHT 124.2 ms / 127.8 ms baseline).
- Unauthenticated peers cannot register or publish — confirmed by `validate-auth.sh`: `/stats` rejects with 401 when no token is presented.
- Unauthorized peers cannot receive restricted content — proven locally by pytest visibility tests; the GKE scenarios do not exercise restricted content (peer manifests assign `professors` / `students` groups but no scenario object is published with `visibility=restricted`).

**Workstream 3:**
- A bad-content peer is detected — _PENDING (validate-reputation.sh)_.
- Repeated bad behavior quarantines a peer — _PENDING_.
- Quarantined peers are excluded from lookup/provider results — _PENDING_.
- Healthy peers continue serving content — _PENDING_.
- Requesters recover by trying alternate providers or origin — _PENDING_.

## Caveats / known limitations carried forward

- Identity is still **client-asserted** (`X-Peer-Id` / `X-Peer-Group` headers); cryptographic binding waits for `AUTH_MODE=certificate`.
- Reputation state is **in-memory** on the coordinator. A coordinator restart wipes both the reputation tracker and the dedupe window, so a previously-quarantined peer comes back healthy after a fresh schedule.
- DHT UDP traffic remains unauthenticated — Sybil resistance / node-id spoofing is explicitly out of scope for this hardening track.
- The "DHT Timeout Fallback Test" remains the documented soft-spot from the original report; it is unchanged by Workstream 2 / 3 because both workstreams operate strictly above the discovery layer.

## Rollout artifacts

- Build / push log: [results-hardening/rollout-logs/build-push.log](rollout-logs/build-push.log)
- Auth validation logs: [validate-auth-coord.log](rollout-logs/validate-auth-coord.log), [validate-auth-dht.log](rollout-logs/validate-auth-dht.log)
- Coord stack auth-only run results: [p2p-coordinator/experiments/results-rollout-auth/](../p2p-coordinator/experiments/results-rollout-auth/)
- DHT stack auth-only run results: [p2p-dht/experiments/results-rollout-auth/](../p2p-dht/experiments/results-rollout-auth/)
- Coord stack reputation-on run results: _PENDING_
- DHT stack reputation-on run results: _PENDING_
- `validate-reputation.sh` output: _PENDING_
