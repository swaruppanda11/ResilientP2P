# ResilientP2P Short DHT-Primary Cloud Demo

**Generated:** 2026-04-21 14:41:58 -06:00

## Demo Goal

This demo shows the DHT-primary architecture running on GKE. It demonstrates origin fetch, DHT-based peer discovery, locality-aware peer reuse, local cache hits, and behavior when the DHT bootstrap service is unavailable.

## Architecture in One Sentence

A DHT-primary peer first checks local cache, then queries the Kademlia DHT for providers, falls back to the coordinator if DHT discovery fails or returns no providers, and finally fetches from origin if no peer can serve the object.

## Demo Setup

- Namespace: p2p-dht
- Demo object: demo-dht-lecture-20260421-144158
- Warm fallback object: demo-dht-fallback-20260421-144158
- Cold object during DHT-bootstrap outage: demo-dht-cold-20260421-144158
- Peers:
  - peer-a1: Building-A
  - peer-a2: Building-A
  - peer-b1: Building-B
- Locality model:
  - same building: 5 ms
  - cross building: 35 ms
  - origin: 120 ms

```powershell
kubectl get pods -n p2p-dht -o wide
```
```text
NAME                             READY   STATUS    RESTARTS   AGE     IP            NODE                                                 NOMINATED NODE   READINESS GATES
coordinator-7f9cd5b579-p9cfj     1/1     Running   0          3h16m   10.24.2.128   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
dht-bootstrap-7b546b8bcd-pmz7t   1/1     Running   0          3h15m   10.24.2.133   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
origin-65674bc7c5-pjhkm          1/1     Running   0          3h16m   10.24.2.129   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-a1-7fbb5b6559-9cf95         1/1     Running   0          3h16m   10.24.2.131   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-a2-7f9887f6b4-7472v         1/1     Running   0          3h16m   10.24.2.132   gke-resilientp2p-gke-building-a-pool-9da3794c-xd6x   <none>           <none>
peer-b1-59b6ff4d89-kswjp         1/1     Running   0          3h16m   10.24.3.127   gke-resilientp2p-gke-building-b-pool-d05e5d9a-4qz5   <none>           <none>
```

## Clean Start

For a repeatable demo, the DHT-primary stack is restarted before requests are issued. This clears peer caches and rebuilds DHT/coordinator state.

```powershell
kubectl scale deployment/coordinator -n p2p-dht --replicas=0
```
```text
deployment.apps/coordinator scaled
```

```powershell
kubectl scale deployment/origin -n p2p-dht --replicas=0
```
```text
deployment.apps/origin scaled
```

```powershell
kubectl scale deployment/dht-bootstrap -n p2p-dht --replicas=0
```
```text
deployment.apps/dht-bootstrap scaled
```

```powershell
kubectl scale deployment/peer-a1 -n p2p-dht --replicas=0
```
```text
deployment.apps/peer-a1 scaled
```

```powershell
kubectl scale deployment/peer-a2 -n p2p-dht --replicas=0
```
```text
deployment.apps/peer-a2 scaled
```

```powershell
kubectl scale deployment/peer-b1 -n p2p-dht --replicas=0
```
```text
deployment.apps/peer-b1 scaled
```

```powershell
kubectl scale deployment/coordinator -n p2p-dht --replicas=1
```
```text
deployment.apps/coordinator scaled
```

```powershell
kubectl scale deployment/origin -n p2p-dht --replicas=1
```
```text
deployment.apps/origin scaled
```

```powershell
kubectl scale deployment/dht-bootstrap -n p2p-dht --replicas=1
```
```text
deployment.apps/dht-bootstrap scaled
```

```powershell
kubectl scale deployment/peer-a1 -n p2p-dht --replicas=1
```
```text
deployment.apps/peer-a1 scaled
```

```powershell
kubectl scale deployment/peer-a2 -n p2p-dht --replicas=1
```
```text
deployment.apps/peer-a2 scaled
```

```powershell
kubectl scale deployment/peer-b1 -n p2p-dht --replicas=1
```
```text
deployment.apps/peer-b1 scaled
```

