# Distributed Systems 2026 @ University of Tartu

## Online Bookstore System 
A book ordering system built with microservices architecture demonstrating REST, gRPC, concurrent processing, and proper system documentation.

### Project Overview
This project implements a distributed book ordering system where users can submit orders that are processed through multiple backend services. The system showcases key distributed systems concepts including inter-service communication, concurrent processing, and comprehensive logging.

### System Architecture
```mermaid
graph TD
    subgraph "Frontend Layer"
        A[Web Browser] -->|REST API| B[Frontend Server<br/>Port: 8082]
    end 

    subgraph "Orchestration Layer"
        B -->|POST checkout| C[Order Orchestrator<br/>Port: 5000]
    end    

    subgraph "Microservices Layer<br/>(Vector Clock Coordination)"
        C -->|gRPC: InitOrder + VC| D[Fraud Detection<br/>Port: 50051]
        C -->|gRPC: InitOrder + VC| E[Transaction Verification<br/>Port: 50052]
        C -->|gRPC: InitOrder + VC| F[Suggestions<br/>Port: 50053]
        
        E <-->|gRPC: VC propagation<br/>events d, e| D
        D <-->|gRPC: VC propagation<br/>event f| F
        E <-->|gRPC: VC propagation<br/>event c, d| D
    end

    subgraph "Execution Layer<br/>(2PC & Leader Election)"
        C -->|gRPC: enqueue_approved_order| G[Order Queue Service<br/>Port: 50060]
        
        G <-->|gRPC: TryAcquireLeadership<br/>& Dequeue| H1[Order Executor 1<br/>Port: 50070<br/>Leader]
        G <-->|gRPC: TryAcquireLeadership<br/>& Dequeue| H2[Order Executor 2<br/>Port: 50071<br/>Standby]
        
        H1 -.->|Competes for Lease| H2
    end

    subgraph "Persistence Layer<br/>(2PC Participants)"
        H1 <-->|gRPC: 2PC<br/>Prepare/Commit| I[Books Database Primary<br/>+ Backups<br/>Port: 50054]
        H1 <-->|gRPC: 2PC<br/>Prepare/Commit| J[Payment System<br/>Port: 50055]
        
        H2 <-->|gRPC: 2PC<br/>Prepare/Commit| I
        H2 <-->|gRPC: 2PC<br/>Prepare/Commit| J
    end
```
The architecture follows a layered approach with clear separation of concerns. The frontend communicates with the orchestrator via REST, which then coordinates three gRPC services concurrently.


### System Workflow
```mermaid
graph TD
    subgraph Frontend
        B[Pushed the submit button]
    end

    subgraph Orchestrator
        B --> C[checkout]
    end

    subgraph "Fraud Detection Microservice"
        D[DetectFraud] --> G[the user data<br/>the credit card info]
        G --> J[fraud detection<br/>is not fraud?]
    end

    subgraph "Transaction Verification Microservice"
        E[VerifyTransaction] --> H[the user data is<br/>all filled in?<br/>the credit card info is<br/>in the correct format?]
        H --> K[transaction verification]
    end

    subgraph "Suggestions Microservice"
        F[SuggestBook] --> I[the order items are<br/>not empty?<br/>Randomly pick up books<br/>from a static book list.]
        I --> L[book suggestion]
    end

    C --> D
    C --> E
    C --> F

    J --> N
    K --> N
    L --> N

    subgraph Orchestrator_
    N{Not fraud & verified?}
    N -->|No| O[Reject<br/>Show Error]
    N -->|Yes| P[Return order status<br/>Suggested Books]
    end

    subgraph Frontend_
    P --> R[Display order<br/>confirmed page]
    end
```
## End-to-End System Flow (Checkpoint2)

```mermaid
flowchart TD
    U[User fills Checkout Form] --> F[Frontend POST /checkout]
    F --> O[Orchestrator /checkout]

    O --> I1[InitOrder to Transaction Verification]
    O --> I2[InitOrder to Fraud Detection]
    O --> I3[InitOrder to Suggestions]

    I1 --> M[Orchestrator merges init vector clocks]
    I2 --> M
    I3 --> M

    M --> A[Event a: VerifyItems]
    M --> B[Event b: VerifyUserData]

    A --> C[Event c: VerifyCardFormat]
    B --> D[Event d: CheckUserFraud]

    C --> E[Event e: CheckCardFraud]
    D --> E

    E --> G[Event f: GenerateSuggestions]

    G --> DEC{All checks passed?}
    DEC -- Yes --> Q[Enqueue order in Order Queue]
    DEC -- No --> R[Reject Order]

    Q --> EXEC[Leader Executor dequeues and executes order]

    EXEC --> CLR[Final VCf broadcast clear to all 3 services.]
    R --> CLR

    CLR --> RESP[Return final response to frontend]
```

