import sys
import os
import time
import grpc
import logging
import threading
from concurrent import futures

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

order_executor_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_executor"))
sys.path.insert(0, order_executor_grpc_path)
import order_executor_pb2 as ex_pb
import order_executor_pb2_grpc as ex_grpc

order_queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2 as q_pb
import order_queue_pb2_grpc as q_grpc

books_db_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/books_database"))
sys.path.insert(0, books_db_grpc_path)
import books_database_pb2 as db_pb
import books_database_pb2_grpc as db_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EXECUTOR_ID = os.getenv("EXECUTOR_ID", "executor-1")
QUEUE_ADDR = os.getenv("ORDER_QUEUE_ADDR", "order_queue:50060")
DB_PRIMARY_ADDR = os.getenv("DB_PRIMARY_ADDR", "books_db_primary:50050")
LEASE_SECONDS = int(os.getenv("LEASE_SECONDS", "2"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1.0"))
GRPC_PORT = int(os.getenv("EXECUTOR_PORT", "50070"))


class SharedState:
    def __init__(self):
        """Track executor leadership and status for health visibility."""
        self.leader_id = ""
        self.is_leader = False
        self.last_status = "starting"
        self.lock = threading.Lock()

    def update(self, leader_id, is_leader, status):
        """Update local status snapshot shared with Ping endpoint."""
        with self.lock:
            self.leader_id = leader_id
            self.is_leader = is_leader
            self.last_status = status

    def snapshot(self):
        """Read a consistent snapshot of executor status fields."""
        with self.lock:
            return self.leader_id, self.is_leader, self.last_status


STATE = SharedState()


class OrderExecutorService(ex_grpc.OrderExecutorServiceServicer):
    def Ping(self, request, context):
        """Report executor health and current leader information."""
        leader_id, is_leader, status = STATE.snapshot()
        return ex_pb.PingResponse(
            executor_id=EXECUTOR_ID,
            leader_id=leader_id,
            is_leader=is_leader,
            status=status,
        )


def execute_order(order, db_stub):
    """
    Execute an order by reading stock and writing updated values to the database.
    
    For each item in the order:
    1. Read current stock
    2. Validate stock availability
    3. Write updated stock
    """
    order_id = order.order_id
    user_id = order.user_id
    items = order.items
    
    logger.info("Executing order | order_id=%s | user_id=%s | items=%d", order_id, user_id, len(items))
    
    success_count = 0
    failure_count = 0
    
    for item in items:
        try:
            # Step 1: Read current stock
            read_response = db_stub.Read(db_pb.ReadRequest(title=item))
            
            if not read_response.success:
                logger.warning("Stock read failed | order_id=%s | item=%s | message=%s", 
                             order_id, item, read_response.message)
                failure_count += 1
                continue
            
            current_stock = read_response.stock
            logger.info("Stock read | order_id=%s | item=%s | current_stock=%d", 
                       order_id, item, current_stock)
            
            # Step 2: Validate stock availability
            if current_stock <= 0:
                logger.warning("Insufficient stock | order_id=%s | item=%s | available=%d", 
                             order_id, item, current_stock)
                failure_count += 1
                continue
            
            # Step 3: Write updated stock (decrement by 1 for this order)
            new_stock = current_stock - 1
            write_response = db_stub.Write(
                db_pb.WriteRequest(
                    title=item,
                    new_stock=new_stock,
                    client_id=EXECUTOR_ID,
                    order_id=order_id
                )
            )
            
            if write_response.success:
                logger.info("Stock updated | order_id=%s | item=%s | new_stock=%d | version=%d", 
                           order_id, item, new_stock, write_response.version)
                success_count += 1
            else:
                logger.warning("Stock write failed | order_id=%s | item=%s | message=%s", 
                             order_id, item, write_response.message)
                failure_count += 1
        
        except Exception as exc:
            logger.error("Error executing item | order_id=%s | item=%s | error=%s", 
                        order_id, item, str(exc))
            failure_count += 1
    
    if failure_count == 0 and success_count > 0:
        logger.info("Order execution completed successfully | order_id=%s | items_processed=%d", 
                   order_id, success_count)
    else:
        logger.warning("Order execution completed with issues | order_id=%s | success=%d | failures=%d", 
                      order_id, success_count, failure_count)


def executor_loop():
    """Continuously compete for leadership, dequeue, and execute at most one order at a time."""
    while True:
        try:
            with grpc.insecure_channel(QUEUE_ADDR) as channel:
                queue_stub = q_grpc.OrderQueueServiceStub(channel)
                election = queue_stub.TryAcquireLeadership(
                    q_pb.LeadershipRequest(executor_id=EXECUTOR_ID, lease_seconds=LEASE_SECONDS)
                )

                if not election.granted:
                    STATE.update(election.leader_id, False, "standby")
                    logger.info("Standby | leader=%s", election.leader_id)
                    time.sleep(POLL_SECONDS)
                    continue

                STATE.update(EXECUTOR_ID, True, "leader")
                logger.info("Leader active | executor=%s", EXECUTOR_ID)

                dequeue = queue_stub.Dequeue(
                    q_pb.DequeueRequest(executor_id=EXECUTOR_ID, vector_clock=q_pb.VectorClock())
                )
                if not dequeue.success:
                    STATE.update(election.leader_id, False, "lost-leadership")
                    logger.warning("Dequeue denied: %s", dequeue.message)
                    time.sleep(POLL_SECONDS)
                    continue

                if not dequeue.has_order:
                    logger.info("Leader idle | queue empty")
                    time.sleep(POLL_SECONDS)
                    continue

                order = dequeue.order
                logger.info(
                    "Order dequeued | executor=%s | order_id=%s | user=%s | items=%d",
                    EXECUTOR_ID,
                    order.order_id,
                    order.user_id,
                    len(order.items),
                )
                
                # Connect to primary database and execute order
                try:
                    with grpc.insecure_channel(DB_PRIMARY_ADDR) as db_channel:
                        db_stub = db_grpc.BooksDatabaseStub(db_channel)
                        execute_order(order, db_stub)
                except Exception as db_exc:
                    logger.error("Database connection error | order_id=%s | error=%s", 
                               order.order_id, str(db_exc))

        except Exception as exc:
            STATE.update("", False, "error")
            logger.error("Executor loop error: %s", exc)
            time.sleep(POLL_SECONDS)


def serve():
    """Start background executor worker and expose lightweight gRPC endpoint."""
    worker = threading.Thread(target=executor_loop, daemon=True)
    worker.start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    ex_grpc.add_OrderExecutorServiceServicer_to_server(OrderExecutorService(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    logger.info("Order Executor %s started on port %d", EXECUTOR_ID, GRPC_PORT)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
