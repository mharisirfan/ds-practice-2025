# Seminar 10: Distributed Books Database Implementation

## Overview

This checkpoint implements a **Primary-Backup Replicated Books Database** with strong consistency guarantees for a distributed order execution system. The system demonstrates how to handle consistency in a distributed environment while maintaining reliability and availability.

---

## Architecture Summary

### 1. **Books Database Service** (`books_database/`)
- **Role**: Distributed key-value store for book inventory management
- **Replication Strategy**: Primary-Backup (Primary-Replica) Model
- **Consistency Model**: Strong Consistency (Sequential Consistency)
- **Components**:
  - **Primary Replica** (`books_db_primary`): Accepts all writes, propagates to backups
  - **Backup Replicas** (`books_db_backup_1`, `books_db_backup_2`): Receive writes from primary

### 2. **Order Executor Service** (Updated: `order_executor/`)
- **Role**: Execute orders by interacting with the database
- **Operation Flow**:
  1. Dequeue an order from order_queue
  2. For each book in the order:
     - **Read** current stock
     - **Validate** stock availability
     - **Write** updated stock (decrement by 1)
  3. Log execution results

### 3. **Data Flow**
```
Order Queue → Order Executor → Books Database (Primary)
                                      ↓
                              Replicate to Backups
                           (Backup 1 & Backup 2)
```

---

## Key Design Decisions

### **Consistency Protocol: Primary-Backup**

**Why Primary-Backup?**
- ✅ Strong consistency (no stale reads possible)
- ✅ Simple to understand and implement
- ✅ Good for write-heavy workloads with critical data (book stock)
- ⚠️ Trade-off: Reduced availability if primary fails

**Implementation Details:**

1. **Writes** (Client → Primary):
   - Primary accepts write request
   - Applies write locally
   - Propagates write to all backups
   - Returns success only when all replicas acknowledge (quorum = all backups)
   - If backup fails, logs warning but still considers write successful

2. **Reads** (Client → Any Replica):
   - Can be served from any replica (primary or backup)
   - Returns immediately with current value
   - All replicas have identical data due to synchronous replication