```powershell
kubectl rollout status deployment/coordinator -n p2p-dht --timeout=90s
```
```text
Waiting for deployment "coordinator" rollout to finish: 0 of 1 updated replicas are available...
deployment "coordinator" successfully rolled out
```

```powershell
kubectl rollout status deployment/origin -n p2p-dht --timeout=90s
```
```text
deployment "origin" successfully rolled out
```

```powershell
kubectl rollout status deployment/dht-bootstrap -n p2p-dht --timeout=90s
```
```text
deployment "dht-bootstrap" successfully rolled out
```

```powershell
kubectl rollout status deployment/peer-a1 -n p2p-dht --timeout=90s
```
```text
Waiting for deployment "peer-a1" rollout to finish: 0 of 1 updated replicas are available...
deployment "peer-a1" successfully rolled out
```

```powershell
kubectl rollout status deployment/peer-a2 -n p2p-dht --timeout=90s
```
```text
deployment "peer-a2" successfully rolled out
```

```powershell
kubectl rollout status deployment/peer-b1 -n p2p-dht --timeout=90s
```
```text
deployment "peer-b1" successfully rolled out
```

## Live Request Walkthrough

### Step 1 - Cold object fetch from origin

**What this demonstrates:** The object is not cached or advertised yet, so peer-a1 fetches it from the origin. After storing it locally, peer-a1 announces it into the DHT and publishes it to the coordinator fallback index.

Request:
```text
peer-a1 / Building-A -> GET http://localhost:9001/trigger-fetch/demo-dht-lecture-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-lecture-20260421-144158",
    "source":  "origin",
    "size":  1048576,
    "latency_ms":  190.71940309368074,
    "candidate_count":  0,
    "provider":  "http://origin.p2p-dht.svc.cluster.local:8001"
}
```
Presenter note:
- Source reported by the system: origin
- Provider: http://origin.p2p-dht.svc.cluster.local:8001
- Candidate count: 0
- Service latency reported by peer: 190.72 ms
- Wall-clock time observed by script: 265.17 ms

### Step 2 - Same-building DHT peer fetch

**What this demonstrates:** peer-a2 asks for the same object. In the DHT-primary path, it queries the DHT first, discovers peer-a1 as a provider, and fetches from a peer instead of the origin.

