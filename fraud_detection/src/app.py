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
EVENT_MARKERS = {
    "b": "evt_b_done",
    "c": "evt_c_done",
    "d": "evt_d_done",
    "e": "evt_e_done",
}


def merge_clocks(*clocks):
    """Merge vector clocks by taking the component-wise maximum."""
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged


def clock_lte(local_clock, final_clock):
    """Return True when local clock is less than or equal to VCf for all keys."""
    keys = set(local_clock.keys()) | set(final_clock.keys())
    for key in keys:
        if local_clock.get(key, 0) > final_clock.get(key, 0):
            return False
    return True


class FraudDetectionService(pb_grpc.FraudDetectionServiceServicer):
    def __init__(self):
        """Store per-order cached payload and per-order vector clock state."""
        self.order_cache = {}
        self.order_clocks = {}
        self.order_events = {}
        self.lock = threading.Lock()

    @staticmethod
    def _clock_msg(clock_dict):
        """Convert dictionary clock into protobuf vector clock message."""
        msg = pb.VectorClock()
        msg.clock.update(clock_dict)
        return msg

    def _merge_incoming(self, order_id, incoming_clock):
        """Merge incoming clock with local order clock before processing an event."""
        current = self.order_clocks.get(order_id, {})
        merged = merge_clocks(current, incoming_clock)
        self.order_clocks[order_id] = merged
        return dict(merged)

    def _tick(self, order_id, event_name):
        """Advance local service component for the current order event and log it."""
        clock = self.order_clocks.get(order_id, {})
        clock[SERVICE_KEY] = clock.get(SERVICE_KEY, 0) + 1
        self.order_clocks[order_id] = clock
        logger.info("Event %s | order_id=%s | VC=%s", event_name, order_id, clock)
        return dict(clock)

    def _causal_violation(self, order_id, event_name, reason, clock):
        """Build a consistent causal-violation response and log it."""
        logger.warning("Causal violation | event=%s | order_id=%s | reason=%s | VC=%s", event_name, order_id, reason, clock)
        return pb.EventResponse(
            ok=False,
            message=f"Causal violation: {reason}",
            vector_clock=self._clock_msg(clock),
        )

    def InitOrder(self, request, context):
        """Cache order input and initialize vector-clock tracking for this service."""
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
            self.order_events[request.order_id] = {"done": {"init"}}

        return pb.InitOrderResponse(success=True, message="Fraud order initialized", vector_clock=self._clock_msg(clock))

    def CheckUserFraud(self, request, context):
        """Event d: run user-level fraud checks after user-data validation path."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            has_b_vc = merged.get(EVENT_MARKERS["b"], 0) >= 1
            if not has_b_vc:
                return self._causal_violation(
                    request.order_id,
                    "d_check_user_fraud",
                    "event d requires completed event b",
                    merged,
                )

            if "d" in state["done"]:
                return self._causal_violation(request.order_id, "d_check_user_fraud", "event d already executed", merged)

            clock = self._tick(request.order_id, "d_check_user_fraud")

        text = f"{data['user_id']} {data['user_contact']} {data['user_address']}".lower()
        if "fraud" in text or "scam" in text:
            return pb.EventResponse(ok=False, message="Suspicious user data detected", vector_clock=self._clock_msg(clock))

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("d")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["d"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        return pb.EventResponse(ok=True, message="User fraud check passed", vector_clock=self._clock_msg(out))

    def CheckCardFraud(self, request, context):
        """Event e: run card-level fraud checks after c and d dependencies."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            has_c_vc = merged.get(EVENT_MARKERS["c"], 0) >= 1
            has_d_local = "d" in state["done"]
            has_d_vc = merged.get(EVENT_MARKERS["d"], 0) >= 1
            if not (has_c_vc and has_d_local and has_d_vc):
                return self._causal_violation(
                    request.order_id,
                    "e_check_card_fraud",
                    "event e requires completed events c and d",
                    merged,
                )

            if "e" in state["done"]:
                return self._causal_violation(request.order_id, "e_check_card_fraud", "event e already executed", merged)

            clock = self._tick(request.order_id, "e_check_card_fraud")

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

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("e")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["e"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        return pb.EventResponse(ok=True, message="Card fraud check passed", vector_clock=self._clock_msg(out))

    def ClearOrder(self, request, context):
        """Clear cached order state only when local VC is causally <= VCf."""
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
            self.order_events.pop(request.order_id, None)

        logger.info("ClearOrder success | order_id=%s | VCf=%s", request.order_id, final_clock)
        return pb.ClearOrderResponse(success=True, message="Order state cleared", vector_clock=self._clock_msg(final_clock))


def serve():
    """Start gRPC server for fraud detection service."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_FraudDetectionServiceServicer_to_server(FraudDetectionService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logger.info("Fraud Detection Service started on port 50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
