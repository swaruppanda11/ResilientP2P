# Resilience: Hybrid P2P Web Caching for Campus Networks
## Product Requirements Document

**Project Name:** Resilience
**Version:** 1.2
**Date:** March 2025
**Authors:** Tanish Praveen Nagrani, Swarup Panda
**Duration:** 6 weeks (Sprint-based delivery)
**Target:** University of Colorado Boulder Campus Network

---

## 1. Executive Summary

Resilience is a hybrid peer-to-peer web caching system optimized for campus networks. It combines two complementary architectures—DHT-based decentralized caching and coordinator-based centralized caching—with intelligent fall-back mechanisms to maximize reliability, reduce external bandwidth consumption by 60–75%, and maintain low content access latency.

Unlike prior work (Maygh, Squirrel, Coral), Resilience explicitly studies how two architectural approaches can be combined for fault tolerance, and systematically evaluates which configuration (DHT-primary + Coordinator-fallback vs. Coordinator-primary + DHT-fallback) better balances performance, resilience, and operational complexity in campus environments.

---

## 2. Problem Statement

### Current State
Campus networks experience significant redundant bandwidth consumption when multiple students simultaneously access identical content (lecture videos, course materials, popular websites). Each request independently traverses the campus gateway to external servers or CDNs, resulting in:
- **Wasted bandwidth**: 50GB inbound for a 500-student lecture downloading a 100MB file
- **Increased latency**: External WAN links slower than on-campus Gigabit LAN
- **High costs**: Both institutional bandwidth and CDN charges
- **No resilience**: Single points of failure in traditional proxy caches or reliance on external CDNs

### Key Campus Network Characteristics
- **High content overlap**: Students in same courses access similar materials
- **Fast local connectivity**: Gigabit+ LAN speeds vs. congested external links
- **Temporal locality**: Content accessed in bursts (assignment deadlines, exam prep)
- **Trust domain**: Users share institutional identity, enabling peer-assisted distribution
- **High churn**: Sessions typically 10–30 minutes (class duration)

### Existing Solution Gaps
| Solution | Limitation |
|----------|-----------|
| Proxy caches (Squid) | Single point of failure, limited scalability |
| Commercial CDNs | Still consume external bandwidth, ongoing costs |
| Generic P2P (BitTorrent) | Not designed for web content, requires separate client |
| Maygh (browser P2P) | No locality awareness, coordinator-only design |
| Squirrel (DHT-based) | No locality awareness, outdated evaluation |

### The Core Research Gap
**How do DHT-primary and Coordinator-primary hybrid architectures compare in trading off decentralization, simplicity, and resilience for campus P2P caching?**

---

## 3. Goals and Objectives

### Primary Goal
Design, implement, and evaluate a hybrid peer-to-peer web caching system that intelligently switches between two architectures (DHT and Coordinator) to maximize resilience, minimize latency, and reduce external bandwidth in campus networks.

### Specific Objectives

**Goal 1: Demonstrate Hybrid Fall-back Effectiveness**
- Implement both DHT-primary + Coordinator-fallback and Coordinator-primary + DHT-fallback configurations
- Measure: How often does each configuration trigger fallback?
- Measure: What is the latency cost of switching to fallback mode?
- Target: Fallback latency <200ms, fallback triggered <5% of the time during normal operation

**Goal 2: Minimize External Bandwidth Consumption**
- Evaluate cache hit rates and bandwidth reduction vs. direct origin access
- Target: Achieve 60–75% external bandwidth reduction
- Compare hit rates between primary and fallback modes

**Goal 3: Maintain Low Access Latency**
- Measure median and 95th percentile latency for:
  - Primary mode operation
  - Fallback mode operation
  - Hybrid switching overhead
- Target: Primary mode latency ≤ direct origin access; fallback mode degradation <50ms

**Goal 4: Characterize Churn Resilience**
- Test both configurations under realistic campus churn (10–30 min sessions)
- Measure: How does fallback frequency change with churn rate?
- Measure: Cache hit rate sensitivity to correlated vs. random peer departures
- Target: Cache hit rate remains >60% under 20% per-minute churn

