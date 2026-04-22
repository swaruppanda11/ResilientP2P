# ResilientP2P Short Cloud Demo

**Generated:** 2026-04-21 14:40:45 -06:00

## Demo Goal

This demo shows the coordinator-primary architecture running on GKE. In under two minutes, it demonstrates origin fetch, peer-assisted cache reuse, locality-aware peer transfer, local cache hits, and hybrid fallback when the coordinator is unavailable.

## Architecture in One Sentence

A peer first checks its local cache, then uses the coordinator to discover nearby providers, falls back to the DHT if the coordinator is unavailable, and finally fetches from the origin if no peer can serve the object.

## Demo Setup

- Namespace: p2p-coordinator
- Demo object: demo-lecture-20260421-144045
- Fallback object: demo-fallback-20260421-144045
- Peers:
  - peer-a1: Building-A
  - peer-a2: Building-A
  - peer-b1: Building-B
- Locality model:
  - same building: 5 ms
  - cross building: 35 ms
  - origin: 120 ms

```powershell
kubectl get pods -n p2p-coordinator -o wide
```
```text
NAME                             READY   STATUS    RESTARTS   AGE     IP            NODE                                                 NOMINATED NODE   READINESS GATES
coordinator-7f9cd5b579-44l57     1/1     Running   0          4h48m   10.24.2.125   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
dht-bootstrap-7b546b8bcd-qxnsj   1/1     Running   0          7d23h   10.24.2.82    gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
origin-65674bc7c5-k2hmw          1/1     Running   0          7d23h   10.24.2.81    gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-a1-6559d885c8-rfxmv         1/1     Running   0          7d23h   10.24.2.83    gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-a2-69c675799c-bp7fn         1/1     Running   0          7d23h   10.24.2.84    gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-b1-854cb4dc68-fpblh         1/1     Running   0          7d23h   10.24.3.118   gke-resilientp2p-gke-building-b-pool-d05e5d9a-4qz5   <none>           <none>
```

## Live Request Walkthrough

### Step 1 - Cold object fetch from origin

**What this demonstrates:** The object is not cached anywhere yet, so peer-a1 must fetch it from the origin. After this request, peer-a1 stores it locally and publishes metadata to the coordinator and DHT.

Request:
```text
peer-a1 / Building-A -> GET http://localhost:7001/trigger-fetch/demo-lecture-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-lecture-20260421-144045",
    "source":  "origin",
    "size":  1048576,
    "latency_ms":  238.39107097592205,
    "candidate_count":  0,
    "provider":  "http://origin.p2p-coordinator.svc.cluster.local:8001"
}
```
Presenter note:
- Source reported by the system: origin
- Provider: http://origin.p2p-coordinator.svc.cluster.local:8001
- Candidate count: 0
- Service latency reported by peer: 238.39 ms
- Wall-clock time observed by script: 311.64 ms

### Step 2 - Same-building peer fetch

**What this demonstrates:** peer-a2 asks for the same object. The coordinator discovers peer-a1 as a provider in the same building, so the object is served by a peer instead of the origin.

Request:
```text
peer-a2 / Building-A -> GET http://localhost:7002/trigger-fetch/demo-lecture-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-lecture-20260421-144045",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  75.46707801520824,
    "candidate_count":  1,
    "provider":  "http://peer-a1.p2p-coordinator.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a1.p2p-coordinator.svc.cluster.local:7000
- Candidate count: 1
- Service latency reported by peer: 75.47 ms
- Wall-clock time observed by script: 120.32 ms

### Step 3 - Cross-building peer fetch

**What this demonstrates:** peer-b1 is in a different logical building. The system still avoids the origin by fetching from a peer, but the topology model applies cross-building delay.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:7003/trigger-fetch/demo-lecture-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-lecture-20260421-144045",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  96.36069997213781,
    "candidate_count":  2,
    "provider":  "http://peer-a2.p2p-coordinator.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a2.p2p-coordinator.svc.cluster.local:7000
- Candidate count: 2
- Service latency reported by peer: 96.36 ms
- Wall-clock time observed by script: 165.06 ms

### Step 4 - Local cache hit

**What this demonstrates:** peer-b1 requests the same object again. This time it serves the object directly from its own local cache, which is the fastest path.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:7003/trigger-fetch/demo-lecture-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-lecture-20260421-144045",
    "source":  "cache",
    "size":  1048576,
    "latency_ms":  0.4974100738763809,
    "candidate_count":  0,
    "provider":  "peer-b1"
}
```
Presenter note:
- Source reported by the system: cache
- Provider: peer-b1
- Candidate count: 0
- Service latency reported by peer: 0.50 ms
- Wall-clock time observed by script: 20.84 ms

