# Distributed Systems @ University of Tartu

This repository contains the initial code for the practice sessions of the Distributed Systems course at the University of Tartu.

## 📊 Vector Clock System Documentation

This system uses **Vector Clocks** to maintain causal ordering across microservices:

- **[Vector Clocks System Design](./VECTOR_CLOCKS_SYSTEM_DESIGN.md)** - Complete system architecture with vector clock flows and examples
- **[Vector Clock Detailed Trace](./VECTOR_CLOCK_DIAGRAM.md)** - Full timeline with all vector clock values at each step

### Quick Overview
The system processes orders through 6 events (a-f) across 3 services with proper vector clock synchronization:
```
Event A (verify items)  ──┐
Event B (verify user)   ──┼─→ Event E (merge) ──→ Event F (suggestions) ──→ Enqueue
Event C (card format)   ──┤                ↑
Event D (fraud check)   ──┘────────────────┘
```

## Getting started

### Overview

The code consists of multiple services. Each service is located in a separate folder. The `frontend` service folder contains a Dockerfile and the code for an example bookstore application. Each backend service folder (e.g. `orchestrator` or `fraud_detection`) contains a Dockerfile, a requirements.txt file and the source code of the service. During the practice sessions, you will implement the missing functionality in these backend services, or extend the backend with new services.

There is also a `utils` folder that contains some helper code or specifications that are used by multiple services. Check the `utils` folder for more information.

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



# Leader Election Diagram

```mermaid
sequenceDiagram
    participant E1 as Executor-1
    participant E2 as Executor-2
    participant Q as Order Queue (central authority)

    loop every POLL_SECONDS
        E1->>Q: TryAcquireLeadership(executor-1, lease_seconds)
        Q-->>E1: granted=true, leader_id=executor-1, lease_expiry
    end

    loop every POLL_SECONDS
        E2->>Q: TryAcquireLeadership(executor-2, lease_seconds)
        Q-->>E2: granted=false, leader_id=executor-1
    end

    E1->>Q: Dequeue(executor-1)
    Q-->>E1: success=true, has_order=true/false

    E2->>Q: Dequeue(executor-2)
    Q-->>E2: success=false (not active leader)

    Note over E1,Q: If E1 renews before expiry, leadership continues.
    Note over E1,E2: If E1 fails/stops renewing, lease expires.

    E2->>Q: TryAcquireLeadership(executor-2, lease_seconds)
    Q-->>E2: granted=true, leader_id=executor-2

    E2->>Q: Dequeue(executor-2)
    Q-->>E2: success=true
```

- requirements.txt dependencies from each service

frontend service:
- It's a simple static HTML page, you can open `frontend/src/index.html` in your browser.

And then run each service individually.
