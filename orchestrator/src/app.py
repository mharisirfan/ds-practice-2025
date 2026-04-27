import sys
import os
import json
import logging
import socket
import time
import uuid
import threading
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, as_completed, wait

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/fraud_detection"))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_pb
import fraud_detection_pb2_grpc as fraud_grpc

transaction_verification_grpc_path = os.path.abspath(
    os.path.join(FILE, "../../../utils/pb/transaction_verification")
)
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2 as tv_pb
import transaction_verification_pb2_grpc as tv_grpc

suggestions_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/suggestions"))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2 as sug_pb
import suggestions_pb2_grpc as sug_grpc

order_queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, order_queue_grpc_path)
import order_queue_pb2 as oq_pb
import order_queue_pb2_grpc as oq_grpc

import grpc
from flask import Flask, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ORCH_KEY = "orchestrator"
CLEAR_RETRY_ATTEMPTS = 3
CLEAR_RETRY_BACKOFF_SEC = 0.3

CLEAR_SERVICES = {
    "transaction_verification": {
        "host": "transaction_verification",
        "port": 50052,
    },
    "fraud_detection": {
        "host": "fraud_detection",
        "port": 50051,
    },
    "suggestions": {
        "host": "suggestions",
        "port": 50053,
    },
}


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


def merge_clocks(*clocks):
    """Merge multiple vector clocks by taking the maximum value per process key."""
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged


def tick_orchestrator(clock):
    """Advance the orchestrator component in a vector clock before dispatching a new event."""
    updated = dict(clock)
    updated[ORCH_KEY] = updated.get(ORCH_KEY, 0) + 1
    return updated


def to_tv_clock(clock):
    """Convert a Python dict clock into transaction-verification protobuf format."""
    msg = tv_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def to_fraud_clock(clock):
    """Convert a Python dict clock into fraud-detection protobuf format."""
    msg = fraud_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def to_sug_clock(clock):
    """Convert a Python dict clock into suggestions protobuf format."""
    msg = sug_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def to_oq_clock(clock):
    """Convert a Python dict clock into order-queue protobuf format."""
    msg = oq_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def rpc_init_transaction(order_id, user_id, contact, address, credit_card, items, clock):
    """Initialize order cache and initial clock state in transaction-verification service."""
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.InitOrder(
            tv_pb.InitOrderRequest(
                order_id=order_id,
                user_id=user_id,
                user_contact=contact,
                user_address=address,
                credit_card=credit_card,
                items=items,
                vector_clock=to_tv_clock(clock),
            )
        )
    return response.success, response.message, dict(response.vector_clock.clock)


def rpc_init_fraud(order_id, user_id, contact, address, credit_card, order_amount, clock):
    """Initialize order cache and initial clock state in fraud-detection service."""
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.InitOrder(
            fraud_pb.InitOrderRequest(
                order_id=order_id,
                user_id=user_id,
                user_contact=contact,
                user_address=address,
                card_number=credit_card,
                order_amount=order_amount,
                vector_clock=to_fraud_clock(clock),
            )
        )
    return response.success, response.message, dict(response.vector_clock.clock)


def rpc_init_suggestions(order_id, user_id, items, clock):
    """Initialize order cache and initial clock state in suggestions service."""
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = sug_grpc.SuggestionsServiceStub(channel)
        response = stub.InitOrder(
            sug_pb.InitOrderRequest(
                order_id=order_id,
                user_id=user_id,
                purchased_items=items,
                vector_clock=to_sug_clock(clock),
            )
        )
    return response.success, response.message, dict(response.vector_clock.clock)