## Hybrid Fallback Mini-Test

This final step warms a second object on peer-a1, intentionally scales the coordinator down, and then asks peer-b1 for that warm object. A successful peer response while the coordinator is unavailable demonstrates DHT fallback.

### Step 5a - Warm fallback object before coordinator failure

**What this demonstrates:** This creates a cached provider for the fallback object and gives the DHT time to learn the provider.

Request:
```text
peer-a1 / Building-A -> GET http://localhost:7001/trigger-fetch/demo-fallback-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-fallback-20260421-144045",
    "source":  "origin",
    "size":  1048576,
    "latency_ms":  165.76250398065895,
    "candidate_count":  0,
    "provider":  "http://origin.p2p-coordinator.svc.cluster.local:8001"
}
```
Presenter note:
- Source reported by the system: origin
- Provider: http://origin.p2p-coordinator.svc.cluster.local:8001
- Candidate count: 0
- Service latency reported by peer: 165.76 ms
- Wall-clock time observed by script: 186.37 ms

```powershell
kubectl scale deployment/coordinator -n p2p-coordinator --replicas=0
```
```text
deployment.apps/coordinator scaled
```

### Step 5b - Coordinator unavailable, DHT fallback serves warm object

**What this demonstrates:** The coordinator is down, so the normal coordinator lookup fails. The peer falls back to the DHT, finds the warm object provider, and fetches from another peer instead of the origin.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:7003/trigger-fetch/demo-fallback-20260421-144045
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-fallback-20260421-144045",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  2104.4984420295805,
    "candidate_count":  1,
    "provider":  "http://peer-a1.p2p-coordinator.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a1.p2p-coordinator.svc.cluster.local:7000
- Candidate count: 1
- Service latency reported by peer: 2,104.50 ms
- Wall-clock time observed by script: 2,226.87 ms

```powershell
kubectl scale deployment/coordinator -n p2p-coordinator --replicas=1
```
```text
deployment.apps/coordinator scaled
```

```powershell
kubectl rollout status deployment/coordinator -n p2p-coordinator --timeout=90s
```
```text
Waiting for deployment "coordinator" rollout to finish: 0 of 1 updated replicas are available...
deployment "coordinator" successfully rolled out
```

## Result Summary

| Step | Expected behavior | Actual source | Provider | Service latency |
|---|---|---:|---|---:|
| 1 | Cold miss goes to origin | origin | http://origin.p2p-coordinator.svc.cluster.local:8001 | 238.39 ms |
| 2 | Same-building reuse avoids origin | peer | http://peer-a1.p2p-coordinator.svc.cluster.local:7000 | 75.47 ms |
| 3 | Cross-building reuse avoids origin | peer | http://peer-a2.p2p-coordinator.svc.cluster.local:7000 | 96.36 ms |
| 4 | Repeated request hits local cache | cache | peer-b1 | 0.50 ms |
| 5 | Coordinator down, DHT fallback finds peer | peer | http://peer-a1.p2p-coordinator.svc.cluster.local:7000 | 2,104.50 ms |

## Optional Coordinator Snapshot After Restart

This snapshot is optional for the live demo. Because the coordinator was intentionally restarted, its in-memory state may still be rebuilding as peers heartbeat and republish cached objects.
```json
{
    "status":  "ok",
    "service":  "coordinator",
    "peer_count":  0,
    "object_count":  0,
    "provider_entries":  0,
    "max_providers_per_lookup":  3,
    "peer_timeout_seconds":  30,
    "provider_selection_policy":  "locality_then_load",
    "total_upload_requests":  0,
    "total_upload_bytes":  0,
    "peer_loads":  [

                   ]
}
```

## What To Say During The Demo

1. The first request is intentionally cold, so it goes to the origin.
2. The second request is the same object from another peer in the same building, so it is served by peer-to-peer transfer.
3. The third request comes from a different building and still avoids the origin, demonstrating campus-wide peer reuse.
4. The fourth request is served from local cache, showing why repeated campus accesses become very cheap.
5. Finally, the coordinator is turned off and a warm object is still served from a peer through DHT fallback, showing the hybrid design.

## Expected Interpretation

- source=origin means external bandwidth was consumed.
- source=peer means the object was served by another campus peer.
- source=cache means the object was served locally without network transfer.
- A peer response during coordinator downtime demonstrates hybrid fallback behavior.