### Microservices Details

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| **Frontend Server** | 8082 | REST API | Web UI server that serves the shopping interface and handles checkout requests from users |
| **Order Orchestrator** | 5000 | REST API + gRPC | Orchestrates the entire order workflow: initializes microservices, coordinates event propagation with vector clocks, makes approval decisions, and triggers cleanup |
| **Transaction Verification** | 50052 | gRPC | Validates user data completeness and credit card format. Runs parallel branches via local dispatch, coordinates with Fraud Detection using vector clocks to enforce causal ordering of events (a, b, c) |
| **Fraud Detection** | 50051 | gRPC | Analyzes user data and credit card patterns for fraud indicators using rule-based detection. Depends on Transaction Verification events via vector clock validation. Calls Suggestions service to generate recommendations (event f) |
| **Suggestions** | 50053 | gRPC | Generates personalized book recommendations for approved orders. Receives event triggers via vector clock from Fraud Detection and merges clock state for causal consistency |
| **Order Queue Service** | 50060 | gRPC | Manages approved order queue and implements leader election. Executors compete for lease to become leader. Provides TryAcquireLeadership and Dequeue operations with gRPC-based coordination |
| **Order Executor 1** | 50070 | gRPC | Active leader executor: dequeues orders, acts as 2PC coordinator with Database and Payment System, manages decision log for recovery, executes committed transactions |
| **Order Executor 2** | 50071 | gRPC | Standby executor: competes for leadership lease, monitors queue, takes over if leader fails, maintains shared decision log for crash recovery |
| **Books Database Primary** | 50054 | gRPC | Primary database replica: stores book inventory and processes stock updates. Participates in 2PC protocol (Prepare/Commit/Abort). Coordinates with backup replicas for consistency |
| **Payment System** | 50055 | gRPC | Handles payment processing and state management. Participates in 2PC protocol, maintains prepared transaction state with TTL-based recovery, commits or aborts payments atomically |


## Vector Clocks Diagram
```mermaid
graph TB
    subgraph Init ["INITIALIZATION PHASE"]
        init["Init with VC=(1,0,0,0,0)"]
    end
    
    subgraph EventsPhase ["PARALLEL EVENT PROCESSING"]
        A["Event A: VerifyItems<br/>(Transaction Verification)<br/>VC in: (1,0,0,0,0)<br/>VC out: (1,1,0,0,0)"]
        B["Event B: VerifyUserData<br/>(Transaction Verification)<br/>VC in: (1,0,0,0,0)<br/>VC out: (1,2,0,0,0)"]
        
        C["Event C: VerifyCardFormat<br/>(Transaction Verification)<br/>Depends on A<br/>VC in: (1,2,0,0,0)<br/>VC out: (1,3,0,0,0)"]
        
        D["Event D: CheckUserFraud<br/>(Fraud Detection)<br/>Depends on B<br/>VC in: (1,2,0,0,0)<br/>VC out: (1,2,1,0,0)"]
        
        E["Event E: CheckCardFraud<br/>(Fraud Detection)<br/>MERGE(C,D)<br/>VC in: (1,3,1,0,0)<br/>VC out: (1,3,2,0,0)"]
        
        F["Event F: GenerateSuggestions<br/>(Suggestions Service)<br/>Depends on E<br/>VC in: (1,3,2,0,0)<br/>VC out: (1,3,2,1,0)"]
    end
    
    subgraph Queue ["QUEUE & CLEAR PHASE"]
        Enq["Enqueue Order<br/>(Order Queue)<br/>VC in: (1,3,2,1,0)<br/>VC out: (1,3,2,1,1)"]
        
        Clear["Final Clear Broadcast<br/>VCf = (2,3,2,1,1)<br/>Clear sent to all services <br/>with final vector clock"]
    end
    
    Result["✓ Order Processed<br/>All state cleaned up"]
    
    Init --> A
    Init --> B
    
    A --> C
    B --> D
    
    C --> E
    D --> E
    
    E --> F
    
    F --> Enq
    
    Enq --> Clear
    Clear --> Result

```