**Goal 5: Compare Operational Complexity**
- Quantify operational requirements for each hybrid configuration:
  - DHT-primary: Infrastructure needs, overlay maintenance overhead
  - Coordinator-primary: Single point of failure, resource requirements
- Document which configuration is easier to deploy/maintain in campus environment

---

## 4. Product Vision

### What Resilience Does
Resilience is a peer-to-peer web caching overlay for campus networks that:

1. **Distributes Content via Peers** — When a student requests content (video, assignment, webpage), the system first attempts to fetch from nearby peers rather than external servers
2. **Provides Intelligent Fall-back** — If the primary architecture (DHT or Coordinator) fails or degrades, automatically switches to the secondary architecture without user intervention
3. **Optimizes for Campus Geography** — Prefers geographically nearby peers to minimize latency and maximize LAN utilization
4. **Maintains Performance Under Churn** — Continues caching effectively even when peers frequently join/leave
5. **Reduces Operational Burden** — Hybrid design provides redundancy without requiring dual infrastructure

### Who Uses It
- **CU Boulder IT department**: Deploys system to reduce campus bandwidth costs
- **Students**: Transparent caching — no behavior change required, just faster downloads
- **Content providers**: Reduced server load from cached hits
- **Network researchers**: Platform for studying P2P systems in campus contexts

### What Success Looks Like
- System remains available even when primary architecture fails
- External bandwidth consumption drops 60–75%
- Peer access latency ≤ direct access latency
- Runs on commodity hardware; minimal operational overhead
- Can be deployed university-wide without requiring browser plugins or client software modifications

---

## 5. Scope: Two Hybrid Configurations

### Configuration A: DHT-Primary + Coordinator-Fallback
**Primary Path (DHT):**
- Fully decentralized peer discovery using Kademlia DHT
- Peers register their cached content in the overlay
- Content lookup uses DHT routing (likely longer lookups but no single point of failure)

**Fallback Path (Coordinator):**
- If DHT lookups timeout (>500ms) or fail, switch to coordinator
- Coordinator tracks all online peers and their cache contents
- Coordinator returns list of peers with requested content, sorted by locality
- Peers fetch from coordinator recommendations

**Strengths:** Decentralization, no single point of failure, DHT self-heals
**Weaknesses:** Complexity of DHT overlay maintenance, potentially higher lookup latency

---

### Configuration B: Coordinator-Primary + DHT-Fallback
**Primary Path (Coordinator):**
- Central coordinator service tracks all online peers and cached content
- Fast lookup: Coordinator maintains in-memory index, O(1) response times
- Coordinator returns list of nearby peers with requested content
- Peers fetch from coordinator recommendations

**Fallback Path (DHT):**
- If coordinator is unavailable/unresponsive, peers switch to DHT-based discovery
- DHT acts as backup index, requires no central service
- Higher latency but ensures availability

**Strengths:** Simplicity, fast lookups, coordinator can be lightweight
**Weaknesses:** Coordinator is a bottleneck/SPOF without redundancy

---

### Evaluation Approach
Both configurations will be evaluated on:
1. **Fallback Frequency** — How often does each trigger its backup mechanism?
2. **Fallback Latency** — What is the cost of switching modes?
3. **Cache Hit Rates** — In primary mode vs. fallback mode
4. **Churn Resilience** — Which handles peer departures better?
5. **Operational Complexity** — Which is easier to deploy and maintain?

---

## 6. Key Features

### Core Features (MVP)

#### 6.1 Peer Discovery & Registration
- **DHT-based**: Peers join Kademlia overlay on startup; announce cached content via DHT `set` operations using a read-modify-write pattern to accumulate provider lists per object
- **Coordinator-based**: Peers register with central coordinator on startup; send periodic heartbeats (default 10s); coordinator prunes dead peers after timeout (default 30s)
- **Hybrid**: Both mechanisms active simultaneously; each peer maintains a DHT node and a coordinator HTTP client

