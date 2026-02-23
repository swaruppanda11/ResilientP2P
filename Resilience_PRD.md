# Resilience: Hybrid P2P Web Caching for Campus Networks
## Product Requirements Document

**Project Name:** Resilience  
**Version:** 1.0  
**Date:** February 2025  
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
- If DHT lookups timeout or hit rates drop below threshold, switch to coordinator
- Coordinator tracks all online peers and their cache contents
- Coordinator returns list of peers with requested content
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
- **DHT-based**: Peers join DHT overlay, announce cached content via DHT put operations
- **Coordinator-based**: Peers register with central coordinator, send heartbeats
- **Hybrid**: Both mechanisms run in parallel (at least one active)

#### 6.2 Content Lookup & Routing
- **DHT lookup**: XOR-based routing to find peers with requested content
- **Coordinator lookup**: Query coordinator for list of peers with content
- **Locality awareness**: Both modes prefer geographically nearby peers
  - Use IP-based geolocation (campus subnet mapping)
  - Prefer peers on same building/floor when possible
  - Fall back to broader radius if local peers unavailable

#### 6.3 Intelligent Fall-back Mechanism
- **Health monitoring**: Continuous tracking of primary architecture health
  - DHT health: Lookup success rate, response latency, number of responsive neighbors
  - Coordinator health: Connectivity, response time, cache freshness
- **Fallback triggers**:
  - Time-based: If lookup takes >500ms, try fallback
  - Hit-based: If cache hit rate drops below 60% for 2 consecutive minutes, try fallback
  - Explicit: Fallback triggered on DHT timeout or coordinator unreachable
- **Graceful degradation**: System remains functional even if both modes degrade
- **Recovery**: Automatic switch back to primary when health improves

#### 6.4 Cache Management
- **Cache storage**: Peer browsers cache via browser LocalStorage (Coordinator-primary) or dedicated peer cache directory (DHT-primary + simulator)
- **Cache eviction**: LRU eviction when cache size exceeds 100MB
- **Content validation**: Simple HTTP ETag checking for cache freshness
- **Cache consistency**: Best-effort (accept stale content, validate on miss)

#### 6.5 Peer Selection & Load Balancing
- **Geographic proximity**: Calculate RTT to candidate peers, prefer lower RTT
- **Load balancing**: Don't overload single high-capacity peer
  - Track request count per peer
  - Distribute requests across top-3 nearest peers
  - Implement tit-for-tat incentive (upload to peers you download from)

#### 6.6 Churn Handling
- **Peer timeouts**: Mark peers as offline after 2 failed connection attempts or heartbeat miss
- **DHT re-publish**: Peers republish cache contents to DHT every 5 minutes (prevent stale entries)
- **Coordinator heartbeat**: Peers send heartbeat to coordinator every 30 seconds
- **Graceful shutdown**: Peers notify coordinator/DHT on departure

#### 6.7 Metrics & Observability
- **Per-peer metrics**: Cache hit rate, latency, uptime, churn events
- **System-wide metrics**: Bandwidth reduction, cache hit rate, external bandwidth usage, fallback frequency
- **Logging**: Structured logs for debugging (peer joins, lookups, fallbacks, failures)

---

## 7. Technical Architecture

### 7.1 System Components

```
┌─────────────────────────────────────────────────────────┐
│                     Student Browsers                     │
│  (JavaScript client, LocalStorage cache, P2P protocol)   │
└────────────┬────────────────────────────────────────────┘
             │
     ┌───────┴──────────┐
     │                  │
┌────▼─────┐    ┌──────▼──────┐
│    DHT   │◄──►│ Coordinator  │
│ Overlay  │    │  Service     │
└──────────┘    └──────────────┘
     │                  │
     └────────┬─────────┘
              │
         [Fallback Logic]
         [Health Monitor]
```

### 7.2 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **DHT Implementation** | libp2p Kademlia (or Python `kademlia` lib) | Proven, well-maintained |
| **Coordinator** | Python Flask/FastAPI | Lightweight, easy to implement |
| **Simulation** | Mininet or SimPy | Realistic campus network topology |
| **Peer Communication** | HTTP/REST or WebRTC DataChannel | Browser-friendly, no plugins needed |
| **Cache Storage** | Browser LocalStorage (sim) or filesystem | Simple, browser-native for web version |
| **Metrics Collection** | Prometheus-compatible or CSV export | Standard observability stack |
| **Language** | Python (DHT, Coordinator, Simulator) | Team expertise, rapid iteration |

---

## 8. Implementation Plan

### Week 1: Design & Foundation
- [ ] Finalize architecture designs (DHT-primary vs. Coordinator-primary details)
- [ ] Design fall-back switching logic (triggers, latency, state management)
- [ ] Set up Mininet campus network topology simulation
- [ ] Create workload generator (realistic access patterns)
- [ ] Establish metrics collection framework

