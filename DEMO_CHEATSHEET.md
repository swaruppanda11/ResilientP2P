# Demo Cheatsheet — 8-Minute Presentation

**Goal:** show the hybrid caching flow live in under 90 seconds, with zero chance of the stack reset eating your talk.

**Strategy:** skip `runner.py` entirely. Use pre-opened `kubectl port-forward` tunnels and fire 3 `curl` commands by hand. You control the pacing; no pod restarts on stage.

---

## 1. Before the talk (hidden setup)

Make sure kubeconfig points at the right cluster:

```bash
gcloud container clusters get-credentials resilientp2p-gke \
  --zone us-central1-f --project resilientp2p-492916
```

Open 3 port-forwards and leave them running the whole talk (service port is **7000**):

```bash
kubectl -n p2p-coordinator port-forward svc/peer-a1 7001:7000 &
kubectl -n p2p-coordinator port-forward svc/peer-a2 7002:7000 &
kubectl -n p2p-coordinator port-forward svc/peer-b1 7003:7000 &
```

Verify they're live:

```bash
curl -s http://localhost:7001/health | jq .
curl -s http://localhost:7002/health | jq .
curl -s http://localhost:7003/health | jq .
```

All three should return `{"status":"ok","service":"peer:peer-XX"}`. If any one fails, restart its port-forward.

---

## 2. Live on stage (~20 seconds)

Paste this into a terminal that is visible to the audience:

```bash
OBJ="demo-$(date +%s)"

echo "--- Call 1: peer-a1 (cold — no peer has it) ---"
curl -s "http://localhost:7001/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 2: peer-a2 (same building — LAN hop) ---"
curl -s "http://localhost:7002/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 3: peer-b1 (different building — cross-node) ---"
curl -s "http://localhost:7003/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 4: peer-a1 again (local cache hit) ---"
curl -s "http://localhost:7001/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'
```

---

## 3. What the audience sees (and what you say)

| Call | `source` | Expected `latency_ms` | Talk track |
|---|---|---:|---|
| 1 | `"origin"` | ~140 | "Cold start — no peer has it yet. Hits the simulated WAN origin." |
| 2 | `"peer"` | ~40 | "peer-a2 is in the same building. Coordinator returned peer-a1 — LAN transfer." |
| 3 | `"peer"` | ~100 | "peer-b1 is in the other building. Still peer-served — just a cross-node hop." |
| 4 | `"cache"` | <5 | "Same peer again. Local cache hit — the whole three-tier story." |

**The money line:** "First request pays the WAN cost. Everyone after gets it from a peer."

---

## 4. Optional: DHT-primary variant (reference only — don't run live)

The DHT stack mirrors the coordinator stack — same peer names, same ports, different namespace. Use local ports **7101–7103** so the port-forwards don't clash with the coordinator ones.

```bash
kubectl -n p2p-dht port-forward svc/peer-a1 7101:7000 &
kubectl -n p2p-dht port-forward svc/peer-a2 7102:7000 &
kubectl -n p2p-dht port-forward svc/peer-b1 7103:7000 &
```

```bash
OBJ="demo-dht-$(date +%s)"

echo "--- Call 1: peer-a1 (cold — DHT empty, falls to origin) ---"
curl -s "http://localhost:7101/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 2: peer-a2 (DHT has peer-a1 as provider) ---"
curl -s "http://localhost:7102/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 3: peer-b1 (DHT returns multiple providers) ---"
curl -s "http://localhost:7103/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'

echo "--- Call 4: peer-a1 again (local cache hit) ---"
curl -s "http://localhost:7101/trigger-fetch/$OBJ" | jq '{source, latency_ms, provider}'
```

**What's different from the coordinator demo:** same three-tier fetch, same latency profile. Only the lookup path inverts.

| | Coordinator-primary | DHT-primary |
|---|---|---|
| Provider lookup | coordinator REST | Kademlia DHT `get` |
| Fallback | DHT | coordinator |
| Peer ranking | locality + load | DHT return order |

**Talking point (if asked):**
> "Same three-tier fetch, same latency profile. What changes is who answers the 'who has this?' question — a central coordinator, or a distributed hash table. Coordinator wins on smarter peer selection; DHT wins on having no single point of failure. That tradeoff is what our results table quantifies."

**Why not show both live?** 8 minutes is tight. Running both stacks eats 60+ seconds of stage time for a story the audience already understood after call 4 of the coordinator demo. Mention the DHT exists, point at the comparison numbers on your results slide, move on.

---

## 5. De-risking

- **Dry-run the whole sequence 3 times back-to-back** right before you go on. Demo code ages in minutes.
- Use a **fresh `$OBJ`** each rehearsal — cache is persistent across runs, so reusing object IDs fakes a cold start that isn't real.
- Keep the output tiny (`jq '{source, latency_ms, provider}'`) — raw responses are noisy on a projector.
- **Fallback slide**: pre-screenshot the expected output. If anything breaks, flip to the slide, say *"here's what it would've shown,"* and move on. No one will know.
- Don't touch the DHT-primary stack during the demo. One architecture is plenty of live material for 90 seconds.

---

## 6. If a port-forward dies mid-talk

Don't try to fix it. Skip to the fallback slide. Fixing port-forwards on stage is a trap.

If you want to pre-empt: run each `kubectl port-forward` inside a loop in its own terminal so it auto-restarts:

```bash
while true; do kubectl -n p2p-coordinator port-forward svc/peer-a1 7001:7000; sleep 1; done
```

---

## 7. After the talk (cleanup)

```bash
pkill -f "kubectl.*port-forward"
```