#### 6.2 Content Lookup & Routing
- **DHT lookup**: XOR-based Kademlia routing; provider list stored as JSON at `hash(object_id)`; caller applies per-request timeout (default 500ms)
- **Coordinator lookup**: HTTP GET `/lookup/{object_id}?location_id=...`; coordinator returns up to K providers sorted by locality then load
- **Locality awareness**: Both modes prefer same `location_id` (building) peers first
  - DHT: client-side sort of returned provider list by `location_id` match
  - Coordinator: server-side sort by `location_id` match then upload request count

#### 6.3 Fall-back Mechanism
- **Fallback triggers** (per-request, not periodic):
  - DHT timeout: `asyncio.wait_for` with 500ms budget; triggers coordinator fallback
  - DHT error: any exception during lookup; triggers coordinator fallback
  - Coordinator unreachable / returns 0 providers: triggers DHT fallback
- **No automatic recovery switching**: fallback is per-request, not a mode switch; each request independently tries primary first
- **Both systems updated on store**: every peer that caches an object announces to both DHT and coordinator, keeping both indices warm for fallback

#### 6.4 Cache Management
- **Storage**: In-process `OrderedDict` (LRU); persists for the lifetime of the container
- **Eviction**: LRU when byte capacity exceeded (default 10MB per peer in Docker; configurable via `CACHE_CAPACITY_BYTES`)
- **Content validation**: SHA-256 checksum verified on every `put`; mismatches raise an error
- **Cache consistency**: Best-effort (content is immutable per `object_id` by design)

#### 6.5 Peer Selection & Load Balancing
- **Geographic proximity**: Peers sorted by `location_id` match (same building = lower latency tier)
- **Load balancing (coordinator)**: Ties broken by `total_upload_requests` ascending (least-loaded first); configurable via `PROVIDER_SELECTION_POLICY` env var (`locality_then_load` or `locality_only`)
- **Load balancing (DHT)**: Client-side only; sorted by locality, secondary sort by `peer_id` (deterministic tie-break); no upload tracking in DHT path
- **Max candidates**: Both paths return at most `MAX_PROVIDERS_PER_LOOKUP` peers (default 3)

#### 6.6 Churn Handling
- **Coordinator**: Heartbeat timeout evicts dead peers and prunes their index entries; re-registration on 404 responses
- **DHT**: Kademlia overlay self-heals via periodic stabilization; peers republish all cached content to DHT every `DHT_REPUBLISH_INTERVAL_SECONDS` (default 300s) to recover from node churn erasing stored values
- **Graceful departure**: On shutdown, peer removes itself from DHT provider lists for all cached objects; no coordinator deregistration endpoint (coordinator detects departure via heartbeat timeout)

#### 6.7 Metrics & Observability
- **Per-request metric events** printed to stdout as `METRIC: {JSON}` lines (parseable by experiment runner)
- **Event types**: `CACHE_HIT`, `CACHE_MISS`, `CACHE_STORE`, `CACHE_REJECTED`, `PEER_FETCH`, `ORIGIN_FETCH`, `LOOKUP_RESULT` (coordinator), `DHT_LOOKUP_RESULT`, `DHT_LOOKUP_TIMEOUT`, `DHT_LOOKUP_FAILURE`, `COORDINATOR_FALLBACK`, `COORDINATOR_LOOKUP_RESULT`
- **Per-peer HTTP stats**: `GET /stats` returns cache hit/miss/eviction counts, cache byte utilization
- **Coordinator stats**: `GET /stats` returns peer count, object count, provider entries, per-peer upload totals
- **Experiment results**: JSON files written to `experiments/results/` per scenario

---

## 7. Technical Architecture

### 7.1 System Components

