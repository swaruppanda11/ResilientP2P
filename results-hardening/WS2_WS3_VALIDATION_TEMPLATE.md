# Workstream 2 and 3 Validation Fill Template

Use this file after running the live-cluster validation scripts:

```bash
./scripts/validate-auth.sh | tee results-hardening/rollout-logs/validate-auth-coord.log
./scripts/validate-auth.sh -n p2p-dht | tee results-hardening/rollout-logs/validate-auth-dht.log

./scripts/validate-reputation.sh | tee results-hardening/rollout-logs/validate-reputation-coord.log
./scripts/validate-reputation.sh -n p2p-dht | tee results-hardening/rollout-logs/validate-reputation-dht.log
```

Prerequisites:

- `kubectl`, `jq`, `curl`, and `python3` are installed.
- `kubectl` is authenticated to the target cluster.
- `AUTH_MODE=shared_token` in both namespaces.
- `p2p-auth-token` Secret exists in both namespaces.
- `REPUTATION_ENABLED=true` before running `validate-reputation.sh`.

## Workstream 2 — Peer authentication

### Auth-gate validation

| Stack | Tests passed | Tests failed | Notes |
|---|---:|---:|---|
| coordinator-primary (`p2p-coordinator`) | `__ / __` | `__` | `__` |
| DHT-primary (`p2p-dht`) | `__ / __` | `__` | `__` |

### Load-bearing auth assertions

Replace each row with the observed result from the script output.

| Assertion | coordinator-primary | DHT-primary |
|---|---|---|
| `/health` returns `200` without auth | `PASS/FAIL` | `PASS/FAIL` |
| coordinator `/stats` returns `401` without token | `PASS/FAIL` | `PASS/FAIL` |
| coordinator `/stats` returns `401` with wrong token | `PASS/FAIL` | `PASS/FAIL` |
| peer `/stats` returns `401` without token | `PASS/FAIL` | `PASS/FAIL` |
| coordinator gated call returns `200` with valid token | `PASS/FAIL` | `PASS/FAIL` |
| coordinator logs include claimed `X-Peer-Id` | `PASS/FAIL` | `PASS/FAIL` |
| peer `/stats` returns `200` with valid token | `PASS/FAIL` | `PASS/FAIL` |
| runner preflight fails loudly when `AUTH_TOKEN` is unset | `PASS/FAIL` | `PASS/FAIL` |

### Auth summary paragraph

Use and edit this paragraph after you have the numbers:

> `validate-auth.sh` confirmed that the peer-authentication gate is working on both stacks. In `p2p-coordinator`, the script recorded `__ / __` checks passing; in `p2p-dht`, it recorded `__ / __` checks passing. The load-bearing results were consistent across both namespaces: `/health` remained public, gated endpoints rejected missing and invalid tokens with `401`, valid bearer tokens were accepted, and coordinator logs attributed authenticated calls to the claimed peer identity. Any failing checks were limited to `__`.

## Workstream 3 — Malicious-peer resilience

### Quarantine validation

| Stack | Quarantine reached | Provider excluded from `/lookup` | Availability preserved | Notes |
|---|:---:|:---:|:---:|---|
| coordinator-primary (`p2p-coordinator`) | `PASS/FAIL` | `PASS/FAIL` | `PASS/FAIL` | `__` |
| DHT-primary (`p2p-dht`) | `PASS/FAIL` | `PASS/FAIL` | `PASS/FAIL` | `__` |

### Fill from `validate-reputation.sh`

Copy the relevant lines from each run:

#### coordinator-primary

```text
1. Set peer-a1 MALICIOUS_MODE=serve_corrupted
  __
2. Trigger fetches that exercise the malicious peer
  __
3. Poll coordinator /stats until peer-a1 is quarantined
  __
4. /lookup excludes peer-a1
  __
5. Availability preserved (peer-b1 fetch still works)
  __
Summary: __ passed, __ failed
```

#### DHT-primary

```text
1. Set peer-a1 MALICIOUS_MODE=serve_corrupted
  __
2. Trigger fetches that exercise the malicious peer
  __
3. Poll coordinator /stats until peer-a1 is quarantined
  __
4. /lookup excludes peer-a1
  __
5. Availability preserved (peer-b1 fetch still works)
  __
Summary: __ passed, __ failed
```

### Reputation snapshot at quarantine

If you run the script with `-v`, paste the `/stats` excerpt here:

#### coordinator-primary

```json
{
  "peer_id": "peer-a1",
  "state": "__",
  "score": "__",
  "incident_counts": "__"
}
```

#### DHT-primary

```json
{
  "peer_id": "peer-a1",
  "state": "__",
  "score": "__",
  "incident_counts": "__"
}
```

### Reputation summary paragraph

Use and edit this paragraph after you have the outputs:

> `validate-reputation.sh` confirmed whether a malicious peer serving corrupted bytes is isolated correctly. In each namespace, `peer-a1` was switched to `MALICIOUS_MODE=serve_corrupted`, client fetches were driven through the cluster, the coordinator was polled for reputation state, and `/lookup` was checked for provider exclusion. The observed results were: coordinator-primary `__`, DHT-primary `__`. Availability after quarantine was `__`, indicating that healthy peers and origin fallback `__`.

## Final paste target

The intended report file is:

- `results-hardening/WORKSTREAM2_3_GKE_SUMMARY.md`

Recommended insertion points:

- Workstream 2 auth results:
  Replace or tighten the existing "Auth-gate validation" subsection.
- Workstream 3 malicious-peer results:
  Replace the current `_PENDING_` entries under "Malicious-peer quarantine test".