## Leader Election Diagram
```mermaid
sequenceDiagram
    participant E1 as Executor-1
    participant E2 as Executor-2
    participant Q as Order Queue

    loop Every POLL_SECONDS
        E1->>Q: TryAcquireLeadership(executor-1, lease=2s)
        Q-->>E1: granted=true, leader=executor-1
    end

    loop Every POLL_SECONDS
        E2->>Q: TryAcquireLeadership(executor-2, lease=2s)
        Q-->>E2: granted=false, leader=executor-1
    end

    E1->>Q: Dequeue(executor-1)
    Q-->>E1: allowed (leader only)

    Note over Q: Mutual exclusion: only current lease holder can dequeue.

    Note over E1,E2: If E1 lease expires or E1 fails, E2 can acquire leadership.

    E2->>Q: TryAcquireLeadership(executor-2)
    Q-->>E2: granted=true
    E2->>Q: Dequeue(executor-2)
    Q-->>E2: allowed
```

```mermaid
sequenceDiagram
    participant E1 as Executor-1
    participant Q as Order Queue
    participant E2 as Executor-2

    Note over E1,E2: Snapshot 1: Executor-1 Acquires Leadership
    E1->>Q: TryAcquireLeadership(executor-1, lease=2s)
    Q-->>E1: granted=true, leader_id=executor-1
    E2->>Q: TryAcquireLeadership(executor-2, lease=2s)
    Q-->>E2: granted=false, leader_id=executor-1
    E1->>Q: Dequeue(executor-1)
    Q-->>E1: Order1 (allowed - leader only)
    Note over Q: leader_expiry = now + 2s
```
```mermaid
sequenceDiagram
    participant E1 as Executor-1
    participant Q as Order Queue
    participant E2 as Executor-2

    Note over E1,E2: Snapshot 2: Executor-1 Lease Expires / Fails
    Note over E1: (Time: leader_expiry reached)
    E1->>Q: TryAcquireLeadership(executor-1, lease=2s)
    Q-->>E1: granted=false, leader_id=NONE
    Note over Q: Lease expired - no current leader
    E2->>Q: TryAcquireLeadership(executor-2, lease=2s)
    Q-->>E2: granted=true, leader_id=executor-2
    Note over Q: leader_expiry = now + 2s (E2's lease)
```
```mermaid
sequenceDiagram
    participant E1 as Executor-1
    participant Q as Order Queue
    participant E2 as Executor-2

    Note over E1,E2: Snapshot 3: Executor-2 Acquires Leadership (Failover)
    E2->>Q: TryAcquireLeadership(executor-2, lease=2s)
    Q-->>E2: granted=true, leader_id=executor-2
    E1->>Q: TryAcquireLeadership(executor-1, lease=2s)
    Q-->>E1: granted=false, leader_id=executor-2
    E2->>Q: Dequeue(executor-2)
    Q-->>E2: Order2 (allowed - leader only)
    Note over Q: leader_expiry = now + 2s
    Note over E1: Standby mode: retry TryAcquireLeadership after POLL_SECONDS
```

Our leader-election mechanism is lease-based and dynamically supports N executors (N > 2), not just two fixed replicas. Any executor instance with a unique executor_id can compete for leadership by calling TryAcquireLeadership; the order_queue grants leadership to only one active lease holder at a time, so mutual exclusion is preserved for dequeue operations. The system is resilient to failures because if the current leader crashes or stops renewing, its lease expires and another executor automatically becomes leader on the next polling cycle. **This design is centralized**, which makes coordination simple and deterministic, but also introduces trade-offs: the queue service is a potential single point of failure and bottleneck compared to decentralized approaches. **Bonus Point**

# Checkpoint 3
## Books Database Service Overview

The Books Database functions as a distributed, in-memory key-value store responsible for managing the inventory of items across the microservice ecosystem. To ensure fault tolerance and high availability under heavy system load, the data state is replicated across multiple independent instances. The implementation relies on several core distributed systems patterns to maintain data integrity and consistency.

**Primary-Backup Architecture**

The database is structured around a single Primary node and multiple Backup nodes. All read and write requests initiated by the Order Execution layer are routed exclusively to the Primary instance. The Primary is responsible for managing the canonical state of the database and orchestrating the downstream propagation of any updates to the Backup replicas.

