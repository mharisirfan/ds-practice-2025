import sys
import os
import grpc
from concurrent import futures
import logging
import re
import threading

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as pb
import fraud_detection_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SERVICE_KEY = "fraud_detection"


def merge_clocks(*clocks):
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged


def clock_lte(local_clock, final_clock):
    keys = set(local_clock.keys()) | set(final_clock.keys())
    for key in keys:
        if local_clock.get(key, 0) > final_clock.get(key, 0):
            return False
    return True


class FraudDetectionService(pb_grpc.FraudDetectionServiceServicer):
    def __init__(self):
        self.order_cache = {}
        self.order_clocks = {}
        self.lock = threading.Lock()

    @staticmethod
    def _clock_msg(clock_dict):
        msg = pb.VectorClock()
        msg.clock.update(clock_dict)
        return msg

    def _merge_incoming(self, order_id, incoming_clock):
        current = self.order_clocks.get(order_id, {})
        merged = merge_clocks(current, incoming_clock)
        self.order_clocks[order_id] = merged
        return dict(merged)

    def _tick(self, order_id, event_name):
        clock = self.order_clocks.get(order_id, {})
        clock[SERVICE_KEY] = clock.get(SERVICE_KEY, 0) + 1
        self.order_clocks[order_id] = clock
        logger.info("Event %s | order_id=%s | VC=%s", event_name, order_id, clock)
        return dict(clock)

    def InitOrder(self, request, context):
        with self.lock:
            self.order_cache[request.order_id] = {
                "user_id": request.user_id,
                "user_contact": request.user_contact,
                "user_address": request.user_address,
                "card_number": request.card_number,
                "order_amount": request.order_amount,
            }
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "init")

        return pb.InitOrderResponse(success=True, message="Fraud order initialized", vector_clock=self._clock_msg(clock))

    def CheckUserFraud(self, request, context):
        with self.lock:
            data = self.order_cache.get(request.order_id)
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "d_check_user_fraud")

        if data is None:
            return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(clock))

        text = f"{data['user_id']} {data['user_contact']} {data['user_address']}".lower()
        if "fraud" in text or "scam" in text:
            return pb.EventResponse(ok=False, message="Suspicious user data detected", vector_clock=self._clock_msg(clock))

        return pb.EventResponse(ok=True, message="User fraud check passed", vector_clock=self._clock_msg(clock))

    def CheckCardFraud(self, request, context):
        with self.lock:
            data = self.order_cache.get(request.order_id)
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "e_check_card_fraud")

        if data is None:
            return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(clock))

        card = data["card_number"]
        amount_raw = data["order_amount"]

        if not re.match(r"^\d{16}$", card):
            return pb.EventResponse(ok=False, message="Fraud: invalid card format", vector_clock=self._clock_msg(clock))
        if card.startswith("1111"):
            return pb.EventResponse(ok=False, message="Fraud: suspicious card pattern", vector_clock=self._clock_msg(clock))

        try:
            amount = float(amount_raw)
        except ValueError:
            return pb.EventResponse(ok=False, message="Fraud: invalid order amount", vector_clock=self._clock_msg(clock))

        if amount > 10000 or amount < 0:
            return pb.EventResponse(ok=False, message="Fraud: suspicious order amount", vector_clock=self._clock_msg(clock))

        return pb.EventResponse(ok=True, message="Card fraud check passed", vector_clock=self._clock_msg(clock))

    def ClearOrder(self, request, context):
        with self.lock:
            local = self.order_clocks.get(request.order_id, {})
            final_clock = dict(request.final_vector_clock.clock)
            if not clock_lte(local, final_clock):
                logger.error("ClearOrder rejected | order_id=%s | local=%s | VCf=%s", request.order_id, local, final_clock)
                return pb.ClearOrderResponse(
                    success=False,
                    message="Local VC is greater than VCf; refusing to clear",
                    vector_clock=self._clock_msg(local),
                )

            self.order_cache.pop(request.order_id, None)
            self.order_clocks.pop(request.order_id, None)

        logger.info("ClearOrder success | order_id=%s | VCf=%s", request.order_id, final_clock)
        return pb.ClearOrderResponse(success=True, message="Order state cleared", vector_clock=self._clock_msg(final_clock))


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_FraudDetectionServiceServicer_to_server(FraudDetectionService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logger.info("Fraud Detection Service started on port 50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
