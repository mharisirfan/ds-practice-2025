# Vector Clock Lamport Diagram - Distributed Order Processing System

## System Overview

This document describes the vector clock causality for the distributed order processing system. The system uses vector clocks to maintain causal ordering across multiple microservices.

**Vector Clock Notation:** `VC = (Orch, TV, FD, SG, OQ)`
- Orch = Orchestrator
- TV = Transaction Verification Service  
- FD = Fraud Detection Service
- SG = Suggestions Service
- OQ = Order Queue Service

---

## Lamport Vector Clock Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Vector Clock Timeline: (Orch, TV, FD, SG, OQ)                                                   │
│  Time: 1,0,0,0  │  2,0,0,0  │  3,0,0,0  │  4,0,0,0  │  5,0,0,0  │  6,0,0,0  │  7,0,0,0        │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  ORCHESTRATOR (Orch)                                                                              │
  │                                                                                                   │
  │  • (1,0,0,0,0)              • (2,0,0,0,0)         • (3,0,0,0,0)         • (4,0,0,0,0)           │
  │       INIT                   after A,B          after C,D merge      after E            after F  │
  │   ├─────────────────────────┬──────────────┬────────────────┬─────────────────┬──────────────┐  │
  │   │                         │              │                │                 │              │  │
  └───┼─────────────────────────┼──────────────┼────────────────┼─────────────────┼──────────────┘  │
      │                         │              │                │                 │
      ↓                         ↓              ↓                ↓                 ↓
  
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  TRANSACTION VERIFICATION (TV)                                                                   │
  │                                                                                                   │
  │  ...........• (1,1,0,0,0)─────────────• (1,2,0,0,0)─────────────• (1,3,0,0,0)                   │
  │             │      a                   │       b                 │       c                       │
  │         VC: 1,1,0,0,0               VC: 1,2,0,0,0           VC: 1,3,0,0,0                       │
  │             │                         │                       │                                  │
  └─────────────┼─────────────────────────┼───────────────────────┼──────────────────────────────────┘
                │                         │                       │
                ├─────────────────────────┘                       │
                │ (a completes)                                   │
                │                                                 │
  ┌─────────────┼─────────────────────────────────────────────────┼──────────────────────────────────┐
  │             │  FRAUD DETECTION (FD)                           │                                  │
  │             │                                                 │                                  │
  │             ├────────────────────────• (1,2,1,0,0)───────────┐                                  │
  │             │                        │        d              │ (merge from a,b,c)               │
  │             │                    VC: 1,2,1,0,0               │                                  │
  │             │                        │                       ↓                                   │
  │             │                        │              • (1,3,2,0,0)                               │
  │             │                        │              │        e                                  │
  │             │                        │          VC: 1,3,2,0,0                                  │
  │             │                        │              │                                          │
  └─────────────┼────────────────────────┼──────────────┼────────────────────────────────────────────┘
                │                        │              │
                │ (b → d)               │              │ (c,d → e)
                │                        │              │
  ┌─────────────┴────────────────────────┴──────────────┴────────────────────────────────────────────┐
  │ SUGGESTIONS (SG)                                                                                │
  │                                                                                                  │
  │                                                    • (1,3,2,1,0)                                │
  │                                                    │       f                                    │
  │                                                VC: 1,3,2,1,0                                   │
  │                                                    │                                            │
  └────────────────────────────────────────────────────┼────────────────────────────────────────────┘
                                                       │
                                              (e → f)  │
                                                       ↓
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │ ORDER QUEUE (OQ)                                                                                │
  │                                                                                                  │
  │                                                           • (1,3,2,1,1)                         │
  │                                                           │      g                              │
  │                                                       VC: 1,3,2,1,1                            │
  │                                                           │  (ENQUEUE)                         │
  │                                                           │                                    │
  └───────────────────────────────────────────────────────────┼────────────────────────────────────┘
                                                              │
                                                    (f → g)  │
                                                             ↓
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │ FINAL STATE & CLEAR BROADCAST                                                                   │
  │                                                                                                  │
  │ VCf (Final Vector Clock) = (2,3,2,1,1)                                                         │
  │                                                                                                  │
  │ Broadcast ClearOrder(order_id, VCf=(2,3,2,1,1)) to:                                           │
  │  ├─ TV: waits until local_vc ≤ VCf → CLEAR ✓                                                  │
  │  ├─ FD: waits until local_vc ≤ VCf → CLEAR ✓                                                  │
  │  └─ SG: waits until local_vc ≤ VCf → CLEAR ✓                                                  │
  │                                                                                                  │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Vector Clock Event Details