**Synchronous Replication**

To prevent data loss and ensure a unified state across the distributed system, a synchronous replication protocol is employed. When a write request modifies the inventory, the Primary first updates its internal local state and subsequently broadcasts the exact update to all connected Backup nodes. The Primary blocks the client transaction and waits for explicit acknowledgments from all active Backups before returning a successful response. This design actively trades lower latency and higher availability for strict sequential consistency, guaranteeing that an acknowledged order is never lost even if the Primary node experiences a catastrophic failure.

**Optimistic Concurrency Control (Compare-And-Swap)**

Given that multiple Order Executors operate in parallel, the system is highly susceptible to race conditions, such as "lost updates" where simultaneous transactions overwrite one another. To safely manage concurrent writes without relying on expensive, highly restrictive distributed locks, Optimistic Concurrency Control (OCC) is utilized via a Compare-And-Swap (CAS) mechanism. 

When an executor submits a write request, it includes an `expected_stock` parameter—reflecting the state of the inventory at the exact moment it was read. Before applying the update, the Primary node evaluates whether the current local stock still matches this expected value. 
*   **If the values match:** The transaction proceeds, and the update is replicated.
*   **If the values differ:** It indicates that another concurrent process has already modified the inventory. The Primary safely rejects the write operation, prompting the initiating executor to back off, re-read the latest state, and retry the transaction.

---

### Consistency Protocol Diagram

Below is the sequence diagram illustrating the complete network flow of the synchronous replication process, alongside the resolution of a concurrent transaction attempt.

```mermaid
sequenceDiagram
    participant Exec1 as Order Executor 1
    participant Primary as DB Primary
    participant Backup1 as DB Backup 1
    participant Backup2 as DB Backup 2
    participant Exec2 as Order Executor 2

    Note over Exec1, Backup2: Phase 1: Read Operation
    Exec1->>Primary: ReadRequest(title="Book A")
    Primary-->>Exec1: ReadResponse(stock=10)
    
    Note over Exec1: Inventory evaluated.<br/>new_stock = 9<br/>expected_stock = 10

    Note over Exec1, Backup2: Phase 2: Synchronous Write & CAS Validation
    Exec1->>Primary: WriteRequest("Book A", new_stock=9, expected_stock=10)
    
    Note over Primary: CAS Check:<br/>Current (10) == Expected (10) -> OK
    Primary->>Primary: Update local state: "Book A" = 9
    
    par Synchronous Replication
        Primary->>Backup1: WriteRequest("Book A", new_stock=9, is_replica_sync=True)
        Primary->>Backup2: WriteRequest("Book A", new_stock=9, is_replica_sync=True)
    end
    
    Note over Backup1, Backup2: Backups bypass CAS validation<br/>(is_replica_sync=True)
    Backup1->>Backup1: Update local state: "Book A" = 9
    Backup2->>Backup2: Update local state: "Book A" = 9
    
    par Replication Acknowledgment
        Backup1-->>Primary: WriteResponse(Success=True)
        Backup2-->>Primary: WriteResponse(Success=True)
    end
    
    Primary-->>Exec1: WriteResponse(Success=True)
    Note over Exec1: Transaction committed successfully

    Note over Exec2, Primary: Phase 3: Concurrent Write Handling (Contention)
    Exec2->>Primary: WriteRequest("Book A", new_stock=9, expected_stock=10)
    Note over Primary: CAS Check:<br/>Current (9) != Expected (10) -> FAILED
    Primary-->>Exec2: WriteResponse(Success=False)
    Note over Exec2: Transaction aborted.<br/>Client initiates backoff and retry loop.
```




---------------------------------------------------------------------------------