```
                    ┌─────────────────────────────────┐
                    │         Campus Peer Node         │
                    │                                  │
                    │  ┌──────────┐  ┌──────────────┐ │
                    │  │  Cache   │  │   Content    │ │
                    │  │ Manager  │  │   Transfer   │ │
                    │  │  (LRU)   │  │ (HTTP/REST)  │ │
                    │  └──────────┘  └──────────────┘ │
                    │  ┌──────────┐  ┌──────────────┐ │
                    │  │   DHT    │  │ Coordinator  │ │
                    │  │  Client  │  │   Client     │ │
                    │  │(Kademlia)│  │  (fallback)  │ │
                    │  └────┬─────┘  └──────┬───────┘ │
                    └───────┼───────────────┼─────────┘
                            │               │
               ┌────────────┘               └────────────┐
               ▼                                         ▼
   ┌───────────────────────┐             ┌───────────────────────┐
   │   Kademlia DHT        │             │  Coordinator Service  │
   │   Overlay Network     │             │  (FastAPI, in-memory  │
   │   (UDP, ksize=5)      │             │   index, O(1) lookup) │
   └───────────────────────┘             └───────────────────────┘
               │
   ┌───────────┴───────────┐
   │   DHT Bootstrap Node  │
   │   (well-known entry   │
   │    point for overlay) │
   └───────────────────────┘
```

**Config A (DHT-primary):** DHT Client is primary → Coordinator Client is fallback
**Config B (Coordinator-primary):** Coordinator Client is primary → DHT Client is fallback

### 7.2 Repository Structure

```
ResilientP2P/
├── Resilience_PRD.md
│
├── p2p-coordinator/          # Config B: Coordinator-primary + DHT-fallback
│   ├── common/               # Shared: config, logging, metrics, schemas
│   ├── coordinator/          # Coordinator service (FastAPI)
│   │   ├── main.py           # /register /publish /lookup /heartbeat /stats
│   │   └── store.py          # In-memory peer/content index
│   ├── peer/                 # Coordinator-primary peer
│   │   ├── cache.py          # LRU cache with SHA-256 validation
│   │   ├── client.py         # coordinator → [DHT fallback] → origin
│   │   └── main.py           # FastAPI: /trigger-fetch /get-object /stats
│   ├── dht/                  # DHT node (fallback path)  [TO ADD]
│   │   └── node.py           # Kademlia wrapper
│   ├── origin/               # Simulated origin server (WAN delay)
│   ├── docker-compose.yml
│   └── experiments/
│       ├── runner.py         # Workload/churn experiment orchestrator
│       └── workload.json     # 4 scenarios: smoke, burst, indep churn, corr churn
│
└── p2p-dht/                  # Config A: DHT-primary + Coordinator-fallback
    ├── common/               # Shared: config, logging, metrics, schemas
    ├── dht/
    │   └── node.py           # Kademlia wrapper (kademlia==2.2.2, ksize=5)
    ├── peer/                 # DHT-primary peer
    │   ├── cache.py          # LRU cache with SHA-256 validation
    │   ├── client.py         # DHT → coordinator fallback → origin
    │   └── main.py           # FastAPI: /trigger-fetch /get-object /stats
    ├── bootstrap/            # Bare Kademlia bootstrap node (UDP only)
    ├── docker-compose.yml    # Reuses coordinator/origin from p2p-coordinator/
    └── experiments/
        ├── runner.py         # Same interface as coordinator runner
        └── workload.json     # Same 4 scenarios (directly comparable)
```

### 7.3 Technology Stack

| Component | Technology | Decision |
|-----------|-----------|----------|
| **DHT** | `kademlia==2.2.2` (asyncio, UDP) | Proven Python library; `ksize=5` makes churn-induced data loss measurable |
| **Coordinator** | Python FastAPI + uvicorn | Lightweight; async-native; same runtime as peers |
| **Peer HTTP server** | FastAPI + uvicorn | Consistent stack across all services |
| **HTTP client** | `httpx` (async) | Async-native; compatible with FastAPI lifespan |
| **Simulation** | Docker Compose + WAN delay via origin `?delay=` param | No Mininet needed; containers on bridge network approximate LAN; origin simulates WAN |
| **Cache** | In-process `OrderedDict` (LRU) | Simple, fast, no external dependency |
| **Metrics** | Structured JSON stdout (`METRIC:` prefix) | Parseable by experiment runner; no infrastructure needed |
| **Experiment runner** | Python + `httpx` + `docker compose` CLI | Drives fetch/kill/restart events; writes JSON results |
| **Language** | Python 3.10 | Team expertise; asyncio throughout |

