# Cloud Results Comparison

This file consolidates the single-run cloud experiment outputs generated in GKE on 2026-04-12.

Source artifacts:

- [p2p-coordinator/experiments/results-k8s](p2p-coordinator/experiments/results-k8s)
- [p2p-dht/experiments/results-k8s](p2p-dht/experiments/results-k8s)

The values below are taken directly from the `summary` sections of the result JSON files.

## Shared Topology

- Intra-location delay: `5 ms`
- Inter-location delay: `35 ms`
- Origin delay: `120 ms`
- Peer set: `peer-a1`, `peer-a2`, `peer-b1`

## Core Workload Comparison

| Scenario | Coordinator Success | Coordinator Mean (ms) | Coordinator Median (ms) | Coordinator Sources | DHT Success | DHT Mean (ms) | DHT Median (ms) | DHT Sources |
|---|---:|---:|---:|---|---:|---:|---:|---|
| Explicit Locality Smoke Test | 1.00 | 133.37 | 104.54 | `origin=1, peer=2` | 1.00 | 126.58 | 96.34 | `origin=1, peer=2` |
| Course Burst Workload | 1.00 | 48.12 | 0.68 | `origin=4, peer=4, cache=14` | 1.00 | 58.84 | 39.90 | `origin=4, peer=9, cache=9` |
| Burst With Independent Churn | 0.85 | 42.35 | 0.43 | `origin=2, peer=4, cache=11` | 0.85 | 69.09 | 72.47 | `origin=2, peer=10, cache=5` |
| Correlated Class Exit Churn | 0.91 | 39.93 | 0.52 | `origin=2, peer=4, cache=14` | 0.91 | 172.88 | 20.76 | `origin=3, peer=7, cache=10` |

## Failure-Injection Comparison

| Scenario | Warm Seed Source | Warm After Fault | Warm Candidates | Cold After Fault | Cold Candidates | Mean Latency (ms) | Median Latency (ms) |
|---|---|---|---:|---|---:|---:|---:|
| Coordinator Failure Fallback Smoke Test | `origin` | `peer` | 1 | `origin` | 0 | 1500.57 | 2102.02 |
| Coordinator Partition Fallback Test | `origin` | `peer` | 1 | `origin` | 0 | 1497.32 | 2102.25 |
| Coordinator Timeout Fallback Test | `origin` | `peer` | 1 | `origin` | 0 | 1368.59 | 1303.64 |
| DHT Failure Fallback Smoke Test | `origin` | `peer` | 1 | `origin` | 0 | 165.82 | 186.87 |
| DHT Partition Fallback Test | `origin` | `peer` | 1 | `origin` | 0 | 356.47 | 263.90 |
| DHT Timeout Fallback Test | `origin` | `origin` | 1 | `origin` | 0 | 3453.37 | 671.70 |

## Observations

- Both stacks preserved the expected locality ordering in the smoke test: first origin, then same-building peer service, then cross-building peer service.
- The coordinator-primary stack retained stronger local-cache behavior in the burst and churn workloads, reflected in lower medians and more `cache`-served requests.
- The DHT-primary stack issued more peer-served requests in the burst and churn workloads, but this came with higher median or mean latency in those runs.
- The original coordinator cloud fallback issue is resolved: warm-object peer fallback now works under coordinator crash, partition, and timeout scenarios.
- The DHT crash and partition fallback scenarios also behave correctly: warm objects are served from peers and cold objects degrade to origin.
- The DHT timeout scenario remains the main weak case: the warm object still falls through to origin despite one candidate being known. This should be reported as an observed limitation in the timeout path, not as a test failure.

## Files Used

Coordinator stack:

- [explicit-locality-smoke-test.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/explicit-locality-smoke-test.json)
- [course-burst-workload.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/course-burst-workload.json)
- [burst-with-independent-churn.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/burst-with-independent-churn.json)
- [correlated-class-exit-churn.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/correlated-class-exit-churn.json)
- [coordinator-failure-fallback-smoke-test.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/coordinator-failure-fallback-smoke-test.json)
- [coordinator-partition-fallback-test.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/coordinator-partition-fallback-test.json)
- [coordinator-timeout-fallback-test.json](c:/Dev/ResilientP2P/p2p-coordinator/experiments/results-k8s/coordinator-timeout-fallback-test.json)

DHT stack:

- [explicit-locality-smoke-test.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/explicit-locality-smoke-test.json)
- [course-burst-workload.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/course-burst-workload.json)
- [burst-with-independent-churn.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/burst-with-independent-churn.json)
- [correlated-class-exit-churn.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/correlated-class-exit-churn.json)
- [dht-failure-fallback-smoke-test.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/dht-failure-fallback-smoke-test.json)
- [dht-partition-fallback-test.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/dht-partition-fallback-test.json)
- [dht-timeout-fallback-test.json](c:/Dev/ResilientP2P/p2p-dht/experiments/results-k8s/dht-timeout-fallback-test.json)
