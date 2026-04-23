# How the System Works: End-to-End Test Flow

This document explains what actually happens when you run the test suite — where the "cached" data comes from, how it reaches peers, and what the metrics capture.

## 1. What "cache" means here

**There is no real external website.** The "content" is **synthetic 1MB objects** generated deterministically on demand by the `origin` pod. From [p2p-coordinator/origin/main.py](p2p-coordinator/origin/main.py):

```python
def generate_content(object_id: str, size: int = 1024):
    base = object_id.encode()
    content = base * (size // len(base)) + base[:size % len(base)]
    checksum = hashlib.sha256(content).hexdigest()
```

So `object_id="lecture-1-video"` always produces the exact same 1MB of bytes (the string `"lecture-1-video"` repeated to fill 1MB). The `origin` pod simulates a slow WAN server — it `asyncio.sleep`s for ~120ms before returning. That's the "external source" we're supposedly avoiding.

## 2. The test driver ([experiments/runner.py](p2p-coordinator/experiments/runner.py))

[scripts/run-k8s-suite.sh](scripts/run-k8s-suite.sh) runs `python runner.py workload-k8s.json` N times for each stack. The runner:

1. `kubectl port-forward` to every peer, the coordinator, and origin (so the Python driver can hit them over `localhost`)
2. For each scenario, fires fetch requests at peers:
   ```json
   {"action": "fetch", "peer": "peer-a1", "object_id": "lecture-1-video"}
   ```
   → translates to `POST http://localhost:7001/trigger-fetch` on peer-a1
3. Parses the `METRIC: {...}` JSON lines that peers print to stdout, then writes a results JSON file per scenario

Scenarios come from [workload-k8s.json](p2p-coordinator/experiments/workload-k8s.json) — 7 total (smoke, course burst, independent churn, correlated churn, plus 3 failure-injection tests).

## 3. A single fetch — the actual flow

Take `peer-a1 fetch lecture-1-video`. The peer runs [peer/client.py](p2p-coordinator/peer/client.py) and tries four sources in order (Config B = coordinator-primary):

```
┌─────────────┐
│ 1. Local    │  cache.get(object_id)
│    cache    │  → if present: source="cache", latency ~0ms
└──────┬──────┘
       │ miss
       ▼
┌─────────────┐
│ 2. Coord-   │  GET coordinator/lookup/{id}?location_id=Building-A
│    inator   │  returns up to 3 peer URLs, sorted by locality + load
│    lookup   │
└──────┬──────┘
       │ got provider URLs
       ▼
┌─────────────┐
│ 3. DHT      │  (only if coordinator failed / returned 0 providers)
│    fallback │  asks the DHT overlay "who has this key?"
└──────┬──────┘
       │ tries each candidate peer
       ▼
┌─────────────┐
│ 4. Peer     │  GET peer-a2:7002/get-object/{id}
│    fetch    │  peer-a2 reads its own cache, sends bytes back
│             │  → source="peer", latency 0.5–70ms
└──────┬──────┘
       │ all peers failed
       ▼
┌─────────────┐
│ 5. Origin   │  GET origin:8000/object/{id}?delay=0.12
│    (WAN)    │  → source="origin", latency ~200ms (the penalty we pay for a miss)
└─────────────┘
```

On **any** successful fetch (peer or origin), the requesting peer stores the bytes in its own LRU cache ([peer/cache.py](p2p-coordinator/peer/cache.py) with SHA-256 verification), then announces ownership to **both** the coordinator and the DHT. That's how content spreads through the overlay.

The DHT-primary stack ([p2p-dht/peer/client.py](p2p-dht/peer/client.py)) uses the same order but swaps steps 2 and 3: DHT first, coordinator as fallback.

## 4. Example: the 3-step "Explicit Locality Smoke Test"

| Step | Peer | Request | What happens | Source | Latency |
|---|---|---|---|---|---|
| 1 | peer-a1 | fetch `lecture-1-video` | Cache miss → coordinator has 0 providers → DHT has 0 → falls to origin, caches bytes, announces | `origin` | ~140ms (WAN delay) |
| 2 | peer-a2 | fetch `lecture-1-video` | Cache miss → coordinator returns `[peer-a1]` (same building "A", closest) → HTTP fetch from peer-a1 → caches, announces | `peer` | ~40ms |
| 3 | peer-b1 | fetch `lecture-1-video` | Cache miss → coordinator returns `[peer-a1, peer-a2]` → fetches from one, caches, announces | `peer` | ~100ms (cross-node) |

After these 3 steps, all 3 peers have the object cached. Subsequent fetches hit local cache (`source="cache"`, sub-ms).

**Bandwidth "reduction":** 3 requests × 1MB = 3MB would have hit origin if no caching. With caching, only 1MB hit origin. → **66.7% reduction.** That's the number in the smoke test row of [results-aggregate/aggregate-summary.md](results-aggregate/aggregate-summary.md).

## 5. Where peer-to-peer traffic actually flows

Inside the cluster, a peer fetching from another peer is just HTTP over the pod network:

```
peer-a2 pod (10.24.2.84, building-a node)
   │ GET http://peer-a1.p2p-coordinator.svc.cluster.local:8080/get-object/lecture-1-video
   ▼
kube-dns → service/peer-a1 → peer-a1 pod (10.24.2.83, same node)
```

Same-node = ~1ms; cross-node (to peer-b1 on the other VM) = ~30ms. That's the "locality" dimension the experiment is measuring.

The `kubectl port-forward` the runner sets up is only so the Python driver on your laptop can send the initial `trigger-fetch` request — **peer-to-peer bytes transfer happens inside the cluster**, not through your laptop.

## 6. TL;DR

- **Source of data**: the `origin` pod synthesizes 1MB objects deterministically from the `object_id` (simulated external content, not real web pages)
- **What gets cached**: peers write fetched bytes into their in-process LRU cache
- **How peers find each other**: coordinator lookup (primary) → DHT (fallback) — both indices learn who has what when a peer announces after caching
- **How bytes move between peers**: plain HTTP inside the cluster pod network, pod-to-pod
- **What the runner measures**: per-request `METRIC:` lines emitted to stdout (source, latency, candidates) → aggregated into the JSON/MD tables under [results-aggregate/](results-aggregate/)