**Deliverable:** Design document, Mininet topology, workload traces

### Week 2-3: Implement Core Systems
- [ ] **DHT Implementation**:
  - [ ] Integrate Kademlia DHT library
  - [ ] Implement peer discovery and content registration
  - [ ] Add locality awareness (subnet-based peer preferences)
  
- [ ] **Coordinator Implementation**:
  - [ ] Build lightweight coordinator service
  - [ ] Implement peer registration and heartbeat
  - [ ] Add content tracking and peer ranking by proximity
  
- [ ] **Shared Infrastructure**:
  - [ ] Cache interface (abstraction over DHT and Coordinator caches)
  - [ ] Peer selection logic (locality-aware ranking)
  - [ ] HTTP client for fetching from peers

**Deliverable:** Working DHT and Coordinator systems, passing unit tests

### Week 4: Integration & Fall-back Logic
- [ ] Implement fall-back mechanism for both configurations
  - [ ] Configuration A: DHT-primary with Coordinator fallback
  - [ ] Configuration B: Coordinator-primary with DHT fallback
- [ ] Health monitoring (latency, hit rate tracking)
- [ ] Fallback triggering and switching logic
- [ ] Recovery logic (switch back to primary when healthy)
- [ ] Integration testing in Mininet

**Deliverable:** Both hybrid configurations working end-to-end

### Week 5: Evaluation & Experiments
- [ ] Run baseline experiments (no caching, single origin)
- [ ] Configuration A experiments:
  - [ ] Cache hit rate (primary + fallback)
  - [ ] Latency (primary + fallback switching)
  - [ ] Fallback frequency under various churn rates
  - [ ] Bandwidth reduction
- [ ] Configuration B experiments (same metrics)
- [ ] Comparative analysis: which configuration is better?

**Deliverable:** Evaluation results (CSV, graphs, raw data)

### Week 6: Analysis, Polish & Documentation
- [ ] Analyze results and answer key questions:
  - Which configuration triggers fallback less frequently?
  - Which maintains better cache hit rates?
  - Which has lower latency overhead?
  - Which is operationally simpler?
- [ ] Create visualizations (latency CDF, bandwidth reduction over time, fallback events)
- [ ] Write final technical report
- [ ] Prepare presentation/slides

**Deliverable:** Final report, slides, code repository with instructions

---

## 9. Evaluation Metrics & Success Criteria

### Metric: Cache Hit Rate
- **Definition**: (Peer cache hits) / (Total requests)
- **Measurement**: Count at system-wide level and per-peer
- **Success Criteria**:
  - Primary mode: >70% hit rate
  - Fallback mode: >60% hit rate
  - DHT-primary vs. Coordinator-primary: Difference <10 percentage points

### Metric: External Bandwidth Reduction
- **Definition**: (Origin bytes - Peer-cached bytes) / Origin bytes
- **Measurement**: Bytes served by peers vs. origin server
- **Success Criteria**:
  - Achieve 60–75% reduction vs. direct origin access
  - Fallback mode reduction ≥50% of primary mode

### Metric: Access Latency
- **Definition**: Time from content request to first byte received
- **Measurement**: Median, 95th percentile, 99th percentile latency
- **Success Criteria**:
  - Primary mode median latency ≤ direct origin access
  - Fallback mode median latency ≤ origin latency + 50ms
  - Fallback switching overhead <200ms

### Metric: Fallback Frequency
- **Definition**: Number of fallback switches per minute
- **Measurement**: Count fallback trigger events
- **Success Criteria**:
  - <5% of lookups trigger fallback during normal operation
  - Fallback frequency increases gracefully with churn rate
  - Both configurations remain stable under 20% per-minute churn

### Metric: Churn Resilience
- **Definition**: Cache hit rate under varying churn scenarios
- **Measurement**: Hit rate vs. churn rate (random departures, correlated departures)
- **Success Criteria**:
  - Hit rate >60% under 20% per-minute churn
  - Correlated churn (class ending) handled as well as random churn
  - Fallback prevents catastrophic hit rate collapse

### Metric: Operational Complexity
- **Definition**: Effort required to deploy, monitor, and maintain system
- **Measurement**: Lines of coordinator code, DHT config complexity, operational tasks required
- **Success Criteria**:
  - Coordinator-primary <1000 LOC
  - DHT configuration <500 lines
  - Clear winner between the two configurations

### Metric: Latency Comparison (Configuration A vs. B)
- **Definition**: Primary mode latency for DHT-primary vs. Coordinator-primary
- **Success Criteria**:
  - If Coordinator-primary <DHT-primary by >50ms: easier to operate
  - If DHT-primary ≥ Coordinator-primary: decentralization justified

---

## 10. Constraints & Assumptions

### Constraints
- **Time**: 6 weeks to design, implement, evaluate, and document
- **Team**: 2 people (Tanish + Swarup), some work parallelizable
- **Evaluation scope**: Campus network simulation only, not real deployment
- **Content size**: Focus on small objects (web pages, assignments, metadata); large video streaming deferred

