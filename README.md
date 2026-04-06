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
        B -->|POST<br/>checkout| C[Order Orchestrator<br/>Flask: 5000]
    end    

    subgraph "Microservices Layer"
        C -->|gRPC| D[Fraud Detection<br/>Port: 50051]
        C -->|gRPC| E[Transaction Verification<br/>Port: 50052]
        C -->|gRPC| F[Suggestions<br/>Port: 50053]
    end

    subgraph "Execution Layer"
        C -->|gRPC: Enqueue| G[Order Queue Service<br/>Port: 50060]
        
        G <-->|gRPC: TryAcquireLeadership & Dequeue| H1[Order Executor 1<br/>Port: 50070]
        G <-->|gRPC: TryAcquireLeadership & Dequeue| H2[Order Executor 2<br/>Port: 50071]
        
        %% Represents the lease-based leader state held in the queue
        H1 -.->|Competes for Lease| H2
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
| **Fraud Detection** | 50051 | gRPC | Analyzes user data and credit card information to determine if a transaction is fraudulent using rule-based detection |
| **Transaction Verification** | 50052 | gRPC | Validates that user data is all filled in and credit card information is in the correct format |
| **Suggestions** | 50053 | gRPC | Randomly picks books from a book list to recommend to customers after successful checkout |
| **Order** | 50060 | gRPC | Handles order lifecycle, coordinates validation steps, and manages overall checkout flow |
| **Executor 1** | 50070 | gRPC | Executes tasks concurrently, dispatches service calls, and processes responses |
| **Executor 2** | 50071 | gRPC | Backup/parallel executor instance for load distribution and fault tolerance |

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
This sequence diagram illustrates how vector clocks track causality and asynchronous events across the microservices during a single checkout request. It highlights the Orchestrator branching out concurrent requests, how the Transaction Verification service sequentially merges and increments these incoming clocks to establish a strict mathematical order of operations, and how the final merged clock state is ultimately used to safely enqueue the order and clear the distributed caches.

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
Our leader-election mechanism is lease-based and dynamically supports N executors (N > 2), not just two fixed replicas. Any executor instance with a unique executor_id can compete for leadership by calling TryAcquireLeadership; the order_queue grants leadership to only one active lease holder at a time, so mutual exclusion is preserved for dequeue operations. The system is resilient to failures because if the current leader crashes or stops renewing, its lease expires and another executor automatically becomes leader on the next polling cycle. **This design is centralized**, which makes coordination simple and deterministic, but also introduces trade-offs: the queue service is a potential single point of failure and bottleneck compared to decentralized approaches. **Bonus Point**

## Bonus Points Implementation
- We implemented the bonus requirement in the orchestrator as the final step of every checkout flow, regardless of success or failure. After all worker-thread events complete (or fail), the orchestrator computes the final vector clock VCf (final_clock = tick_orchestrator(latest_clock)) and broadcasts a ClearOrder request to all relevant services (transaction_verification, fraud_detection, and suggestions) through broadcast_final_clear(...). Each service compares its local vector clock with the received VCf using a causal check (local VC <= VCf): if valid, it safely clears cached order state; if not, it refuses cleanup and returns an error. The orchestrator collects and logs any failed clear targets, so incorrect causal states are explicitly reported rather than silently ignored.

- Our leader-election mechanism is lease-based and dynamically supports N executors (N > 2), not just two fixed replicas. Any executor instance with a unique executor_id can compete for leadership by calling TryAcquireLeadership; the order_queue grants leadership to only one active lease holder at a time, so mutual exclusion is preserved for dequeue operations. The system is resilient to failures because if the current leader crashes or stops renewing, its lease expires and another executor automatically becomes leader on the next polling cycle. This design is centralized, which makes coordination simple and deterministic, but also introduces trade-offs: the queue service is a potential single point of failure and bottleneck compared to decentralized approaches.





---------------------------------------------------------------------------------






### Running the code with Docker Compose [recommended]

To run the code, you need to clone this repository, make sure you have Docker and Docker Compose installed, and run the following command in the root folder of the repository:

```bash
docker compose up
```

This will start the system with the multiple services. Each service will be restarted automatically when you make changes to the code, so you don't have to restart the system manually while developing. If you want to know how the services are started and configured, check the `docker-compose.yaml` file.

The checkpoint evaluations will be done using the code that is started with Docker Compose, so make sure that your code works with Docker Compose.

If, for some reason, changes to the code are not reflected, try to force rebuilding the Docker images with the following command:

```bash
docker compose up --build
```

### Run the code locally

Even though you can run the code locally, it is recommended to use Docker and Docker Compose to run the code. This way you don't have to install any dependencies locally and you can easily run the code on any platform.

If you want to run the code locally, you need to install the following dependencies:

backend services:
- Python 3.8 or newer
- pip
- [grpcio-tools](https://grpc.io/docs/languages/python/quickstart/)
- requirements.txt dependencies from each service

frontend service:
- It's a simple static HTML page, you can open `frontend/src/index.html` in your browser.

And then run each service individually.