| Event | Process | Type | VC In | VC Out | Depends On | Description |
|-------|---------|------|-------|--------|-----------|-------------|
| **INIT** | Orchestrator | Initialize | (0,0,0,0,0) | (1,0,0,0,0) | - | Tick orchestrator, broadcast to TV, FD, SG |
| **a** | Transaction Verif. | Verify Items | (1,0,0,0,0) | (1,1,0,0,0) | INIT | Check order has items |
| **b** | Transaction Verif. | Verify User Data | (1,0,0,0,0) | (1,2,0,0,0) | INIT | Validate user fields |
| **c** | Transaction Verif. | Verify Card Format | (1,2,0,0,0) | (1,3,0,0,0) | **a** | Check card format |
| **d** | Fraud Detection | Check User Fraud | (1,2,0,0,0) | (1,2,1,0,0) | **b** | User fraud checks |
| **e** | Fraud Detection | Check Card Fraud | (1,3,1,0,0)* | (1,3,2,0,0) | **c ∧ d** | Card fraud checks (MERGE) |
| **f** | Suggestions | Generate Suggestions | (1,3,2,0,0) | (1,3,2,1,0) | **e** | Generate recommendations |
| **g** | Order Queue | Enqueue | (1,3,2,1,0) | (1,3,2,1,1) | **f** | Add to queue |
| **Clear** | All Services | Clear State | VCf=(2,3,2,1,1) | - | **g** | Broadcast final clock |

*At event e, merge clocks from c and d: max((1,3,0,0,0), (1,2,1,0,0)) = (1,3,1,0,0)

---

## Detailed Trace with Causality

### Step-by-Step Execution

**Step 1: Initialization (Orch ticks)**
```
Orchestrator: (0,0,0,0,0) → (1,0,0,0,0)
Broadcast InitOrder to TV, FD, SG with VC=(1,0,0,0,0)
```

**Step 2: Event A - Verify Items (TV)**
```
Message from Orch: VC=(1,0,0,0,0)
TV receives: increments TV component
VC=(1,1,0,0,0) ← Event a recorded
```

**Step 3: Event B - Verify User Data (TV - parallel)**
```
Message from Orch: VC=(1,0,0,0,0)
TV receives: increments TV component again
VC=(1,2,0,0,0) ← Event b recorded
```

**Step 4: Event C - Verify Card Format (TV - depends on A)**
```
Orchestrator waits for Event A: (1,1,0,0,0)
Orchestrator ticks: (2,1,0,0,0) → (1,2,0,0,0)
Message to TV: VC=(1,2,0,0,0)
TV receives: increments TV component
VC=(1,3,0,0,0) ← Event c recorded [c happens after a]
```

**Step 5: Event D - Check User Fraud (FD - depends on B)**
```
Orchestrator waits for Event B: (1,2,0,0,0)
Orchestrator ticks: (2,2,0,0,0) → (1,2,0,0,0)  
Message to FD: VC=(1,2,0,0,0)
FD receives: increments FD component
VC=(1,2,1,0,0) ← Event d recorded [d happens after b]
```