### Assumptions
- **Access patterns**: Realistic campus workload from prior literature (Maygh, campus traces)
- **Churn patterns**: Campus sessions 10–30 minutes, correlated with class schedules
- **Network**: LAN latency <10ms, WAN latency 50–100ms
- **Peer capacity**: Each peer can store ~100MB of cache
- **Trust**: Assume benign peers (no Byzantine adversaries)
- **Content**: Immutable or low-change-rate content (assignments, lecture videos)

---

## 11. Risk Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| DHT integration complexity | Delays Week 2-3 | Medium | Use proven library; spike early |
| Coordinator bottleneck | Limits Coord-primary performance | Medium | Load test early; optimize if needed |
| Mininet simulation inaccuracy | Results don't reflect real campus | Low | Validate against CU network traces |
| Churn correlation analysis | Complex to model correctly | Medium | Start with simple random churn; add correlation in Week 5 |
| Limited time for polish | Incomplete evaluation | Medium | Prioritize core metrics; cut secondary ones if needed |

---

## 12. Success Definition

### Project is Successful if:

1. ✅ **Both hybrid configurations are implemented and working** (Week 4)
   - DHT-primary + Coordinator-fallback functions end-to-end
   - Coordinator-primary + DHT-fallback functions end-to-end
   - Fall-back switching triggered and measured

2. ✅ **Evaluation shows meaningful differences** (Week 5)
   - Clear winner between configurations (one has better latency, one better simplicity, etc.)
   - Fallback mechanism proves valuable (prevents >20% hit rate drops)
   - Results are reproducible and documented

3. ✅ **Achieves bandwidth reduction goals** (Week 5)
   - 60–75% external bandwidth reduction demonstrated
   - Cache hit rates >60–70% in primary modes

4. ✅ **Report answers the core research question** (Week 6)
   - Clear recommendation: "For campus networks, DHT-primary/Coordinator-primary is better because..."
   - Justification based on empirical evaluation

5. ✅ **Code is documented and reproducible** (Week 6)
   - Clean repository with setup instructions
   - Comments explaining key logic
   - Evaluation scripts reproducible by others

---

## 13. Team Responsibilities

### Tanish Praveen Nagrani
- **Architecture & System Design**: Overall system design, fall-back logic, peer selection
- **Coordinator Implementation**: Build coordinator service, peer registration, health tracking
- **Integration**: Ensure both configurations work end-to-end
- **Documentation**: Final report, architecture diagrams

### Swarup Panda
- **DHT Integration & Implementation**: Kademlia DHT integration, content registration, locality hints
- **Evaluation Infrastructure**: Mininet topology, workload generator, metrics collection
- **Churn Modeling**: Realistic churn scenarios, correlated vs. random departures
- **Analysis**: Evaluation results, comparative analysis, visualization

### Shared Responsibilities
- Weekly sync on progress and blockers
- Code review and testing
- Final presentation preparation

---

## 14. Definition of Done

A feature is "done" when:
- [ ] Code is written and passes tests
- [ ] Integrated with rest of system
- [ ] Documented (comments + docstrings)
- [ ] Evaluated on a representative scenario
- [ ] No blocking issues remaining

---

## 15. Appendix: Example Evaluation Scenario

### Scenario: "Busy Assignment Day"
**Setup:**
- 100 students online, 20 per-minute joining/leaving (correlated: 2 classes overlap)
- Popular content: 3 assignment PDFs (20MB total), accessed 1000x/hour
- Secondary content: Various course materials (100MB), 200 accesses

**Expected Results:**
- Without caching: 1.8GB external bandwidth, high latency
- Configuration A (DHT-primary): 300MB external bandwidth, <2 fallbacks/min
- Configuration B (Coordinator-primary): 250MB external bandwidth, <1 fallback/min

**Success Metrics:**
- Both achieve >60% bandwidth reduction
- Configuration B has lower fallback frequency (coordinator fast lookups)
- Configuration A remains stable even with correlated churn

---

## 16. References

[1] L. Zhang, F. Zhou, A. Mislove, and R. Sundaram. "Maygh: Building a CDN from client web browsers." EuroSys 2013.  
[2] S. Iyer, A. Rowstron, and P. Druschel. "Squirrel: A decentralized peer-to-peer web cache." PODC 2002.  
[3] M.J. Freedman et al. "Democratizing content publication with Coral." NSDI 2004.  
[4] B. Cohen. "Incentives build robustness in BitTorrent." P2P Systems Economics 2003.  
[5] P. Maymounkov and D. Mazières. "Kademlia: A peer-to-peer information system based on the XOR metric." IPTPS 2002.

---

**Document Status:** Draft  
**Last Updated:** February 22, 2025  
**Next Review:** End of Week 1
