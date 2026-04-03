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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EXECUTOR_ID = os.getenv("EXECUTOR_ID", "executor-1")
QUEUE_ADDR = os.getenv("ORDER_QUEUE_ADDR", "order_queue:50060")
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
                    "Order is being executed... | executor=%s | order_id=%s | user=%s | items=%d",
                    EXECUTOR_ID,
                    order.order_id,
                    order.user_id,
                    len(order.items),
                )
                # Simulate critical section execution.
                time.sleep(0.5)

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
