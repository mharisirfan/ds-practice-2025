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

fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_pb
import fraud_detection_pb2_grpc as fraud_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SERVICE_KEY = "transaction_verification"
SUGGESTED_BOOKS_METADATA_KEY = "suggested-books"
EVENT_MARKERS = {
    "a": "evt_a_done",
    "b": "evt_b_done",
    "c": "evt_c_done",
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


class TransactionVerificationServicer(pb_grpc.TransactionVerificationServiceServicer):
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

    @staticmethod
    def _fraud_clock_msg(clock_dict):
        """Convert dictionary clock into fraud-detection protobuf vector clock message."""
        msg = fraud_pb.VectorClock()
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
                "credit_card": request.credit_card,
                "items": list(request.items),
            }
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "init")
            self.order_events[request.order_id] = {"done": {"init"}}

        return pb.InitOrderResponse(
            success=True,
            message="Transaction order initialized",
            vector_clock=self._clock_msg(clock),
        )

    def StartVerificationFlow(self, request, context):
        """Start backend-owned event ordering and service-to-service clock propagation."""
        with self.lock:
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            parent_clock = self._tick(request.order_id, "start_verification_flow")

        failure = {"message": None}

        def run_items_branch():
            try:
                logger.info(
                    "LOCAL DISPATCH transaction_verification -> transaction_verification | branch=items | event=a_verify_items | order_id=%s | VC=%s",
                    request.order_id,
                    parent_clock,
                )
                with grpc.insecure_channel("localhost:50052") as channel:
                    stub = pb_grpc.TransactionVerificationServiceStub(channel)
                    event_a = stub.VerifyItems(
                        pb.EventRequest(order_id=request.order_id, vector_clock=self._clock_msg(parent_clock))
                    )
                    if not event_a.ok:
                        failure["message"] = event_a.message
                        return False, dict(event_a.vector_clock.clock)

                    logger.info(
                        "LOCAL DISPATCH transaction_verification -> transaction_verification | branch=items | event=c_verify_card_format | order_id=%s | VC=%s",
                        request.order_id,
                        dict(event_a.vector_clock.clock),
                    )
                    event_c = stub.VerifyCardFormat(
                        pb.EventRequest(order_id=request.order_id, vector_clock=event_a.vector_clock)
                    )
                    if not event_c.ok:
                        failure["message"] = event_c.message
                        return False, dict(event_c.vector_clock.clock)

                    return True, dict(event_c.vector_clock.clock)
            except Exception as exc:
                failure["message"] = str(exc)
                return False, parent_clock

        def run_user_branch():
            try:
                logger.info(
                    "LOCAL DISPATCH transaction_verification -> transaction_verification | branch=user | event=b_verify_user_data | order_id=%s | VC=%s",
                    request.order_id,
                    parent_clock,
                )
                with grpc.insecure_channel("localhost:50052") as channel:
                    stub = pb_grpc.TransactionVerificationServiceStub(channel)
                    event_b = stub.VerifyUserData(
                        pb.EventRequest(order_id=request.order_id, vector_clock=self._clock_msg(parent_clock))
                    )
                    if not event_b.ok:
                        failure["message"] = event_b.message
                        return False, dict(event_b.vector_clock.clock)

                logger.info(
                    "HANDOFF transaction_verification -> fraud_detection | event=d_check_user_fraud | order_id=%s | VC=%s",
                    request.order_id,
                    dict(event_b.vector_clock.clock),
                )
                with grpc.insecure_channel("fraud_detection:50051") as channel:
                    stub = fraud_grpc.FraudDetectionServiceStub(channel)
                    event_d = stub.CheckUserFraud(
                        fraud_pb.EventRequest(
                            order_id=request.order_id,
                            vector_clock=self._fraud_clock_msg(dict(event_b.vector_clock.clock)),
                        )
                    )
                    if not event_d.ok:
                        failure["message"] = event_d.message
                        return False, dict(event_d.vector_clock.clock)

                    return True, dict(event_d.vector_clock.clock)
            except Exception as exc:
                failure["message"] = str(exc)
                return False, parent_clock

        with futures.ThreadPoolExecutor(max_workers=2) as pool:
            items_future = pool.submit(run_items_branch)
            user_future = pool.submit(run_user_branch)
            items_ok, clock_c = items_future.result(timeout=10)
            user_ok, clock_d = user_future.result(timeout=10)

        if not (items_ok and user_ok):
            merged_clock = merge_clocks(merged, clock_c, clock_d)
            with self.lock:
                self.order_clocks[request.order_id] = merged_clock
            context.set_trailing_metadata(((SUGGESTED_BOOKS_METADATA_KEY, "[]"),))
            return pb.EventResponse(
                ok=False,
                message=failure["message"] or "Verification flow failed",
                vector_clock=self._clock_msg(merged_clock),
            )

        with self.lock:
            join_clock = merge_clocks(self.order_clocks.get(request.order_id, {}), clock_c, clock_d)
            self.order_clocks[request.order_id] = join_clock
            join_clock = self._tick(request.order_id, "join_c_d_before_fraud")

        try:
            logger.info(
                "HANDOFF transaction_verification -> fraud_detection | event=e_check_card_fraud | order_id=%s | VC=%s",
                request.order_id,
                join_clock,
            )
            with grpc.insecure_channel("fraud_detection:50051") as channel:
                stub = fraud_grpc.FraudDetectionServiceStub(channel)
                event_e, call = stub.CheckCardFraud.with_call(
                    fraud_pb.EventRequest(
                        order_id=request.order_id,
                        vector_clock=self._fraud_clock_msg(join_clock),
                    )
                )

            books_payload = "[]"
            for key, value in call.trailing_metadata() or []:
                if key == SUGGESTED_BOOKS_METADATA_KEY:
                    books_payload = value
                    break

            out_clock = merge_clocks(join_clock, dict(event_e.vector_clock.clock))
            with self.lock:
                self.order_clocks[request.order_id] = out_clock

            logger.info(
                "RETURN fraud_detection -> transaction_verification | event=e_check_card_fraud | order_id=%s | ok=%s | VC=%s",
                request.order_id,
                event_e.ok,
                out_clock,
            )
            context.set_trailing_metadata(((SUGGESTED_BOOKS_METADATA_KEY, books_payload),))
            return pb.EventResponse(
                ok=event_e.ok,
                message=event_e.message,
                vector_clock=self._clock_msg(out_clock),
            )
        except Exception as exc:
            context.set_trailing_metadata(((SUGGESTED_BOOKS_METADATA_KEY, "[]"),))
            return pb.EventResponse(
                ok=False,
                message=str(exc),
                vector_clock=self._clock_msg(join_clock),
            )

    def VerifyItems(self, request, context):
        """Event a: verify the order contains at least one item."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            if "a" in state["done"]:
                return self._causal_violation(request.order_id, "a_verify_items", "event a already executed", merged)

            clock = self._tick(request.order_id, "a_verify_items")

        if not data["items"]:
            return pb.EventResponse(ok=False, message="Cart is empty", vector_clock=self._clock_msg(clock))

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("a")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["a"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        return pb.EventResponse(ok=True, message="Items verified", vector_clock=self._clock_msg(out))

    def VerifyUserData(self, request, context):
        """Event b: verify required user information fields are present."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            if "b" in state["done"]:
                return self._causal_violation(request.order_id, "b_verify_user_data", "event b already executed", merged)

            clock = self._tick(request.order_id, "b_verify_user_data")

        user_id = data["user_id"].strip() if data["user_id"] else ""
        user_contact = data["user_contact"].strip() if data["user_contact"] else ""
        user_address = data["user_address"].strip() if data["user_address"] else ""
        if not user_id or not user_contact or not user_address:
            return pb.EventResponse(
                ok=False,
                message="Mandatory user data missing (name/contact/address)",
                vector_clock=self._clock_msg(clock),
            )

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("b")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["b"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        return pb.EventResponse(ok=True, message="User data verified", vector_clock=self._clock_msg(out))

    def VerifyCardFormat(self, request, context):
        """Event c: verify card format after upstream dependency is satisfied."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.EventResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            has_a_local = "a" in state["done"]
            has_a_vc = merged.get(EVENT_MARKERS["a"], 0) >= 1
            if not (has_a_local and has_a_vc):
                return self._causal_violation(
                    request.order_id,
                    "c_verify_card_format",
                    "event c requires completed event a",
                    merged,
                )

            if "c" in state["done"]:
                return self._causal_violation(request.order_id, "c_verify_card_format", "event c already executed", merged)

            clock = self._tick(request.order_id, "c_verify_card_format")

        if not re.match(r"^\d{16}$", data["credit_card"]):
            return pb.EventResponse(ok=False, message="Invalid credit card format", vector_clock=self._clock_msg(clock))

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("c")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["c"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        return pb.EventResponse(ok=True, message="Credit card format verified", vector_clock=self._clock_msg(out))

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
        return pb.ClearOrderResponse(
            success=True,
            message="Order state cleared",
            vector_clock=self._clock_msg(final_clock),
        )


def serve():
    """Start gRPC server for transaction verification service."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_TransactionVerificationServiceServicer_to_server(TransactionVerificationServicer(), server)
    server.add_insecure_port("[::]:50052")
    server.start()
    logger.info("Transaction Verification Service started on port 50052")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