---

## 8. Implementation Plan

### Week 1: Design & Foundation
- [x] Finalize architecture designs (DHT-primary vs. Coordinator-primary details)
- [x] Design fall-back switching logic (per-request timeout-based triggers)
- [x] Create workload generator (course_burst and random_uniform profiles)
- [x] Establish metrics collection framework (METRIC: JSON stdout events)
- [ ] ~~Set up Mininet campus network topology~~ — replaced by Docker Compose

**Deliverable:** ✅ Design document (this PRD), Docker-based topology, workload traces

### Week 2–3: Implement Core Systems
- [x] **DHT Implementation** (`p2p-dht/`):
  - [x] Integrate Kademlia DHT library (`kademlia==2.2.2`)
  - [x] Implement peer discovery and content registration (`dht/node.py`)
  - [x] Add locality awareness (client-side sort by `location_id` in `peer/client.py`)

- [x] **Coordinator Implementation** (`p2p-coordinator/`):
  - [x] Build lightweight coordinator service (`coordinator/main.py`, `coordinator/store.py`)
  - [x] Implement peer registration and heartbeat
  - [x] Add content tracking and peer ranking by proximity + load (`locality_then_load` policy)

- [x] **Shared Infrastructure**:
  - [x] LRU cache with SHA-256 validation (`peer/cache.py`)
  - [x] Locality-aware peer selection logic
  - [x] HTTP client for peer-to-peer content transfer

**Deliverable:** ✅ Working DHT stack (`p2p-dht/`) and Coordinator stack (`p2p-coordinator/`)

### Week 4: Integration & Fall-back Logic
- [x] Configuration A: DHT-primary with Coordinator fallback (`p2p-dht/peer/client.py`)
- [ ] Configuration B: Coordinator-primary with DHT fallback (`p2p-coordinator/peer/client.py` — **in progress**)
  - [ ] Add `dht/node.py` to coordinator stack
  - [ ] Add DHT fallback path in coordinator `peer/client.py`
  - [ ] Add DHT bootstrap node to coordinator `docker-compose.yml`
- [ ] Merge `tanish` and `DHT` branches into unified integration branch
- [ ] End-to-end integration testing for both configurations

**Deliverable:** Both hybrid configurations working end-to-end

### Week 5: Evaluation & Experiments
- [ ] Run baseline experiments (no caching, direct origin)
- [ ] Configuration A experiments:
  - [ ] Cache hit rate (primary + fallback triggered)
  - [ ] Latency (DHT lookup vs. coordinator fallback latency)
  - [ ] Fallback frequency under independent and correlated churn
  - [ ] Bandwidth reduction (origin bytes vs. peer bytes)
- [ ] Configuration B experiments (same metrics)
- [ ] Comparative analysis: DHT-primary vs. Coordinator-primary

**Deliverable:** Evaluation results in `experiments/results/*.json`

### Week 6: Analysis, Polish & Documentation
- [ ] Analyze results and answer key questions:
  - Which configuration triggers fallback less frequently?
  - Which maintains better cache hit rates under churn?
  - Which has lower median and tail latency?
  - Which is operationally simpler?
- [ ] Create visualizations (latency CDF, bandwidth reduction over time, fallback event timeline)
- [ ] Write final technical report
- [ ] Prepare presentation/slides

**Deliverable:** Final report, slides, tagged release in repository

---

## 9. Evaluation Metrics & Success Criteria

### Metric: Cache Hit Rate
- **Definition**: (Peer cache hits) / (Total requests)
- **Measurement**: Parsed from `CACHE_HIT` / `CACHE_MISS` metric events in container logs
- **Success Criteria**:
  - Primary mode: >70% hit rate
  - Fallback mode: >60% hit rate
  - DHT-primary vs. Coordinator-primary: Difference <10 percentage points

