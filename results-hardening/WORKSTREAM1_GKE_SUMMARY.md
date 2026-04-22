# Workstream 1 GKE Validation Summary

Validated on GKE with image tag `f01f039`.

## Coordinator-Primary Stack

Result directory: `p2p-coordinator/experiments/results-k8s-hardening/`

| Scenario | Success Rate | Expected Source Pattern | Observed Source Pattern | Result |
|---|---:|---|---|---|
| Dynamic Object Explicit Invalidation | 1.0 | origin, peer, origin | origin, peer, origin | PASS |
| TTL Expiry Revalidation | 1.0 | origin, origin | origin, origin | PASS |
| Prefix Invalidation Smoke Test | 1.0 | origin, origin, origin | origin, origin, origin | PASS |

## DHT-Primary Stack

Result directory: `p2p-dht/experiments/results-k8s-hardening/`

| Scenario | Success Rate | Expected Source Pattern | Observed Source Pattern | Result |
|---|---:|---|---|---|
| Dynamic Object Explicit Invalidation | 1.0 | origin, peer, origin | origin, peer, origin | PASS |
| TTL Expiry Revalidation | 1.0 | origin, origin | origin, origin | PASS |
| Prefix Invalidation Smoke Test | 1.0 | origin, origin, origin | origin, origin, origin | PASS |

## Interpretation

- Dynamic invalidation verifies that a warmed object can be peer-served before invalidation, then refetched from origin as a new version after invalidation.
- TTL expiry verifies that short-lived objects are not served from stale peer cache after expiry.
- Prefix invalidation verifies that grouped mutable objects can be invalidated together and refetched from origin afterward.