## System Flow - Complete Protocol - Distributed Commitment Protocol diagram
```mermaid
sequenceDiagram
    autonumber
    participant UI as Frontend
    participant ORC as Orchestrator
    participant TV as TransactionVerification
    participant FD as FraudDetection
    participant SUG as Suggestions
    participant OQ as OrderQueue
    participant EX as OrderExecutor<br/>2PC Coordinator
    participant DB as BooksDatabase
    participant PAY as PaymentSystem

    UI->>ORC: POST /checkout (order payload)
    
    rect rgb(200, 220, 255)
    Note over ORC,SUG: Phase 1: Initialization & VC Setup
    ORC->>TV: InitOrder + VC={orchestrator:1}
    ORC->>FD: InitOrder + VC={orchestrator:1}
    ORC->>SUG: InitOrder + VC={orchestrator:1}
    end

    rect rgb(200, 220, 255)
    Note over ORC,SUG: Phase 2: Causal Event Flow with Vector Clocks
    ORC->>TV: StartVerificationFlow + VC={orchestrator:2}
    
    Note over TV: Local parallel branches:<br/>a_verify_items → c_verify_card<br/>b_verify_user_data<br/>Join → event ordering via VC
    
    TV->>FD: CheckUserFraud (event d) + VC
    FD-->>TV: ok + VC (with dependency checks)
    
    TV->>FD: CheckCardFraud (event e) + VC
    FD->>SUG: GenerateSuggestions (event f) + VC
    SUG-->>FD: ok + VC + books
    FD-->>TV: ok + VC + metadata(suggestions)
    
    TV-->>ORC: ok + VC + metadata(suggestions)
    end

    rect rgb(200, 220, 255)
    Note over ORC,OQ: Phase 3: Decision & Enqueue
    alt Order Approved (all events passed VC validation)
        ORC->>OQ: Enqueue(order, VCf)
    else Causal Violation OR Business Logic Reject
        ORC->>TV: ClearOrder(VCf) - validate VC
        ORC->>FD: ClearOrder(VCf) - validate VC
        ORC->>SUG: ClearOrder(VCf) - validate VC
        ORC-->>UI: status=Rejected + reason
        Note over ORC: Order cleanup complete
    end
    end

    rect rgb(255, 220, 200)
    Note over EX,PAY: Phase 4: 2-Phase Commit (Atomicity)
    EX->>OQ: Dequeue(order)
    
    Note over EX: Decision Log: RECEIVED
    
    par 2PC Phase 1: Prepare (Voting)
        EX->>DB: Prepare(order_id, items, qty)
        DB-->>EX: ready=true (stock reserved)
        EX->>PAY: Prepare(order_id, amount)
        PAY-->>EX: ready=true (payment prepared)
    end
    
    Note over EX: Decision Log: PREPARED
    
    alt All participants ready
        par 2PC Phase 2: Commit (Execute)
            EX->>DB: Commit(order_id)
            DB-->>EX: committed (stock updated)
            EX->>PAY: Commit(order_id)
            PAY-->>EX: committed (payment executed)
        end
        Note over EX: Decision Log: COMMITTED
    else Timeout OR Prepare Failed
        par 2PC Phase 2: Abort (Rollback)
            EX->>DB: Abort(order_id)
            DB-->>EX: aborted (stock released)
            EX->>PAY: Abort(order_id)
            PAY-->>EX: aborted (payment cancelled)
        end
        Note over EX: Decision Log: ABORTED
    end
    end

    rect rgb(200, 255, 200)
    Note over ORC,SUG: Phase 5: Cleanup & Causal Consistency Validation
    ORC->>TV: ClearOrder(VCf) - only if local_VC ≤ VCf
    TV-->>ORC: success (state cleared)
    
    ORC->>FD: ClearOrder(VCf)
    FD-->>ORC: success (state cleared)
    
    ORC->>SUG: ClearOrder(VCf)
    SUG-->>ORC: success (state cleared)
    
    Note over ORC: All services acknowledge causal consistency
    end

    ORC-->>UI: status=Success + suggestions

```

### 2-Phase Commit Deep Dive
```mermaid
sequenceDiagram
    participant C as Client (Frontend/Orchestrator)
    participant Q as Order Queue
    participant E as Order Executor (Coordinator)
    participant DB as Books DB Primary (Participant A)
    participant P as Payment Service (Participant B)

    C->>Q: Enqueue approved order
    Q-->>E: Dequeue order

    Note over E: Phase 1 - Prepare
    E->>DB: Prepare(order_id, items)
    DB-->>E: ready / reject
    E->>P: Prepare(order_id, amount)
    P-->>E: ready / reject

    alt Any reject
        E->>DB: Abort(order_id)
        E->>P: Abort(order_id)
        E-->>C: Order failed
    else All ready
        Note over E: Phase 2 - Commit
        E->>DB: Commit(order_id)
        DB-->>E: success
        E->>P: Commit(order_id)
        P-->>E: success
        E-->>C: Order committed
    end
```