**Step 6: Event E - Check Card Fraud (FD - MERGE of C and D)**
```
Orchestrator waits for both:
  - Event C: (1,3,0,0,0)
  - Event D: (1,2,1,0,0)
  
MERGE (component-wise max): (1,3,1,0,0)
Orchestrator ticks: (2,3,1,0,0) → (1,3,1,0,0)
Message to FD: VC=(1,3,1,0,0)
FD receives: increments FD component
VC=(1,3,2,0,0) ← Event e recorded [e happens after both c and d]
```

**Step 7: Event F - Generate Suggestions (SG - depends on E)**
```
Orchestrator waits for E: (1,3,2,0,0)
Orchestrator ticks: (2,3,2,0,0) → (1,3,2,0,0)
Message to SG: VC=(1,3,2,0,0)
SG receives: increments SG component
VC=(1,3,2,1,0) ← Event f recorded [f happens after e]
```

**Step 8: Enqueue Order (OQ - depends on F)**
```
All events complete: VC=(1,3,2,1,0)
Send to Order Queue: VC=(1,3,2,1,0)
OQ receives: increments OQ component
VC=(1,3,2,1,1) ← Event g recorded [order in queue]
```

**Step 9: Final Clear Broadcast**
```
Orchestrator final tick: (2,3,2,1,1) → VCf=(2,3,2,1,1)
Broadcast ClearOrder(order_id, VCf) to:

  TV:  local_vc=(1,3,0,0,0), VCf=(2,3,2,1,1)
       Check: 1 ≤ 2 ✓, 3 ≤ 3 ✓, 0 ≤ 2 ✓, 0 ≤ 1 ✓, 0 ≤ 1 ✓
       → CLEAR per-order state ✓
  
  FD:  local_vc=(1,3,2,0,0), VCf=(2,3,2,1,1)
       Check: 1 ≤ 2 ✓, 3 ≤ 3 ✓, 2 ≤ 2 ✓, 0 ≤ 1 ✓, 0 ≤ 1 ✓
       → CLEAR per-order state ✓
  
  SG:  local_vc=(1,3,2,1,0), VCf=(2,3,2,1,1)
       Check: 1 ≤ 2 ✓, 3 ≤ 3 ✓, 2 ≤ 2 ✓, 1 ≤ 1 ✓, 0 ≤ 1 ✓
       → CLEAR per-order state ✓
```

---

## Causality Relations

```
happens_before (→):
  INIT → a,b
  a → c
  b → d  
  c ∧ d → e  (merge: both predecessors)
  e → f
  f → g (enqueue)
  g → CLEAR (final broadcast)
```

---

## Vector Clock Rules Applied

### Rule 1: Local Event (Increment)
When a process executes a local event, it increments its own clock component:
```
TV before event a: (1, 0, 0, 0, 0)
TV increments TV component → (1, 1, 0, 0, 0)
```

### Rule 2: Send Message (Increment before send)
Sender increments before sending message:
```
Orchestrator before sending to TV: increments Orch component
Then sends message with updated VC
```

### Rule 3: Receive Message (Merge + Increment)
Receiver merges received VC with local, then increments own component:
```
TV receives VC=(1,2,0,0,0) from Orch
TV merges: max(local, received) = (1,2,0,0,0)
TV increments TV: (1, 2+1, 0, 0, 0) = (1,3,0,0,0)
```

### Rule 4: Merge at Join Points
When two causally independent events merge (like c and d → e):
```
VC_c = (1, 3, 0, 0, 0)
VC_d = (1, 2, 1, 0, 0)
VC_merged = max component-wise = (1, 3, 1, 0, 0)
Then orchestrator increments: (1, 3, 1, 0, 0)
```

---

## Causality Example

**Event c causally depends on event a:**
```
Event a           Event c
  ↓                 ↑
VC=(1,1,0,0,0)   VC=(1,3,0,0,0)
  
We know a→c because:
- VC_a.orch (1) ≤ VC_c.orch (1) ✓
- VC_a.tv (1) ≤ VC_c.tv (3)   ✓  (TV incremented!)
- All other components equal or increased
→ c definitely happens after a
```

