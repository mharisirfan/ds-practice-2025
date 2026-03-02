# Distributed Systems 2026 @ University of Tartu

## Online Bookstore System 
A book ordering system built with microservices architecture demonstrating REST, gRPC, concurrent processing, and proper system documentation.

🎯 Project Overview
This project implements a distributed book ordering system where users can submit orders that are processed through multiple backend services. The system showcases key distributed systems concepts including inter-service communication, concurrent processing, and comprehensive logging.

### System Architecture
graph TD
    subgraph "Client Layer"
        A[Web Browser] --> B[Frontend Server<br/>Port: 3000<br/>Node.js/Express]
    end
    
    subgraph "Orchestration Layer"
        B -->|REST API| C[Order Orchestrator<br/>Port: 5000<br/>Python/Flask]
    end
    
    subgraph "Processing Layer"
        C -->|gRPC| D[Inventory Service<br/>Port: 50051]
        C -->|gRPC| E[Payment Processor<br/>Port: 50052]
        C -->|gRPC| F[Shipping Calculator<br/>Port: 50053]
    end
    
    subgraph "Data Layer"
        D --> G[(Inventory DB<br/>SQLite)]
        E --> H[(Transactions DB<br/>SQLite)]
        F --> I[(Shipping Rates<br/>JSON)]
    end
The architecture follows a layered approach with clear separation of concerns. The frontend communicates with the orchestrator via REST, which then coordinates three gRPC services concurrently.











///////


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
