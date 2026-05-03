import sys
import os
import time
import json
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

payment_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/payment"))
sys.path.insert(0, payment_grpc_path)
import payment_pb2 as pay_pb
import payment_pb2_grpc as pay_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EXECUTOR_ID = os.getenv("EXECUTOR_ID", "executor-1")
QUEUE_ADDR = os.getenv("ORDER_QUEUE_ADDR", "order_queue:50060")
# NEW: Address for the primary database replica
DB_PRIMARY_ADDR = os.getenv("DB_PRIMARY_ADDR", "books_database_primary:50054") 
PAYMENT_ADDR = os.getenv("PAYMENT_ADDR", "payment_system:50055")
LEASE_SECONDS = int(os.getenv("LEASE_SECONDS", "2"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1.0"))
GRPC_PORT = int(os.getenv("EXECUTOR_PORT", "50070"))
RPC_TIMEOUT_SECONDS = float(os.getenv("RPC_TIMEOUT_SECONDS", "2.0"))
DECISION_LOG_FILE = os.getenv("EXECUTOR_DECISION_LOG", "/tmp/executor_decisions.json")
COMMIT_DELAY_SECONDS = float(os.getenv("EXECUTOR_COMMIT_DELAY", "0"))


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


class DecisionLog:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.decisions = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self):
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self.decisions, handle)
        os.replace(tmp_path, self.path)

    def record(self, order_id, decision, completed=False):
        with self.lock:
            self.decisions[order_id] = {
                "decision": decision,
                "completed": completed,
                "updated_at": time.time(),
            }
            self._save()

    def mark_completed(self, order_id):
        with self.lock:
            current = self.decisions.get(order_id)
            if not current:
                return
            current["completed"] = True
            current["updated_at"] = time.time()
            self.decisions[order_id] = current
            self._save()

    def pending_commits(self):
        with self.lock:
            return [
                order_id
                for order_id, entry in self.decisions.items()
                if entry.get("decision") == "commit" and not entry.get("completed")
            ]


DECISION_LOG = DecisionLog(DECISION_LOG_FILE)


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


def abort_prepared_participants(order_id, db_stub, payment_stub):
    """Best-effort abort for participants that may have prepared transaction state."""
    try:
        db_stub.Abort(db_pb.AbortRequest(order_id=order_id), timeout=RPC_TIMEOUT_SECONDS)
    except grpc.RpcError as exc:
        logger.error("Database abort failed | order_id=%s | error=%s", order_id, exc.details())

    try:
        payment_stub.Abort(pay_pb.AbortRequest(order_id=order_id), timeout=RPC_TIMEOUT_SECONDS)
    except grpc.RpcError as exc:
        logger.error("Payment abort failed | order_id=%s | error=%s", order_id, exc.details())


def commit_participants_with_retry(order_id, db_stub, payment_stub, max_retries=5):
    """Commit prepared participants; retries reduce the blocking window after a commit decision."""
    participants = {
        "database": lambda: db_stub.Commit(db_pb.CommitRequest(order_id=order_id), timeout=RPC_TIMEOUT_SECONDS).success,
        "payment": lambda: payment_stub.Commit(pay_pb.CommitRequest(order_id=order_id), timeout=RPC_TIMEOUT_SECONDS).success,
    }
    committed = set()

    for attempt in range(1, max_retries + 1):
        for name, commit_call in participants.items():
            if name in committed:
                continue
            try:
                if commit_call():
                    committed.add(name)
                    logger.info("2PC commit ack | order_id=%s | participant=%s", order_id, name)
                else:
                    logger.warning("2PC commit rejected | order_id=%s | participant=%s", order_id, name)
            except grpc.RpcError as exc:
                logger.error("2PC commit RPC failed | order_id=%s | participant=%s | error=%s", order_id, name, exc)

        if len(committed) == len(participants):
            return True

        time.sleep(min(0.25 * attempt, 1.0))

    missing = sorted(set(participants) - committed)
    logger.error("2PC commit incomplete | order_id=%s | missing=%s", order_id, missing)
    return False


def execute_order_with_2pc(order, db_stub, payment_stub):
    """Coordinate a two-phase commit between the books database and payment service."""
    order_id = order.order_id
    items = list(order.items)
    amount = len(items)

    try:
        db_prepare = db_stub.Prepare(
            db_pb.PrepareRequest(order_id=order_id, items=items),
            timeout=RPC_TIMEOUT_SECONDS,
        )
        if not db_prepare.ready:
            logger.warning("2PC database prepare rejected | order_id=%s | message=%s", order_id, db_prepare.message)
            DECISION_LOG.record(order_id, "abort", completed=True)
            abort_prepared_participants(order_id, db_stub, payment_stub)
            return False

        payment_prepare = payment_stub.Prepare(
            pay_pb.PrepareRequest(order_id=order_id, amount=amount),
            timeout=RPC_TIMEOUT_SECONDS,
        )
        if not payment_prepare.ready:
            logger.warning("2PC payment prepare rejected | order_id=%s | message=%s", order_id, payment_prepare.message)
            DECISION_LOG.record(order_id, "abort", completed=True)
            abort_prepared_participants(order_id, db_stub, payment_stub)
            return False

    except grpc.RpcError as exc:
        logger.error("2PC prepare RPC failed | order_id=%s | error=%s", order_id, exc)
        DECISION_LOG.record(order_id, "abort", completed=True)
        abort_prepared_participants(order_id, db_stub, payment_stub)
        return False

    DECISION_LOG.record(order_id, "commit", completed=False)
    if COMMIT_DELAY_SECONDS > 0:
        logger.info("2PC commit delay | order_id=%s | delay=%.2fs", order_id, COMMIT_DELAY_SECONDS)
        time.sleep(COMMIT_DELAY_SECONDS)
    committed = commit_participants_with_retry(order_id, db_stub, payment_stub)
    if committed:
        DECISION_LOG.mark_completed(order_id)
        logger.info("2PC committed | order_id=%s | participants=database,payment", order_id)
    return committed


def executor_loop():
    """Continuously compete for leadership, dequeue, and execute at most one order at a time."""
    # We maintain a single channel to the DB Primary to reuse connection state
    db_channel = grpc.insecure_channel(DB_PRIMARY_ADDR)
    db_stub = db_grpc.BooksDatabaseStub(db_channel)
    payment_channel = grpc.insecure_channel(PAYMENT_ADDR)
    payment_stub = pay_grpc.PaymentServiceStub(payment_channel)

    for order_id in DECISION_LOG.pending_commits():
        logger.warning("Recovering pending commit | order_id=%s", order_id)
        if commit_participants_with_retry(order_id, db_stub, payment_stub):
            DECISION_LOG.mark_completed(order_id)

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
                
                if execute_order_with_2pc(order, db_stub, payment_stub):
                    logger.info("Order %s fully executed: stock updated and payment committed.", order.order_id)
                else:
                    logger.error("Order %s failed during two-phase commit.", order.order_id)

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