Request:
```text
peer-a2 / Building-A -> GET http://localhost:9002/trigger-fetch/demo-dht-lecture-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-lecture-20260421-144158",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  75.1314569497481,
    "candidate_count":  1,
    "provider":  "http://peer-a1.p2p-dht.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a1.p2p-dht.svc.cluster.local:7000
- Candidate count: 1
- Service latency reported by peer: 75.13 ms
- Wall-clock time observed by script: 110.71 ms

### Step 3 - Cross-building DHT peer fetch

**What this demonstrates:** peer-b1 is in a different logical building. The DHT still returns campus providers, and the requester selects a peer provider instead of using the origin.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:9003/trigger-fetch/demo-dht-lecture-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-lecture-20260421-144158",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  97.24391007330269,
    "candidate_count":  1,
    "provider":  "http://peer-a1.p2p-dht.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a1.p2p-dht.svc.cluster.local:7000
- Candidate count: 1
- Service latency reported by peer: 97.24 ms
- Wall-clock time observed by script: 118.80 ms

### Step 4 - Local cache hit

**What this demonstrates:** peer-a1 requests the same object again. Because peer-a1 fetched and stored the object in Step 1, this request is served directly from its local cache.

Request:
```text
peer-a1 / Building-A -> GET http://localhost:9001/trigger-fetch/demo-dht-lecture-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-lecture-20260421-144158",
    "source":  "cache",
    "size":  1048576,
    "latency_ms":  0.33095001708716154,
    "candidate_count":  0,
    "provider":  "peer-a1"
}
```
Presenter note:
- Source reported by the system: cache
- Provider: peer-a1
- Candidate count: 0
- Service latency reported by peer: 0.33 ms
- Wall-clock time observed by script: 20.87 ms

## Hybrid Fallback Mini-Test

This step warms a second object on peer-a1, scales down the DHT bootstrap service, and then asks peer-b1 for that warm object. In the DHT-primary design, coordinator fallback is available when DHT discovery fails or returns no providers. Even if the overlay still has enough state to find the provider, this demonstrates that the system remains available while the DHT bootstrap service is unavailable.

### Step 5a - Warm fallback object before DHT-bootstrap outage

**What this demonstrates:** This creates a cached provider for the fallback object. peer-a1 stores the object, announces it into the DHT, and publishes it to the coordinator fallback index.

Request:
```text
peer-a1 / Building-A -> GET http://localhost:9001/trigger-fetch/demo-dht-fallback-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-fallback-20260421-144158",
    "source":  "origin",
    "size":  1048576,
    "latency_ms":  163.41372299939394,
    "candidate_count":  0,
    "provider":  "http://origin.p2p-dht.svc.cluster.local:8001"
}
```
Presenter note:
- Source reported by the system: origin
- Provider: http://origin.p2p-dht.svc.cluster.local:8001
- Candidate count: 0
- Service latency reported by peer: 163.41 ms
- Wall-clock time observed by script: 184.56 ms

```powershell
kubectl scale deployment/dht-bootstrap -n p2p-dht --replicas=0
```
```text
deployment.apps/dht-bootstrap scaled
```

### Step 5b - DHT-bootstrap unavailable, warm object still served by peer

**What this demonstrates:** The DHT bootstrap service is unavailable. The request still succeeds from a peer, showing that DHT-primary does not immediately collapse to origin when a discovery component is disrupted.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:9003/trigger-fetch/demo-dht-fallback-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-fallback-20260421-144158",
    "source":  "peer",
    "size":  1048576,
    "latency_ms":  73.5469099599868,
    "candidate_count":  1,
    "provider":  "http://peer-a1.p2p-dht.svc.cluster.local:7000"
}
```
Presenter note:
- Source reported by the system: peer
- Provider: http://peer-a1.p2p-dht.svc.cluster.local:7000
- Candidate count: 1
- Service latency reported by peer: 73.55 ms
- Wall-clock time observed by script: 153.48 ms

### Step 5c - Cold object during DHT-bootstrap outage

**What this demonstrates:** This object was never warmed. With no peer provider available, the system correctly falls back to the origin.

Request:
```text
peer-b1 / Building-B -> GET http://localhost:9003/trigger-fetch/demo-dht-cold-20260421-144158
```
Response:
```json
{
    "status":  "success",
    "object_id":  "demo-dht-cold-20260421-144158",
    "source":  "origin",
    "size":  1048576,
    "latency_ms":  186.1055699409917,
    "candidate_count":  0,
    "provider":  "http://origin.p2p-dht.svc.cluster.local:8001"
}
```
Presenter note:
- Source reported by the system: origin
- Provider: http://origin.p2p-dht.svc.cluster.local:8001
- Candidate count: 0
- Service latency reported by peer: 186.11 ms
- Wall-clock time observed by script: 209.62 ms

### Optional peer-b1 discovery log excerpt

The API response reports source and provider, but it does not expose whether the selected peer came from DHT or coordinator fallback. This log excerpt is included as supporting evidence for DHT lookup and fallback events.

