import sys
import os
import time
import grpc
import logging
import threading
from collections import deque
from concurrent import futures

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
order_queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2 as pb
import order_queue_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class OrderQueueService(pb_grpc.OrderQueueServiceServicer):
    def __init__(self):
        """Keep queued orders and centralized lease-based leader election state."""
        self._queue = deque()
        self._leader_id = ""
        self._leader_expiry = 0.0
        self._lock = threading.Lock()

    def _lease_valid(self):
        """Check whether the current leadership lease is still active."""
        return self._leader_id and time.time() < self._leader_expiry
    
    @staticmethod
    def _vc_compare_key(entry):
        """Return sortable key for vector clock (lexicographic order)."""
        vc = entry.get("vector_clock", {})
        # Convert to sorted tuple for consistent ordering
        return tuple(sorted((k, v) for k, v in vc.items()))

    def Enqueue(self, request, context):
        """Insert a verified order into the queue for executor processing."""
        order = request.order
        with self._lock:
            self._queue.append(
                {
                    "order_id": order.order_id,
                    "user_id": order.user_id,
                    "items": list(order.items),
                    "vector_clock": dict(order.vector_clock.clock),
                }
            )
            size = len(self._queue)

        logger.info("Enqueue success | order_id=%s | queue_size=%d", order.order_id, size)
        return pb.EnqueueResponse(success=True, message="Order enqueued")

    def TryAcquireLeadership(self, request, context):
        """Grant or renew leadership lease for one executor at a time."""
        now = time.time()
        lease_seconds = max(1, int(request.lease_seconds) if request.lease_seconds else 2)

        with self._lock:
            was_leader = self._leader_id == request.executor_id
            if not self._lease_valid() or self._leader_id == request.executor_id:
                self._leader_id = request.executor_id
                self._leader_expiry = now + lease_seconds
                granted = True
                message = "Leadership granted"
                log_leadership_change = not was_leader  # Log only if newly granted
            else:
                granted = False
                message = f"Leadership held by {self._leader_id}"
                log_leadership_change = False

            expiry_ms = int(self._leader_expiry * 1000)
            leader_id = self._leader_id

        # Only log significant leadership changes, not every renewal
        if log_leadership_change:
            logger.info("Leadership granted | executor=%s | leader=%s", request.executor_id, leader_id)
        
        return pb.LeadershipResponse(
            granted=granted,
            leader_id=leader_id,
            lease_expiry_unix_ms=expiry_ms,
            message=message,
        )

    def Dequeue(self, request, context):
        """Allow dequeue only to the active leader, enforcing mutual exclusion.
        Returns order with smallest vector clock (causal ordering)."""
        with self._lock:
            if not self._lease_valid() or self._leader_id != request.executor_id:
                return pb.DequeueResponse(success=False, has_order=False, message="Requester is not active leader")

            if not self._queue:
                return pb.DequeueResponse(success=True, has_order=False, message="Queue is empty")

            # VC-aware dequeue: find order with smallest VC (causal ordering)
            min_entry = min(self._queue, key=self._vc_compare_key)
            self._queue.remove(min_entry)
            entry = min_entry
            size = len(self._queue)

        order = pb.QueuedOrder(order_id=entry["order_id"], user_id=entry["user_id"], items=entry["items"])
        order.vector_clock.clock.update(entry["vector_clock"])

        logger.info("Dequeue success | leader=%s | order_id=%s | queue_size=%d | VC=%s", 
                    request.executor_id, entry["order_id"], size, entry["vector_clock"])
        return pb.DequeueResponse(success=True, has_order=True, message="Order dequeued", order=order)


def serve():
    """Start gRPC server for order queue service."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_OrderQueueServiceServicer_to_server(OrderQueueService(), server)
    server.add_insecure_port("[::]:50060")
    server.start()
    logger.info("Order Queue Service started on port 50060")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
