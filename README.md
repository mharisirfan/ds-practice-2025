# Distributed Systems 2026 @ University of Tartu

## Online Bookstore System 
A book ordering system built with microservices architecture demonstrating REST, gRPC, concurrent processing, and proper system documentation.

### Project Overview
This project implements a distributed book ordering system where users can submit orders that are processed through multiple backend services. The system showcases key distributed systems concepts including inter-service communication, concurrent processing, and comprehensive logging.

### System Architecture
```mermaid
graph TD
    subgraph "Frontend Layer"
        A[Web Browser] -->|REST API| B[Frontend Server<br/>Port: 8080]
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
### Microservices Details

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| **Fraud Detection** | 50051 | gRPC | Analyzes user data and credit card information to determine if a transaction is fraudulent using rule-based detection |
| **Transaction Verification** | 50052 | gRPC | Validates that user data is all filled in and credit card information is in the correct format |
| **Suggestions** | 50053 | gRPC | Randomly picks books from a book list to recommend to customers after successful checkout |
| **Executor** | 50070 | gRPC | Manages concurrent execution of service calls using thread pools, dispatches tasks to services, and aggregates results |

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
        
        Clear["Final Clear Broadcast<br/>VCf = (2,3,2,1,1)<br/>Clear sent to all services<br/>with final vector clock"]
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
graph TD
    classDef localState fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#000
    classDef rpcCall fill:#f3e5f5,stroke:#8e24aa,stroke-width:2px,color:#000
    classDef queueLogic fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000
    classDef action fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#000
    classDef err fill:#ffebee,stroke:#d32f2f,stroke-width:2px,color:#000

    Start((Start executor_loop))
    Acq[Call TryAcquireLeadership]
    Standby[State: 'standby'<br/>Sleep POLL_SECONDS]
    Leader[State: 'leader']
    ReqDeq[Call Dequeue]
    Lost[State: 'lost-leadership'<br/>Sleep POLL_SECONDS]
    Idle[State: 'leader' idle<br/>Sleep POLL_SECONDS]
    Exec[Log Execution<br/>Simulate Work 0.5s]
    Err[State: 'error'<br/>Sleep POLL_SECONDS]

    class Standby,Leader,Lost,Idle localState;
    class Acq,ReqDeq rpcCall;
    class Exec action;
    class Err err;

    Start --> Acq

    subgraph "Order Queue Service (Lease Management)"
        Q1{Is Lease Expired?<br/>OR<br/>Am I already the Leader?}
        Q2[Grant Lease<br/>Extend Expiry by 2s]
        Q3[Deny Lease<br/>Keep current Leader]
        
        class Q1,Q2,Q3 queueLogic;
        
        Acq --> Q1
        Q1 -->|Yes| Q2
        Q1 -->|No| Q3
    end

    Q3 -->|granted = False| Standby
    Q2 -->|granted = True| Leader
    
    Leader --> ReqDeq

    subgraph "Order Queue Service (Mutual Exclusion)"
        Q4{Is Requester still<br/>the Active Leader?}
        Q5[success = False]
        Q6{Is Queue Empty?}
        Q7[success = True<br/>has_order = False]
        Q8[success = True<br/>has_order = True<br/>Pop Order from Deque]
        
        class Q4,Q5,Q6,Q7,Q8 queueLogic;

        ReqDeq --> Q4
        Q4 -->|No| Q5
        Q4 -->|Yes| Q6
        Q6 -->|Yes| Q7
        Q6 -->|No| Q8
    end

    Q5 --> Lost
    Q7 --> Idle
    Q8 --> Exec

    Standby --> Acq
    Lost --> Acq
    Idle --> Acq
    Exec --> Acq

    Acq -.->|gRPC Exception| Err
    ReqDeq -.->|gRPC Exception| Err
    Err -.->|Recover & Retry| Acq
```
This flowchart maps the finite state machine of an order executor as it continuously loops to compete for and process queued orders. It visualizes a centralized, lease-based leader election algorithm managed by the order queue to enforce mutual exclusion: first validating whether the executor can acquire or renew a two-second leadership lease, and second, confirming the executor remains the active leader at the exact moment of dequeueing. This mechanism safely prevents multiple replicas from concurrently processing the same transaction.


---


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
