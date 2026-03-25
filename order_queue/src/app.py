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
        self._queue = deque()
        self._leader_id = ""
        self._leader_expiry = 0.0
        self._lock = threading.Lock()

    def _lease_valid(self):
        return self._leader_id and time.time() < self._leader_expiry

    def Enqueue(self, request, context):
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
        now = time.time()
        lease_seconds = max(1, int(request.lease_seconds) if request.lease_seconds else 2)

        with self._lock:
            if not self._lease_valid() or self._leader_id == request.executor_id:
                self._leader_id = request.executor_id
                self._leader_expiry = now + lease_seconds
                granted = True
                message = "Leadership granted"
            else:
                granted = False
                message = f"Leadership held by {self._leader_id}"

            expiry_ms = int(self._leader_expiry * 1000)
            leader_id = self._leader_id

        logger.info(
            "Leadership request | executor=%s | granted=%s | leader=%s | expiry_ms=%d",
            request.executor_id,
            granted,
            leader_id,
            expiry_ms,
        )
        return pb.LeadershipResponse(
            granted=granted,
            leader_id=leader_id,
            lease_expiry_unix_ms=expiry_ms,
            message=message,
        )

    def Dequeue(self, request, context):
        with self._lock:
            if not self._lease_valid() or self._leader_id != request.executor_id:
                return pb.DequeueResponse(success=False, has_order=False, message="Requester is not active leader")

            if not self._queue:
                return pb.DequeueResponse(success=True, has_order=False, message="Queue is empty")

            entry = self._queue.popleft()
            size = len(self._queue)

        order = pb.QueuedOrder(order_id=entry["order_id"], user_id=entry["user_id"], items=entry["items"])
        order.vector_clock.clock.update(entry["vector_clock"])

        logger.info("Dequeue success | leader=%s | order_id=%s | queue_size=%d", request.executor_id, entry["order_id"], size)
        return pb.DequeueResponse(success=True, has_order=True, message="Order dequeued", order=order)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_OrderQueueServiceServicer_to_server(OrderQueueService(), server)
    server.add_insecure_port("[::]:50060")
    server.start()
    logger.info("Order Queue Service started on port 50060")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
