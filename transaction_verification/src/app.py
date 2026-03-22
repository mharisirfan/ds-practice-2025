import sys
import os
import grpc
from concurrent import futures
import logging
import re
import threading

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
transaction_verification_grpc_path = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/transaction_verification")
)
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2 as pb
import transaction_verification_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SERVICE_KEY = "transaction_verification"


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


class TransactionVerificationServicer(pb_grpc.TransactionVerificationServiceServicer):
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
                "credit_card": request.credit_card,
                "items": list(request.items),
            }
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "init")

        return pb.InitOrderResponse(
            success=True,
            message="Transaction order initialized",
            vector_clock=self._clock_msg(clock),
        )

    def VerifyItems(self, request, context):
        with self.lock:
            data = self.order_cache.get(request.order_id)
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "a_verify_items")

        if data is None:
            return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(clock))

        if not data["items"]:
            return pb.EventResponse(ok=False, message="Cart is empty", vector_clock=self._clock_msg(clock))

        return pb.EventResponse(ok=True, message="Items verified", vector_clock=self._clock_msg(clock))

    def VerifyUserData(self, request, context):
        with self.lock:
            data = self.order_cache.get(request.order_id)
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "b_verify_user_data")

        if data is None:
            return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(clock))

        user_id = data["user_id"].strip() if data["user_id"] else ""
        user_contact = data["user_contact"].strip() if data["user_contact"] else ""
        user_address = data["user_address"].strip() if data["user_address"] else ""
        if not user_id or not user_contact or not user_address:
            return pb.EventResponse(
                ok=False,
                message="Mandatory user data missing (name/contact/address)",
                vector_clock=self._clock_msg(clock),
            )

        return pb.EventResponse(ok=True, message="User data verified", vector_clock=self._clock_msg(clock))

    def VerifyCardFormat(self, request, context):
        with self.lock:
            data = self.order_cache.get(request.order_id)
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "c_verify_card_format")

        if data is None:
            return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(clock))

        if not re.match(r"^\d{16}$", data["credit_card"]):
            return pb.EventResponse(ok=False, message="Invalid credit card format", vector_clock=self._clock_msg(clock))

        return pb.EventResponse(ok=True, message="Credit card format verified", vector_clock=self._clock_msg(clock))

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
        return pb.ClearOrderResponse(
            success=True,
            message="Order state cleared",
            vector_clock=self._clock_msg(final_clock),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_TransactionVerificationServiceServicer_to_server(TransactionVerificationServicer(), server)
    server.add_insecure_port("[::]:50052")
    server.start()
    logger.info("Transaction Verification Service started on port 50052")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