### Metric: External Bandwidth Reduction
- **Definition**: (Origin bytes - Peer-cached bytes) / Origin bytes
- **Measurement**: `bytes_by_source` field in experiment result summary (`origin` vs. `peer` + `cache`)
- **Success Criteria**:
  - Achieve 60–75% reduction vs. direct origin access
  - Fallback mode reduction ≥50% of primary mode

### Metric: Access Latency
- **Definition**: Time from content request to first byte received
- **Measurement**: `service_latency_ms` in experiment result events (median, p95)
- **Success Criteria**:
  - Primary mode median latency ≤ direct origin access
  - Fallback mode median latency ≤ origin latency + 50ms
  - Fallback switching overhead <200ms

### Metric: Fallback Frequency
- **Definition**: Fraction of lookups that trigger fallback
- **Measurement**: Count of `COORDINATOR_FALLBACK` / `DHT_FALLBACK` metric events vs. total lookups
- **Success Criteria**:
  - <5% of lookups trigger fallback during normal operation (no churn)
  - Fallback frequency increases gracefully with churn rate
  - Both configurations remain stable under 20% per-minute churn

### Metric: Churn Resilience
- **Definition**: Cache hit rate under varying churn scenarios
- **Measurement**: Compare `source_counts` between no-churn and churn scenarios
- **Success Criteria**:
  - Hit rate >60% under 20% per-minute churn
  - Correlated churn (class ending) handled as well as random churn
  - Fallback prevents catastrophic hit rate collapse

### Metric: Operational Complexity
- **Definition**: Effort required to deploy and maintain system
- **Measurement**: Service count, configuration surface (env vars), extra infrastructure required
- **Coordinator-primary**: 3 services (coordinator, origin, peers) + 1 bootstrap node when DHT fallback added
- **DHT-primary**: 4 services (coordinator, origin, peers, bootstrap) — same
- **Success Criteria**: Document qualitative complexity differences based on observed failure modes

---

## 10. Constraints & Assumptions

### Constraints
- **Time**: 6 weeks to design, implement, evaluate, and document
- **Team**: 2 people (Tanish + Swarup)
- **Evaluation scope**: Docker Compose simulation only, not real campus deployment
- **Content size**: Fixed 1MB objects (origin generates deterministic content per `object_id`); large streaming deferred

### Assumptions
- **Access patterns**: Course-driven bursts and uniform random requests (modeled in `workload.json`)
- **Churn patterns**: Independent random churn and correlated class-exit churn (modeled in `workload.json`)
- **Network**: All containers on single Docker bridge network; WAN latency simulated via origin `?delay=0.1s` parameter
- **Peer capacity**: 10MB cache per peer (Docker default; configurable)
- **Trust**: Benign peers assumed (no Byzantine adversaries)
- **Content**: Immutable per `object_id` (SHA-256 checksum enforced on cache write)

---

## 11. Risk Mitigation

| Risk | Impact | Likelihood | Status | Mitigation |
|------|--------|-----------|--------|-----------|
| DHT integration complexity | Delays | Medium | ✅ Resolved | Used `kademlia==2.2.2`; working in `p2p-dht/` |
| Coordinator bottleneck | Limits performance | Medium | Monitoring | Load-aware selection implemented; will measure under burst |
| Mininet simulation inaccuracy | Unrealistic results | Low | ✅ Resolved | Replaced with Docker Compose + simulated WAN delay |
| Churn correlation analysis | Complex to model | Medium | ✅ Resolved | Correlated churn modeled in `workload.json` via `kind: correlated` |
| Config B DHT fallback missing | Incomplete comparison | High | **In progress** | Adding DHT node to coordinator stack (Week 4) |
| Branch divergence | Integration pain | Medium | **In progress** | Merging `tanish` + `DHT` branches |

---

## 12. Success Definition

### Project is Successful if:

1. **Both hybrid configurations are implemented and working**
   - [x] Configuration A (DHT-primary + Coordinator-fallback) — `p2p-dht/`
   - [ ] Configuration B (Coordinator-primary + DHT-fallback) — `p2p-coordinator/` (DHT fallback pending)
   - [ ] Fall-back switching triggered and measured in experiments