```powershell
kubectl logs -n p2p-dht deployment/peer-b1 --since=3m | Select-String -Pattern 'demo-dht-fallback-20260421-144158|demo-dht-cold-20260421-144158|DHT_LOOKUP|COORDINATOR_FALLBACK'
```
```text

METRIC: {"timestamp":"2026-04-21T20:42:52.872352","source_peer":"peer-b1","event_type":"DHT_LOOKUP_RESULT","object_id":"demo-d
ht-lecture-20260421-144158","latency_ms":0.5037999944761395,"location_id":"Building-B","bytes_transferred":0,"provider_peer":n
ull,"candidate_count":1,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_object_
count":null}
{"timestamp":"2026-04-21T20:42:52.872517","service":"dht-peer:peer-b1","level":"INFO","event":"dht_lookup_success","details":{
"peer_id":"peer-b1","object_id":"demo-dht-lecture-20260421-144158","provider_count":1}}
METRIC: {"timestamp":"2026-04-21T20:43:01.448143","source_peer":"peer-b1","event_type":"CACHE_MISS","object_id":"demo-dht-fall
back-20260421-144158","latency_ms":0.006119953468441963,"location_id":"Building-B","bytes_transferred":0,"provider_peer":null,
"candidate_count":null,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_object_c
ount":null}
METRIC: {"timestamp":"2026-04-21T20:43:01.448379","source_peer":"peer-b1","event_type":"DHT_LOOKUP_RESULT","object_id":"demo-d
ht-fallback-20260421-144158","latency_ms":0.24896999821066856,"location_id":"Building-B","bytes_transferred":0,"provider_peer"
:null,"candidate_count":1,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_objec
t_count":null}
{"timestamp":"2026-04-21T20:43:01.448492","service":"dht-peer:peer-b1","level":"INFO","event":"dht_lookup_success","details":{
"peer_id":"peer-b1","object_id":"demo-dht-fallback-20260421-144158","provider_count":1}}
METRIC: {"timestamp":"2026-04-21T20:43:01.521696","source_peer":"peer-b1","event_type":"PEER_FETCH","object_id":"demo-dht-fall
back-20260421-144158","latency_ms":73.5469099599868,"location_id":"Building-B","bytes_transferred":1048576,"provider_peer":"ht
tp://peer-a1.p2p-dht.svc.cluster.local:7000","candidate_count":1,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":nu
ll,"cache_size_bytes":null,"cache_object_count":null}
INFO:     127.0.0.1:44924 - "GET /trigger-fetch/demo-dht-fallback-20260421-144158 HTTP/1.1" 200 OK
METRIC: {"timestamp":"2026-04-21T20:43:01.571040","source_peer":"peer-b1","event_type":"CACHE_MISS","object_id":"demo-dht-cold
-20260421-144158","latency_ms":0.0068999361246824265,"location_id":"Building-B","bytes_transferred":0,"provider_peer":null,"ca
ndidate_count":null,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_object_coun
t":null}
METRIC: {"timestamp":"2026-04-21T20:43:01.577642","source_peer":"peer-b1","event_type":"DHT_LOOKUP_RESULT","object_id":"demo-d
ht-cold-20260421-144158","latency_ms":6.603379966691136,"location_id":"Building-B","bytes_transferred":0,"provider_peer":null,
"candidate_count":0,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_object_coun
t":null}
{"timestamp":"2026-04-21T20:43:01.577789","service":"dht-peer:peer-b1","level":"INFO","event":"dht_lookup_success","details":{
"peer_id":"peer-b1","object_id":"demo-dht-cold-20260421-144158","provider_count":0}}
METRIC: {"timestamp":"2026-04-21T20:43:01.583416","source_peer":"peer-b1","event_type":"COORDINATOR_LOOKUP_RESULT","object_id"
:"demo-dht-cold-20260421-144158","latency_ms":12.385979993268847,"location_id":"Building-B","bytes_transferred":0,"provider_pe
er":null,"candidate_count":0,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_ob
ject_count":null}
METRIC: {"timestamp":"2026-04-21T20:43:01.583473","source_peer":"peer-b1","event_type":"COORDINATOR_FALLBACK","object_id":"dem
o-dht-cold-20260421-144158","latency_ms":12.45008991099894,"location_id":"Building-B","bytes_transferred":0,"provider_peer":nu
ll,"candidate_count":null,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":null,"cache_size_bytes":null,"cache_objec
t_count":null}
METRIC: {"timestamp":"2026-04-21T20:43:01.757038","source_peer":"peer-b1","event_type":"CACHE_STORE","object_id":"demo-dht-col
d-20260421-144158","latency_ms":0.0,"location_id":"Building-B","bytes_transferred":1048576,"provider_peer":null,"candidate_cou
nt":null,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":10485760,"cache_size_bytes":1048576,"cache_object_count":1
}
METRIC: {"timestamp":"2026-04-21T20:43:01.757131","source_peer":"peer-b1","event_type":"ORIGIN_FETCH","object_id":"demo-dht-co
ld-20260421-144158","latency_ms":186.1055699409917,"location_id":"Building-B","bytes_transferred":1048576,"provider_peer":"htt
p://origin.p2p-dht.svc.cluster.local:8001","candidate_count":null,"evicted_bytes":0,"evicted_count":0,"cache_capacity_bytes":n
ull,"cache_size_bytes":null,"cache_object_count":null}
INFO:     127.0.0.1:44924 - "GET /trigger-fetch/demo-dht-cold-20260421-144158 HTTP/1.1" 200 OK
```