def rpc_a_verify_items(order_id, clock):
    """Event a: validate that the order has at least one item."""
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyItems(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_b_verify_user_data(order_id, clock):
    """Event b: validate mandatory user fields (name, contact, address)."""
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyUserData(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_c_verify_card_format(order_id, clock):
    """Event c: validate the card format after event a."""
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyCardFormat(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_d_check_user_fraud(order_id, clock):
    """Event d: run fraud checks on user-related fields after event b."""
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.CheckUserFraud(fraud_pb.EventRequest(order_id=order_id, vector_clock=to_fraud_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_e_check_card_fraud(order_id, clock):
    """Event e: run card fraud checks after both c and d complete."""
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.CheckCardFraud(fraud_pb.EventRequest(order_id=order_id, vector_clock=to_fraud_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_f_generate_suggestions(order_id, clock):
    """Event f: generate recommendations after fraud checks are complete."""
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = sug_grpc.SuggestionsServiceStub(channel)
        response = stub.GenerateSuggestions(sug_pb.EventRequest(order_id=order_id, vector_clock=to_sug_clock(clock)))
    books = [{"bookId": b.book_id, "title": b.title, "author": b.author} for b in response.suggested_books]
    return response.ok, response.message, books, dict(response.vector_clock.clock)


def rpc_enqueue_order(order_id, user_id, items, clock):
    """Enqueue an approved order for executor-side critical-section processing."""
    with grpc.insecure_channel("order_queue:50060") as channel:
        stub = oq_grpc.OrderQueueServiceStub(channel)
        request = oq_pb.EnqueueRequest(
            order=oq_pb.QueuedOrder(
                order_id=order_id,
                user_id=user_id,
                items=items,
                vector_clock=to_oq_clock(clock),
            )
        )
        response = stub.Enqueue(request)
    return response.success, response.message


def rpc_clear_transaction(order_id, final_clock):
    """Request transaction-verification service to clear order state using VCf."""
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.ClearOrder(
            tv_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_tv_clock(final_clock))
        )
    return response.success, response.message


def rpc_clear_fraud(order_id, final_clock):
    """Request fraud-detection service to clear order state using VCf."""
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.ClearOrder(
            fraud_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_fraud_clock(final_clock))
        )
    return response.success, response.message


def rpc_clear_suggestions(order_id, final_clock):
    """Request suggestions service to clear order state using VCf."""
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = sug_grpc.SuggestionsServiceStub(channel)
        response = stub.ClearOrder(
            sug_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_sug_clock(final_clock))
        )
    return response.success, response.message


def discover_service_replicas(host, port):
    """Discover all reachable replica endpoints behind a Docker service DNS name."""
    targets = set()
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            targets.add(f"{ip}:{port}")
    except socket.gaierror as exc:
        logger.error("Replica discovery failed | service=%s:%s | error=%s", host, port, exc)

    # Fallback to service DNS name so at least one endpoint is always attempted.
    targets.add(f"{host}:{port}")
    return sorted(targets)


def rpc_clear_target(service_name, target, order_id, final_clock):
    """Send a clear-order request to one concrete replica endpoint."""
    if service_name == "transaction_verification":
        with grpc.insecure_channel(target) as channel:
            stub = tv_grpc.TransactionVerificationServiceStub(channel)
            response = stub.ClearOrder(
                tv_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_tv_clock(final_clock))
            )
            return response.success, response.message

    if service_name == "fraud_detection":
        with grpc.insecure_channel(target) as channel:
            stub = fraud_grpc.FraudDetectionServiceStub(channel)
            response = stub.ClearOrder(
                fraud_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_fraud_clock(final_clock))
            )
            return response.success, response.message

    if service_name == "suggestions":
        with grpc.insecure_channel(target) as channel:
            stub = sug_grpc.SuggestionsServiceStub(channel)
            response = stub.ClearOrder(
                sug_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_sug_clock(final_clock))
            )
            return response.success, response.message

    return False, f"Unknown clear service: {service_name}"


def clear_target_with_retries(service_name, target, order_id, final_clock):
    """Retry clear broadcast to a replica to tolerate transient RPC failures."""
    for attempt in range(1, CLEAR_RETRY_ATTEMPTS + 1):
        try:
            success, message = rpc_clear_target(service_name, target, order_id, final_clock)
            if success:
                return {
                    "service": service_name,
                    "target": target,
                    "success": True,
                    "attempt": attempt,
                    "message": message,
                }

            if attempt < CLEAR_RETRY_ATTEMPTS:
                time.sleep(CLEAR_RETRY_BACKOFF_SEC * attempt)
            else:
                return {
                    "service": service_name,
                    "target": target,
                    "success": False,
                    "attempt": attempt,
                    "message": message,
                }
        except grpc.RpcError as exc:
            if attempt < CLEAR_RETRY_ATTEMPTS:
                time.sleep(CLEAR_RETRY_BACKOFF_SEC * attempt)
                continue
            return {
                "service": service_name,
                "target": target,
                "success": False,
                "attempt": attempt,
                "message": f"RPC error: {exc}",
            }

    return {
        "service": service_name,
        "target": target,
        "success": False,
        "attempt": CLEAR_RETRY_ATTEMPTS,
        "message": "Unknown clear error",
    }


def broadcast_final_clear(order_id, final_clock):
    """Final flow step: broadcast clear with VCf to every discovered backend replica."""
    targets = []
    for service_name, cfg in CLEAR_SERVICES.items():
        replicas = discover_service_replicas(cfg["host"], cfg["port"])
        for target in replicas:
            targets.append((service_name, target))

    results = []
    with ThreadPoolExecutor(max_workers=max(3, len(targets))) as pool:
        future_map = {
            pool.submit(clear_target_with_retries, service_name, target, order_id, final_clock): (service_name, target)
            for service_name, target in targets
        }
        for future in as_completed(future_map):
            result = future.result(timeout=12)
            results.append(result)

    failed = [r for r in results if not r["success"]]
    return {
        "all_ok": len(failed) == 0,
        "targets": len(results),
        "failed": len(failed),
        "results": results,
    }


def make_result(name, ok, message, clock, suggested_books=None):
    """Normalize event execution results into a common structure."""
    return {
        "name": name,
        "ok": ok,
        "message": message,
        "clock": dict(clock),
        "suggested_books": suggested_books or [],
    }


def run_chain_event(stop_event, dep_future, name, func):
    """Run a dependent event once its predecessor succeeds, propagating cancellation."""
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    try:
        dep = dep_future.result(timeout=10)
    except CancelledError:
        return make_result(name, False, "Cancelled due to previous failure", {})

    if not dep["ok"]:
        return make_result(name, False, f"Skipped because dependency {dep['name']} failed", dep["clock"])

    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", dep["clock"])

    clock = tick_orchestrator(dep["clock"])
    ok, message, out_clock = func(clock)
    if not ok:
        stop_event.set()
    return make_result(name, ok, message, out_clock)


def run_chain_event_with_payload(stop_event, dep_future, name, func):
    """Run a dependent event that returns both status and payload (suggestions)."""
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    try:
        dep = dep_future.result(timeout=10)
    except CancelledError:
        return make_result(name, False, "Cancelled due to previous failure", {})

    if not dep["ok"]:
        return make_result(name, False, f"Skipped because dependency {dep['name']} failed", dep["clock"])

    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", dep["clock"])

    clock = tick_orchestrator(dep["clock"])
    ok, message, payload, out_clock = func(clock)
    if not ok:
        stop_event.set()
    return make_result(name, ok, message, out_clock, suggested_books=payload)


def run_join_event(stop_event, dep1_future, dep2_future, name, func):
    """Run a join event that requires two predecessors and merges their vector clocks."""
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    try:
        dep1 = dep1_future.result(timeout=10)
        dep2 = dep2_future.result(timeout=10)
    except CancelledError:
        return make_result(name, False, "Cancelled due to previous failure", {})

    if not dep1["ok"] or not dep2["ok"]:
        merged = merge_clocks(dep1["clock"], dep2["clock"])
        return make_result(name, False, "Skipped because dependency failed", merged)

    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", merge_clocks(dep1["clock"], dep2["clock"]))

    merged = merge_clocks(dep1["clock"], dep2["clock"])
    clock = tick_orchestrator(merged)
    ok, message, out_clock = func(clock)
    if not ok:
        stop_event.set()
    return make_result(name, ok, message, out_clock)


@app.route("/", methods=["GET"])
def index():
    """Health route for basic orchestrator availability checks."""
    return "Hello from Orchestrator!"


@app.route("/checkout", methods=["POST"])
def checkout():
    """Execute ordered checkout workflow with vector clocks, queueing, and final clear broadcast."""
    try:
        body = json.loads(request.data)

        user = body.get("user", {})
        user_id = user.get("name", "").strip()
        user_contact = user.get("contact", "").strip()
        user_address = user.get("address", "").strip()

        card_data = body.get("creditCard", {})
        credit_card = card_data.get("number", "")

        items = body.get("items", [])
        item_list = [item.get("bookId", item.get("name", "")) for item in items]
        order_amount = str(len(items))

        order_id = str(uuid.uuid4())
        base_clock = tick_orchestrator({})
        latest_clock = dict(base_clock)
        status = "Order Rejected"
        books = []
        http_status = 200

        logger.info("Order started | order_id=%s | base VC=%s", order_id, base_clock)

        try:
            with ThreadPoolExecutor(max_workers=3) as init_pool:
                init_a = init_pool.submit(
                    rpc_init_transaction,
                    order_id,
                    user_id,
                    user_contact,
                    user_address,
                    credit_card,
                    item_list,
                    tick_orchestrator(base_clock),
                )
                init_b = init_pool.submit(
                    rpc_init_fraud,
                    order_id,
                    user_id,
                    user_contact,
                    user_address,
                    credit_card,
                    order_amount,
                    tick_orchestrator(base_clock),
                )
                init_c = init_pool.submit(
                    rpc_init_suggestions,
                    order_id,
                    user_id,
                    item_list,
                    tick_orchestrator(base_clock),
                )

                ok_a, msg_a, clock_a = init_a.result(timeout=10)
                ok_b, msg_b, clock_b = init_b.result(timeout=10)
                ok_c, msg_c, clock_c = init_c.result(timeout=10)

            init_clock = merge_clocks(base_clock, clock_a, clock_b, clock_c)
            latest_clock = dict(init_clock)

            if not (ok_a and ok_b and ok_c):
                logger.error("Init failed | order_id=%s | msg=%s | VC=%s", order_id, [msg_a, msg_b, msg_c], init_clock)
            else:
                stop_event = threading.Event()
                failure = None

                with ThreadPoolExecutor(max_workers=6) as pool:
                    future_a = pool.submit(
                        lambda: make_result(
                            "a",
                            *rpc_a_verify_items(order_id, tick_orchestrator(init_clock)),
                        )
                    )
                    future_b = pool.submit(
                        lambda: make_result(
                            "b",
                            *rpc_b_verify_user_data(order_id, tick_orchestrator(init_clock)),
                        )
                    )
                    future_c = pool.submit(
                        run_chain_event,
                        stop_event,
                        future_a,
                        "c",
                        lambda c_clock: rpc_c_verify_card_format(order_id, c_clock),
                    )
                    future_d = pool.submit(
                        run_chain_event,
                        stop_event,
                        future_b,
                        "d",
                        lambda d_clock: rpc_d_check_user_fraud(order_id, d_clock),
                    )
                    future_e = pool.submit(
                        run_join_event,
                        stop_event,
                        future_c,
                        future_d,
                        "e",
                        lambda e_clock: rpc_e_check_card_fraud(order_id, e_clock),
                    )
                    future_f = pool.submit(
                        run_chain_event_with_payload,
                        stop_event,
                        future_e,
                        "f",
                        lambda f_clock: rpc_f_generate_suggestions(order_id, f_clock),
                    )

                    futures = [future_a, future_b, future_c, future_d, future_e, future_f]
                    pending = set(futures)

                    while pending:
                        done_set, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                        if not done_set:
                            raise TimeoutError("Timed out while waiting for event completion")

                        for done in done_set:
                            try:
                                result = done.result(timeout=1)
                            except CancelledError:
                                continue
                            except Exception as event_exc:
                                failure = make_result("unknown", False, f"Event execution error: {event_exc}", latest_clock)
                                stop_event.set()
                                for future in pending:
                                    future.cancel()
                                pending.clear()
                                break

                            logger.info(
                                "Event %s complete | ok=%s | msg=%s | VC=%s",
                                result["name"],
                                result["ok"],
                                result["message"],
                                result["clock"],
                            )
                            if result["clock"]:
                                latest_clock = merge_clocks(latest_clock, result["clock"])
                            if not result["ok"] and failure is None:
                                failure = result
                                stop_event.set()
                                for future in pending:
                                    future.cancel()
                                pending.clear()
                                break

                    if failure is None:
                        final_result = future_f.result(timeout=10)
                    else:
                        final_result = make_result("f", False, "Not completed", failure["clock"])

                if failure is not None:
                    status = "Order Rejected"
                    books = []
                    latest_clock = merge_clocks(latest_clock, final_result["clock"])
                else:
                    status = "Order Approved"
                    books = final_result["suggested_books"]
                    latest_clock = merge_clocks(latest_clock, final_result["clock"])

                if status == "Order Approved":
                    enq_ok, enq_msg = rpc_enqueue_order(order_id, user_id, item_list, latest_clock)
                    if not enq_ok:
                        logger.error("Enqueue failed | order_id=%s | message=%s", order_id, enq_msg)
                        status = "Order Rejected"
                        books = []
                    else:
                        logger.info("Order enqueued | order_id=%s", order_id)

        except Exception as flow_exc:
            logger.exception("Checkout flow error | order_id=%s | error=%s", order_id, flow_exc)
            status = "Order Rejected"
            books = []
            http_status = 500

        final_clock = tick_orchestrator(latest_clock)
        logger.info("Flow finished | order_id=%s | status=%s | VCf=%s", order_id, status, final_clock)

        clear_summary = broadcast_final_clear(order_id, final_clock)
        if not clear_summary["all_ok"]:
            for failed in clear_summary["results"]:
                if not failed["success"]:
                    logger.error(
                        "Clear broadcast error | order_id=%s | service=%s | target=%s | attempt=%s | message=%s",
                        order_id,
                        failed["service"],
                        failed["target"],
                        failed["attempt"],
                        failed["message"],
                    )

        return {
            "orderId": order_id,
            "status": status,
            "suggestedBooks": books,
            "clearBroadcast": {
                "targets": clear_summary["targets"],
                "failed": clear_summary["failed"],
                "allOk": clear_summary["all_ok"],
            },
        }, http_status

    except json.JSONDecodeError:
        return {"error": "Invalid request format"}, 400
    except Exception as exc:
        logger.error("Checkout failed: %s", exc)
        return {"error": "Internal server error"}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