2. **Evaluation shows meaningful differences**
   - [ ] Clear winner between configurations (latency, hit rate, or fallback frequency)
   - [ ] Fallback mechanism proves valuable (prevents >20% hit rate drops under churn)
   - [ ] Results reproducible from `experiments/runner.py`

3. **Achieves bandwidth reduction goals**
   - [ ] 60–75% external bandwidth reduction demonstrated
   - [ ] Cache hit rates >60–70% in primary modes

4. **Report answers the core research question**
   - [ ] Clear recommendation: "For campus networks, X-primary is better because..."
   - [ ] Justification based on empirical evaluation

5. **Code is documented and reproducible**
   - [x] Both stacks runnable with `docker compose up --build`
   - [x] Experiments runnable with `python runner.py`
   - [ ] README with setup instructions
   - [x] Comments and docstrings in core modules

---

## 13. Team Responsibilities

### Tanish Praveen Nagrani
- **Coordinator Implementation**: Coordinator service, peer registration, heartbeat, load-aware selection ✅
- **Config B peer**: Coordinator-primary fetch pipeline, LRU cache, metrics ✅
- **Config B DHT fallback**: Adding DHT node to coordinator peer stack (in progress)
- **Integration**: End-to-end testing, branch merge

### Swarup Panda
- **DHT Implementation**: Kademlia wrapper (`dht/node.py`), read-modify-write provider lists ✅
- **Config A peer**: DHT-primary fetch pipeline with coordinator fallback, locality-aware selection ✅
- **Evaluation Infrastructure**: Experiment runner, workload scenarios, churn profiles ✅
- **Analysis**: Comparative evaluation results, visualizations

### Shared Responsibilities
- Branch merge and integration testing (Week 4)
- Final evaluation runs (Week 5)
- Report and presentation (Week 6)

---

## 14. Definition of Done

A feature is "done" when:
- [x] Code is written and passes manual smoke test
- [ ] Integrated with rest of system (both stacks)
- [x] Documented (comments + docstrings in core modules)
- [ ] Evaluated on at least one experiment scenario
- [ ] No blocking issues remaining

---

## 15. Appendix: Example Evaluation Scenario

### Scenario: "Busy Assignment Day"
**Setup:**
- 3 peers across 2 buildings; 20 requests over 18 seconds
- Popular content: 3 assignment objects (weighted), accessed in a course burst
- Secondary content: campus news, accessed randomly

**Expected Results (Config A — DHT-primary):**
- First fetch of each object: `source=origin` (cold start)
- Subsequent fetches: `source=peer` via DHT lookup (DHT hit rate improves as peers warm up)
- Under correlated churn (Building-A peers crash): `COORDINATOR_FALLBACK` events visible; `source=origin` spike then recovery

**Expected Results (Config B — Coordinator-primary):**
- First fetch of each object: `source=origin`
- Subsequent fetches: `source=peer` via coordinator lookup (faster O(1) lookup vs. DHT)
- Under coordinator crash: `DHT_FALLBACK` events visible; higher latency but continued availability

**Key Comparison:**
- Config B should show lower median lookup latency in normal operation
- Config A should show lower fallback frequency under coordinator failure
- Both should achieve >60% peer hit rate after warm-up

---

## 16. References

[1] L. Zhang, F. Zhou, A. Mislove, and R. Sundaram. "Maygh: Building a CDN from client web browsers." EuroSys 2013.
[2] S. Iyer, A. Rowstron, and P. Druschel. "Squirrel: A decentralized peer-to-peer web cache." PODC 2002.
[3] M.J. Freedman et al. "Democratizing content publication with Coral." NSDI 2004.
[4] B. Cohen. "Incentives build robustness in BitTorrent." P2P Systems Economics 2003.
[5] P. Maymounkov and D. Mazières. "Kademlia: A peer-to-peer information system based on the XOR metric." IPTPS 2002.

---

**Document Status:** Active
**Last Updated:** March 25, 2025
**Next Review:** End of Week 4 (integration complete)
