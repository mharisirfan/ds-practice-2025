import sys
import os
import grpc
from concurrent import futures
import logging
import threading

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, queue_grpc_path)
import order_queue_pb2 as pb
import order_queue_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - Queue - %(message)s")
logger = logging.getLogger(__name__)

class OrderQueueService(pb_grpc.OrderQueueServiceServicer):
    def __init__(self):
        self.lock = threading.Lock()
        self.queue = []

    def Enqueue(self, request, context):
        with self.lock:
            self.queue.append(request.order_id)
            logger.info(f"Order {request.order_id} enqueued. Queue size: {len(self.queue)}")
        return pb.EnqueueResponse(success=True, message="Order queued")

    def Dequeue(self, request, context):
        with self.lock:
            if self.queue:
                order_id = self.queue.pop(0)
                logger.info(f"Order {order_id} dequeued. Queue size: {len(self.queue)}")
                return pb.DequeueResponse(success=True, order_id=order_id, message="Success")
            else:
                return pb.DequeueResponse(success=False, order_id="", message="Queue empty")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_OrderQueueServiceServicer_to_server(OrderQueueService(), server)
    server.add_insecure_port("[::]:50054")
    server.start()
    logger.info("Order Queue Service started on port 50054")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()