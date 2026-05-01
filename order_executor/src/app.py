import sys
import os
import time
import grpc
import logging
import threading
import random
from concurrent import futures

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

# --- Existing gRPC Paths ---
order_executor_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_executor"))
sys.path.insert(0, order_executor_grpc_path)
import order_executor_pb2 as ex_pb
import order_executor_pb2_grpc as ex_grpc

order_queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2 as q_pb
import order_queue_pb2_grpc as q_grpc

# --- NEW: Database gRPC Path ---
books_database_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/books_database"))
sys.path.insert(0, books_database_grpc_path)
import books_database_pb2 as db_pb
import books_database_pb2_grpc as db_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EXECUTOR_ID = os.getenv("EXECUTOR_ID", "executor-1")
QUEUE_ADDR = os.getenv("ORDER_QUEUE_ADDR", "order_queue:50060")
# NEW: Address for the primary database replica
DB_PRIMARY_ADDR = os.getenv("DB_PRIMARY_ADDR", "books_database_primary:50054") 
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


def execute_order_item_with_retry(db_stub, title, quantity=1, max_retries=3):
    """Executes the order item with optimistic concurrency control (retries)."""
    for attempt in range(max_retries):
        # Step 1: Read current stock
        try:
            read_res = db_stub.Read(db_pb.ReadRequest(title=title), timeout=2.0)
            current_stock = read_res.stock
        except grpc.RpcError as e:
            logger.error("Database Read failed for '%s': %s", title, e.details())
            return False

        # Step 2: Check availability
        if current_stock < quantity:
            logger.warning("Not enough stock for '%s' (Current: %d, Required: %d)", title, current_stock, quantity)
            return False

        # Step 3: Attempt to Write (Compare-And-Swap)
        new_stock = current_stock - quantity
        try:
            write_res = db_stub.Write(db_pb.WriteRequest(
                title=title, 
                new_stock=new_stock, 
                expected_stock=current_stock, 
                is_replica_sync=False
            ), timeout=2.0)
            
            if write_res.success:
                logger.info("Stock updated successfully for '%s'. New stock: %d", title, new_stock)
                return True
            else:
                # Concurrent write detected! Back off and retry.
                logger.warning("Contention on '%s', retrying (%d/%d)...", title, attempt + 1, max_retries)
                time.sleep(random.uniform(0.1, 0.5))
                
        except grpc.RpcError as e:
            logger.error("Database Write failed for '%s': %s", title, e.details())
            return False

    logger.error("Failed to update stock for '%s' after %d attempts due to high contention.", title, max_retries)
    return False


def executor_loop():
    """Continuously compete for leadership, dequeue, and execute at most one order at a time."""
    # We maintain a single channel to the DB Primary to reuse connection state
    db_channel = grpc.insecure_channel(DB_PRIMARY_ADDR)
    db_stub = db_grpc.BooksDatabaseStub(db_channel)

    while True:
        try:
            with grpc.insecure_channel(QUEUE_ADDR) as channel:
                # Wait gracefully for the queue to come online if it's booting
                grpc.channel_ready_future(channel).result(timeout=5)
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
                    "Executing order... | executor=%s | order_id=%s | items=%d",
                    EXECUTOR_ID, order.order_id, len(order.items)
                )
                
                all_items_successful = True
                for item_title in order.items:
                    # Assuming each item in the list represents 1 quantity of that book
                    success = execute_order_item_with_retry(db_stub, title=item_title, quantity=1)
                    if not success:
                        all_items_successful = False
                        # In a real system, you might trigger a rollback or compensation transaction here
                        logger.error("Order %s failed on item '%s'.", order.order_id, item_title)
                        break 
                
                if all_items_successful:
                    logger.info("Order %s fully executed and stock updated.", order.order_id)

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