**Event e merges independent events c and d:**
```
Event c: VC=(1,3,0,0,0)   Event d: VC=(1,2,1,0,0)

These are concurrent (neither causes the other):
- c→d? No (VC_c.fd > VC_d.fd: 0 > 1? NO) 
- d→c? No (VC_d.tv > VC_c.tv: 2 < 3? YES, so maybe...)
  Actually: VC_d.tv=2 ≤ VC_c.tv=3, but VC_d.fd=1 > VC_c.fd=0
  So d ⊥ c (concurrent)

Orchestrator merges both results:
max((1,3,0,0,0), (1,2,1,0,0)) = (1,3,1,0,0)

This VC now represents "after both c and d completed"
```

---

## Clearing Constraint Verification

**Final Vector Clock:** VCf = (2,3,2,1,1)

**Transaction Verification Service**
- Last event: event c with VC=(1,3,0,0,0)
- Check before clearing: local_vc ≤ VCf?
  - 1 ≤ 2? YES ✓
  - 3 ≤ 3? YES ✓
  - 0 ≤ 2? YES ✓
  - 0 ≤ 1? YES ✓
  - 0 ≤ 1? YES ✓
- All true → SAFE to clear ✓

**Fraud Detection Service**
- Last event: event e with VC=(1,3,2,0,0)
- Check before clearing: local_vc ≤ VCf?
  - 1 ≤ 2? YES ✓
  - 3 ≤ 3? YES ✓
  - 2 ≤ 2? YES ✓
  - 0 ≤ 1? YES ✓
  - 0 ≤ 1? YES ✓
- All true → SAFE to clear ✓

**Suggestions Service**
- Last event: event f with VC=(1,3,2,1,0)
- Check before clearing: local_vc ≤ VCf?
  - 1 ≤ 2? YES ✓
  - 3 ≤ 3? YES ✓
  - 2 ≤ 2? YES ✓
  - 1 ≤ 1? YES ✓
  - 0 ≤ 1? YES ✓
- All true → SAFE to clear ✓

---

## Implementation Details (From Code)

### Tick Operation (orchestrator/src/app.py)
```python
def tick_orchestrator(clock):
    """Increment orchestrator component before dispatching event"""
    updated = dict(clock)
    updated[ORCH_KEY] = updated.get(ORCH_KEY, 0) + 1
    return updated
```

### Merge Operation (orchestrator/src/app.py)
```python
def merge_clocks(*clocks):
    """Component-wise maximum for join events"""
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged
```

### Clear Constraint (fraud_detection/src/app.py)
```python
def clock_lte(local_clock, final_clock):
    """Verify causality before clearing: local ≤ final element-wise"""
    keys = set(local_clock.keys()) | set(final_clock.keys())
    for key in keys:
        if local_clock.get(key, 0) > final_clock.get(key, 0):
            return False
    return True
```

### Per-Order State Management
Each service maintains:
```python
self.order_cache = {}      # Per-order data/state
self.order_clocks = {}     # Per-order vector clock
self.lock = threading.Lock()  # Thread-safe access
```

---

## Why Vector Clocks Matter in This System

1. **Causal Ordering**: Ensures a→c→e→f happens in correct order
   - Event C cannot execute before Event A completes
   - Event E knows both C and D are done (merge point)

2. **Safe Parallel Execution**: 
   - Events A and B can run in parallel (no dependency)
   - Events C and D can run in parallel (depend on different predecessors)
   - Only Event E needs to wait for both

3. **Atomic State Cleanup**:
   - Final broadcast with VCf ensures ordering constraint
   - Services independently verify readiness: `local_vc ≤ VCf`
   - No service clears state prematurely

4. **Race Condition Prevention**:
   Without vector clocks → TV might clear state while FD still processing
   With vector clocks → Services wait until all causally-prior events complete

5. **Distributed Verification**:
   Each service independently checks clearing constraint
   No central coordinator needed for verification
   Works even if broadcast messages arrive out of order

