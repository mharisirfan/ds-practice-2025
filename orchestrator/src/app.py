import sys
import os
import json
import logging
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError

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

queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, queue_grpc_path)
import order_queue_pb2 as q_pb
import order_queue_pb2_grpc as q_grpc

import grpc
from flask import Flask, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ORCH_KEY = "orchestrator"

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


def merge_clocks(*clocks):
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged


def tick_orchestrator(clock):
    updated = dict(clock)
    updated[ORCH_KEY] = updated.get(ORCH_KEY, 0) + 1
    return updated


def to_tv_clock(clock):
    msg = tv_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def to_fraud_clock(clock):
    msg = fraud_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def to_sug_clock(clock):
    msg = sug_pb.VectorClock()
    msg.clock.update(clock)
    return msg


def rpc_init_transaction(order_id, user_id, contact, address, credit_card, items, clock):
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
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyItems(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_b_verify_user_data(order_id, clock):
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyUserData(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_c_verify_card_format(order_id, clock):
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.VerifyCardFormat(tv_pb.EventRequest(order_id=order_id, vector_clock=to_tv_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_d_check_user_fraud(order_id, clock):
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.CheckUserFraud(fraud_pb.EventRequest(order_id=order_id, vector_clock=to_fraud_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_e_check_card_fraud(order_id, clock):
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.CheckCardFraud(fraud_pb.EventRequest(order_id=order_id, vector_clock=to_fraud_clock(clock)))
    return response.ok, response.message, dict(response.vector_clock.clock)


def rpc_f_generate_suggestions(order_id, clock):
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = sug_grpc.SuggestionsServiceStub(channel)
        response = stub.GenerateSuggestions(sug_pb.EventRequest(order_id=order_id, vector_clock=to_sug_clock(clock)))
    books = [{"bookId": b.book_id, "title": b.title, "author": b.author} for b in response.suggested_books]
    return response.ok, response.message, books, dict(response.vector_clock.clock)


def rpc_clear_transaction(order_id, final_clock):
    with grpc.insecure_channel("transaction_verification:50052") as channel:
        stub = tv_grpc.TransactionVerificationServiceStub(channel)
        response = stub.ClearOrder(
            tv_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_tv_clock(final_clock))
        )
    return response.success, response.message


def rpc_clear_fraud(order_id, final_clock):
    with grpc.insecure_channel("fraud_detection:50051") as channel:
        stub = fraud_grpc.FraudDetectionServiceStub(channel)
        response = stub.ClearOrder(
            fraud_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_fraud_clock(final_clock))
        )
    return response.success, response.message


def rpc_clear_suggestions(order_id, final_clock):
    with grpc.insecure_channel("suggestions:50053") as channel:
        stub = sug_grpc.SuggestionsServiceStub(channel)
        response = stub.ClearOrder(
            sug_pb.ClearOrderRequest(order_id=order_id, final_vector_clock=to_sug_clock(final_clock))
        )
    return response.success, response.message


def make_result(name, ok, message, clock, suggested_books=None):
    return {
        "name": name,
        "ok": ok,
        "message": message,
        "clock": dict(clock),
        "suggested_books": suggested_books or [],
    }


def run_chain_event(stop_event, dep_future, name, func):
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    dep = dep_future.result(timeout=10)
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
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    dep = dep_future.result(timeout=10)
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
    if stop_event.is_set():
        return make_result(name, False, "Cancelled due to previous failure", {})

    dep1 = dep1_future.result(timeout=10)
    dep2 = dep2_future.result(timeout=10)

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

def rpc_enqueue_order(order_id):
    try:
        with grpc.insecure_channel("order_queue:50054") as channel:
            stub = q_grpc.OrderQueueServiceStub(channel)
            response = stub.Enqueue(q_pb.EnqueueRequest(order_id=order_id))
            return response.success
    except Exception as e:
        logger.error(f"Failed to enqueue order {order_id}: {e}")
        return False

@app.route("/", methods=["GET"])
def index():
    return "Hello from Orchestrator!"


@app.route("/checkout", methods=["POST"])
def checkout():
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

        logger.info("Order started | order_id=%s | base VC=%s", order_id, base_clock)

        with ThreadPoolExecutor(max_workers=3) as init_pool:
            init_a = init_pool.submit(
                rpc_init_transaction,
                order_id, user_id, user_contact, user_address, credit_card, item_list,
                tick_orchestrator(base_clock),
            )
            init_b = init_pool.submit(
                rpc_init_fraud,
                order_id, user_id, user_contact, user_address, credit_card, order_amount,
                tick_orchestrator(base_clock),
            )
            init_c = init_pool.submit(
                rpc_init_suggestions,
                order_id, user_id, item_list,
                tick_orchestrator(base_clock),
            )

            ok_a, msg_a, clock_a = init_a.result(timeout=10)
            ok_b, msg_b, clock_b = init_b.result(timeout=10)
            ok_c, msg_c, clock_c = init_c.result(timeout=10)

        if not (ok_a and ok_b and ok_c):
            merged = merge_clocks(clock_a, clock_b, clock_c)
            logger.error("Init failed | order_id=%s | msg=%s | VC=%s", order_id, [msg_a, msg_b, msg_c], merged)
            with ThreadPoolExecutor(max_workers=3) as clear_pool:
                clear_pool.submit(rpc_clear_transaction, order_id, merged)
                clear_pool.submit(rpc_clear_fraud, order_id, merged)
                clear_pool.submit(rpc_clear_suggestions, order_id, merged)
            return {"orderId": order_id, "status": "Order Rejected", "suggestedBooks": []}

        init_clock = merge_clocks(base_clock, clock_a, clock_b, clock_c)
        stop_event = threading.Event()
        failure = None
        
        # ---> THE FIX: Track the highest clock seen across ALL threads <---
        accumulated_clock = init_clock

        with ThreadPoolExecutor(max_workers=6) as pool:
            future_a = pool.submit(lambda: make_result("a", *rpc_a_verify_items(order_id, tick_orchestrator(init_clock))))
            future_b = pool.submit(lambda: make_result("b", *rpc_b_verify_user_data(order_id, tick_orchestrator(init_clock))))
            future_c = pool.submit(run_chain_event, stop_event, future_a, "c", lambda c_clock: rpc_c_verify_card_format(order_id, c_clock))
            future_d = pool.submit(run_chain_event, stop_event, future_b, "d", lambda d_clock: rpc_d_check_user_fraud(order_id, d_clock))
            future_e = pool.submit(run_join_event, stop_event, future_c, future_d, "e", lambda e_clock: rpc_e_check_card_fraud(order_id, e_clock))
            future_f = pool.submit(run_chain_event_with_payload, stop_event, future_e, "f", lambda f_clock: rpc_f_generate_suggestions(order_id, f_clock))

            futures = [future_a, future_b, future_c, future_d, future_e, future_f]
            for done in as_completed(futures):
                try:
                    result = done.result(timeout=10)
                    
                    # Merge EVERY returning clock into our global tracker
                    accumulated_clock = merge_clocks(accumulated_clock, result["clock"])
                    
                    logger.info("Event %s complete | ok=%s | msg=%s | VC=%s", result["name"], result["ok"], result["message"], result["clock"])
                    
                    if not result["ok"] and failure is None:
                        failure = result
                        stop_event.set()
                        for future in futures:
                            future.cancel()
                            
                # We must catch CancelledError because we call future.cancel() above.
                # Cancelled futures will throw this when yielded by as_completed.
                except CancelledError:
                    pass
                except Exception as exc:
                    logger.error("Thread pool execution error: %s", exc)

            if failure is None:
                final_result = future_f.result(timeout=10)
            else:
                final_result = make_result("f", False, "Not completed", accumulated_clock)

        if failure is not None:
            # We now use the accumulated clock instead of just failure["clock"]
            final_clock = accumulated_clock
            status = "Order Rejected"
            books = []
        else:
            final_clock = accumulated_clock
            status = "Order Approved"
            books = final_result["suggested_books"]

            enqueue_success = rpc_enqueue_order(order_id)
            if not enqueue_success:
                logger.error("Order verified but failed to enqueue!")
                status = "Order Error (Queue Down)"

        final_clock = tick_orchestrator(final_clock)
        logger.info("Flow finished | order_id=%s | status=%s | VCf=%s", order_id, status, final_clock)

        with ThreadPoolExecutor(max_workers=3) as clear_pool:
            clear_futures = [
                clear_pool.submit(rpc_clear_transaction, order_id, final_clock),
                clear_pool.submit(rpc_clear_fraud, order_id, final_clock),
                clear_pool.submit(rpc_clear_suggestions, order_id, final_clock),
            ]
            clear_results = [f.result(timeout=10) for f in clear_futures]

        for success, message in clear_results:
            if not success:
                logger.error("Clear broadcast error | order_id=%s | %s", order_id, message)

        return {
            "orderId": order_id,
            "status": status,
            "suggestedBooks": books,
        }

    except json.JSONDecodeError:
        return {"error": "Invalid request format"}, 400
    except Exception as exc:
        logger.error("Checkout failed: %s", exc)
        return {"error": "Internal server error"}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)