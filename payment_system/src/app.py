import json
import logging
import os
import sys
import threading
import time
from concurrent import futures

import grpc

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
payment_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/payment"))
sys.path.insert(0, payment_grpc_path)

import payment_pb2 as pb
import payment_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PAYMENT_PORT", "50055"))
STATE_FILE = os.getenv("PAYMENT_STATE_FILE", "/tmp/payment_transactions.json")
PREPARE_TTL_SECONDS = int(os.getenv("PAYMENT_PREPARE_TTL_SECONDS", "60"))


class PaymentService(pb_grpc.PaymentServiceServicer):
    def __init__(self):
        self.lock = threading.Lock()
        self.transactions = self._load_transactions()
        self._recover_in_doubt()

    def _load_transactions(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as state_file:
                return json.load(state_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_transactions(self):
        tmp_file = f"{STATE_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as state_file:
            json.dump(self.transactions, state_file)
        os.replace(tmp_file, STATE_FILE)

    def _recover_in_doubt(self):
        if PREPARE_TTL_SECONDS <= 0:
            return
        now = time.time()
        changed = False
        for order_id, entry in self.transactions.items():
            if entry.get("state") != "prepared":
                continue
            updated_at = entry.get("updated_at", 0)
            if now - updated_at >= PREPARE_TTL_SECONDS:
                entry["state"] = "aborted"
                entry["updated_at"] = now
                self.transactions[order_id] = entry
                changed = True
        if changed:
            self._save_transactions()

    def Prepare(self, request, context):
        with self.lock:
            current = self.transactions.get(request.order_id, {})
            state = current.get("state")
            if state == "committed":
                return pb.PrepareResponse(ready=True, message="Payment already committed")
            if state == "aborted":
                return pb.PrepareResponse(ready=False, message="Payment already aborted")

            self.transactions[request.order_id] = {
                "state": "prepared",
                "amount": request.amount,
                "updated_at": time.time(),
            }
            self._save_transactions()

        logger.info("Payment prepared | order_id=%s | amount=%d", request.order_id, request.amount)
        return pb.PrepareResponse(ready=True, message="Payment prepared")

    def Commit(self, request, context):
        with self.lock:
            current = self.transactions.get(request.order_id, {})
            state = current.get("state")
            if state == "aborted":
                return pb.CommitResponse(success=False, message="Payment already aborted")
            if state not in {"prepared", "committed"}:
                return pb.CommitResponse(success=False, message="Payment was not prepared")
            if state != "committed":
                current["state"] = "committed"
                current["updated_at"] = time.time()
                self.transactions[request.order_id] = current
                self._save_transactions()

        logger.info("Payment executed | order_id=%s", request.order_id)
        return pb.CommitResponse(success=True, message="Payment committed")

    def Abort(self, request, context):
        with self.lock:
            current = self.transactions.get(request.order_id, {})
            if current.get("state") != "committed":
                current["state"] = "aborted"
                current["updated_at"] = time.time()
                self.transactions[request.order_id] = current
                self._save_transactions()

        logger.info("Payment aborted | order_id=%s", request.order_id)
        return pb.AbortResponse(aborted=True, message="Payment aborted")

    def GetTransaction(self, request, context):
        with self.lock:
            state = self.transactions.get(request.order_id, {}).get("state", "unknown")
        return pb.TransactionStatusResponse(order_id=request.order_id, state=state)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_PaymentServiceServicer_to_server(PaymentService(), server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    logger.info("Payment Service started on port %d", PORT)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