```powershell
kubectl scale deployment/dht-bootstrap -n p2p-dht --replicas=1
```
```text
deployment.apps/dht-bootstrap scaled
```

```powershell
kubectl rollout status deployment/dht-bootstrap -n p2p-dht --timeout=90s
```
```text
Waiting for deployment "dht-bootstrap" rollout to finish: 0 of 1 updated replicas are available...
deployment "dht-bootstrap" successfully rolled out
```

## Result Summary

| Step | Expected behavior | Actual source | Provider | Service latency |
|---|---|---:|---|---:|
| 1 | Cold miss goes to origin | origin | http://origin.p2p-dht.svc.cluster.local:8001 | 190.72 ms |
| 2 | Same-building DHT reuse avoids origin | peer | http://peer-a1.p2p-dht.svc.cluster.local:7000 | 75.13 ms |
| 3 | Cross-building DHT reuse avoids origin | peer | http://peer-a1.p2p-dht.svc.cluster.local:7000 | 97.24 ms |
| 4 | Origin provider repeats request and hits local cache | cache | peer-a1 | 0.33 ms |
| 5b | DHT-bootstrap down, warm object served | peer | http://peer-a1.p2p-dht.svc.cluster.local:7000 | 73.55 ms |
| 5c | Cold object falls back to origin | origin | http://origin.p2p-dht.svc.cluster.local:8001 | 186.11 ms |

## Optional Coordinator Snapshot

The coordinator is the fallback index in this DHT-primary stack. It is not the primary lookup path, but it receives registrations, heartbeats, and publications so it can be used if DHT discovery fails.
```json
{
    "status":  "ok",
    "service":  "coordinator",
    "peer_count":  3,
    "object_count":  3,
    "provider_entries":  3,
    "max_providers_per_lookup":  3,
    "peer_timeout_seconds":  30,
    "provider_selection_policy":  "locality_then_load",
    "total_upload_requests":  3,
    "total_upload_bytes":  3145728,
    "peer_loads":  [
                       {
                           "peer_id":  "peer-a1",
                           "total_upload_requests":  3,
                           "total_upload_bytes":  3145728,
                           "last_transfer_at":  "2026-04-21T20:43:01.509154"
                       },
                       {
                           "peer_id":  "peer-a2",
                           "total_upload_requests":  0,
                           "total_upload_bytes":  0,
                           "last_transfer_at":  null
                       },
                       {
                           "peer_id":  "peer-b1",
                           "total_upload_requests":  0,
                           "total_upload_bytes":  0,
                           "last_transfer_at":  null
                       }
                   ]
}
```

## What To Say During The Demo

1. The first request is cold, so it goes to origin and creates the first cached provider.
2. The second request is the same object from another Building-A peer, and DHT-primary discovery lets it fetch from peer-a1.
3. The third request shows that another building can also avoid the origin by using a campus peer.
4. The fourth request repeats on peer-a1 and shows a local cache hit, which is the fastest path.
5. The final steps disable the DHT bootstrap service. A warm object still comes from a peer, while a never-warmed object correctly falls back to origin.

## Expected Interpretation

- source=origin means external bandwidth was consumed.
- source=peer means the object was served by another campus peer.
- source=cache means the object was served locally without network transfer.
- A warm-object peer response while dht-bootstrap is down demonstrates availability under DHT control-plane disruption.
- A cold-object origin response during the outage is expected because no peer had that object cached.