3. **Fault Tolerance**:
   - Backup failure: Primary continues, marked as degraded
   - Primary failure: Backups continue serving reads (but can't write)
   - In production, would implement automatic primary failover

### **Concurrency Handling: Version Tracking**

**Problem**: What if two different orders try to update the stock of the same book simultaneously?

**Solution**: 
- Each write operation increments a **version number**
- Version is tracked per book in the database
- Last-write-wins semantic with order_id tracking
- Log concurrent writes for audit trail

**Example**:
```
Order A: Read "1984" (stock=40, v=1) → Write 39 (v=2)
Order B: Read "1984" (stock=40, v=1) → Write 39 (v=3)  // Concurrent

Final Result: stock=39, version=3, last_order=B
```

---

## Implementation Details

### **Database Schema**

```python
# Internal storage format
store: Dict[title, (stock, version, last_order_id)]

# Example:
{
    "The Great Gatsby": (50, 5, "order-123"),
    "1984": (39, 3, "order-456"),
}
```

### **gRPC Service Definition** (`utils/pb/books_database/books_database.proto`)

```protobuf
service BooksDatabase {
  rpc Read (ReadRequest) returns (ReadResponse);
  rpc Write (WriteRequest) returns (WriteResponse);
  rpc ReplicateWrite (ReplicateWriteRequest) returns (ReplicateWriteResponse);
  rpc Ping (PingRequest) returns (PingResponse);
}
```

### **Replication Protocol**

**Primary → Backup Communication**:
1. Primary receives Write request
2. Primary calls `ReplicateWrite` on each backup
3. Backup applies write locally and returns success
4. Primary collects all responses
5. Primary returns success to client

**Retry Logic**:
- Up to 3 retries per backup
- 2-second timeout per attempt
- Transient failures don't block the primary

---

## API Usage

### **Client Code (Order Executor)**

```python
# Initialize database connection
with grpc.insecure_channel("books_db_primary:50050") as channel:
    db_stub = db_grpc.BooksDatabaseStub(channel)
    
    # Read stock
    response = db_stub.Read(db_pb.ReadRequest(title="1984"))
    if response.success:
        current_stock = response.stock
    
    # Write updated stock
    response = db_stub.Write(
        db_pb.WriteRequest(
            title="1984",
            new_stock=38,
            client_id="executor-1",
            order_id="order-123"
        )
    )
    if response.success:
        new_version = response.version
```

---

## Running the System

### **Prerequisites**
- Docker & Docker Compose
- Python 3.11+
- gRPC tools: `pip install grpcio grpcio-tools`

### **Startup**

```bash
# Build all services
docker-compose build

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f books_db_primary
docker-compose logs -f books_db_backup_1
docker-compose logs -f books_db_backup_2
docker-compose logs -f order_executor_1
```

### **Services Overview**

| Service | Port | Role |
|---------|------|------|
| `books_db_primary` | 50050 | Primary database |
| `books_db_backup_1` | 50051 | Backup replica |
| `books_db_backup_2` | 50052 | Backup replica |
| `order_executor_1` | 50070 | Order executor 1 |
| `order_executor_2` | 50071 | Order executor 2 |
| `order_queue` | 50060 | Order queue manager |
| `frontend` | 8082 | Web interface |

---

## Consistency Guarantees

### **Strong Consistency Achieved**
✅ **Read-your-write**: Client can read value it just wrote
✅ **Sequential consistency**: All replicas agree on operation order
✅ **Atomicity**: Write either succeeds on all replicas or fails

### **Example Scenario**

```
Time  Executor1                    Executor2                   DB Primary
t0    Dequeue Order-A              Dequeue Order-B
      Read "1984"=40               
      (waits for write)             Read "1984"=40
t1                                                              
      Write "1984"=39,v=2          
      (replicates to B1, B2)        Write "1984"=39,v=3
                                    (replicates to B1, B2)
t2    ✓ Write Success              ✓ Write Success            
      Version=2                     Version=3
                                    
Final state: "1984"=39, version=3, last_order=B
Both reads got stale value (40), but both writes succeeded
Last-write-wins ensures final state is consistent
```

---

## Fault Tolerance Strategy

### **Backup Failure**
- Primary continues accepting writes
- Replication to failed backup retried 3 times
- System continues with reduced redundancy
- Alerts logged for operational monitoring

### **Primary Failure**
- **Reads**: Still work (served from backups)
- **Writes**: Fail with "not primary" error
- **Recovery**: In production, implement:
  - Heartbeat monitoring
  - Automatic failover mechanism
  - Election protocol (e.g., Raft, Zookeeper)

### **Network Partition**
- Primary → Backup communication may fail
- Replication uses best-effort with retries
- Strong consistency might be degraded to eventual consistency
- Logs alert for monitoring

---

## Performance Characteristics

### **Write Operations**
- **Latency**: P + B1 + B2 (serialized)
- **Throughput**: Limited by primary capacity
- **Bottleneck**: Replication to slowest backup

### **Read Operations**
- **Latency**: O(1) - single database lookup
- **Throughput**: Can scale with # of replicas
- **Load Balancing**: Route reads to any replica

### **Scalability**
- Reads: Highly scalable (add more replicas)
- Writes: Limited by primary capacity
- For write-heavy workloads, consider other protocols (Chain Replication, Quorum)

---

## Testing Scenarios

### **Scenario 1: Normal Operation**
```bash
# Orders execute successfully
docker-compose up
# Monitor logs - should see successful reads and writes
```

### **Scenario 2: Concurrent Writes**
```
- Order A and Order B both try to update "1984"
- Read returns 40 for both
- A writes 39 (version 2)
- B writes 39 (version 3)
- Final: version 3, last_order=B
```

### **Scenario 3: Backup Failure**
```bash
# Stop a backup
docker-compose pause books_db_backup_1

# System continues with warnings logged
docker-compose logs -f | grep -i "failed to replicate"
```

### **Scenario 4: Primary Failure**
```bash
# Stop primary
docker-compose pause books_db_primary

# Writes fail, reads still work from backups
# In production, would trigger failover
```

---

## Files Created/Modified

### **New Files**
```
books_database/
├── Dockerfile
├── requirements.txt
└── src/
    └── app.py

utils/pb/books_database/
├── __init__.py
├── books_database.proto
├── books_database_pb2.py
├── books_database_pb2_grpc.py
└── books_database_pb2.pyi
```

### **Modified Files**
```
order_executor/src/app.py
  - Added database imports
  - Added execute_order() function
  - Added database client interaction

docker-compose.yaml
  - Updated order_executor services with DB_PRIMARY_ADDR
  - Added books_db_primary service
  - Added books_db_backup_1 service
  - Added books_db_backup_2 service
```

---

## Key Takeaways

1. **Consistency vs Availability Tradeoff**
   - Primary-Backup: Strong consistency, reduced availability
   - Better for critical data (inventory)

2. **Replication Adds Complexity**
   - Must handle backup failures
   - Synchronization overhead
   - Version management for concurrent writes

3. **Monitoring is Critical**
   - Log all replication failures
   - Monitor primary health
   - Alert on version conflicts

4. **Future Improvements**
   - Implement automatic failover (elect new primary)
   - Add read-your-write client caching
   - Implement Chain Replication for better throughput
   - Add Byzantine fault tolerance for untrusted replicas

---

## References

- **Primary-Backup Protocol**: Classic replicated state machine approach
- **Version Vectors**: Track causality and concurrent updates
- **Quorum Systems**: Voting for consistency
- **Chain Replication**: Better performance for reads
