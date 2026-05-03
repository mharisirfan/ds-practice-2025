import sys
import os
import json
import grpc
import logging
import threading
from collections import Counter
from concurrent import futures

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
books_database_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/books_database"))
sys.path.insert(0, books_database_grpc_path)

import books_database_pb2 as pb
import books_database_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ROLE = os.getenv("DB_ROLE", "backup") # 'primary' or 'backup'
BACKUP_ADDRESSES = os.getenv("BACKUP_ADDRS", "").split(",") # e.g., "db_backup_1:50054,db_backup_2:50055"
PORT = int(os.getenv("PORT", "50054"))
STATE_FILE = os.getenv("DB_STATE_FILE", "/tmp/books_db_state.json")

class BooksDatabaseServicer(pb_grpc.BooksDatabaseServicer):
    def __init__(self):
        self.store, self.prepared_orders, self.completed_orders = self._load_state()
        self.lock = threading.Lock()
        
        # Set up backup connections if this node is the primary
        self.backups = []
        if ROLE == "primary" and BACKUP_ADDRESSES[0]:
            for addr in BACKUP_ADDRESSES:
                channel = grpc.insecure_channel(addr.strip())
                self.backups.append(pb_grpc.BooksDatabaseStub(channel))
                logger.info(f"Primary registered backup at {addr}")

    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("Invalid state file")
                store = data.get("store", {})
                prepared_orders = data.get("prepared_orders", {})
                completed_orders = data.get("completed_orders", {})
                if not isinstance(store, dict):
                    store = {}
                if not isinstance(prepared_orders, dict):
                    prepared_orders = {}
                if not isinstance(completed_orders, dict):
                    completed_orders = {}
                return store, prepared_orders, completed_orders
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return {"Book A": 10, "Book B": 15}, {}, {}

    def _save_state(self):
        tmp_path = f"{STATE_FILE}.tmp"
        payload = {
            "store": self.store,
            "prepared_orders": self.prepared_orders,
            "completed_orders": self.completed_orders,
        }
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, STATE_FILE)

    def Read(self, request, context):
        with self.lock:
            stock = self.store.get(request.title, 0)
        return pb.ReadResponse(stock=stock)

    def Write(self, request, context):
        with self.lock:
            if ROLE != "primary" and not request.is_replica_sync:
                return pb.WriteResponse(success=False, message="Writes must go through the primary replica.")

            current_stock = self.store.get(request.title, 0)
            
            # BONUS: Concurrency Control (Compare-And-Swap)
            # If the client provided an expected stock, and it doesn't match our current state,
            # someone else updated it first. Reject the write.
            if not request.is_replica_sync and request.expected_stock != -1:
                if current_stock != request.expected_stock:
                    logger.warning(f"Concurrent write detected for '{request.title}'. Rejecting.")
                    return pb.WriteResponse(success=False, message="Stock modified by another transaction.")

            # Update local state
            self.store[request.title] = request.new_stock
            logger.info(f"Updated '{request.title}' to {request.new_stock}")
            self._save_state()

            # If Primary, synchronously propagate to backups
            if ROLE == "primary" and not request.is_replica_sync:
                for backup_stub in self.backups:
                    try:
                        # Send as a replica sync to bypass CAS checks on the backup
                        backup_stub.Write(pb.WriteRequest(
                            title=request.title, 
                            new_stock=request.new_stock, 
                            expected_stock=-1, 
                            is_replica_sync=True
                        ), timeout=2.0)
                    except Exception as e:
                        logger.error(f"Failed to replicate to backup: {e}")
                        # In a strict system, you might revert the local write here.
                        return pb.WriteResponse(success=False, message=f"Replication failed: {e}")

        return pb.WriteResponse(success=True, message="Write successful")

    def Prepare(self, request, context):
        with self.lock:
            if ROLE != "primary" and not request.is_replica_sync:
                return pb.PrepareResponse(ready=False, message="Prepare must go through the primary replica.")

            if self.completed_orders.get(request.order_id) == "committed":
                return pb.PrepareResponse(ready=True, message="Order already committed.")
            if self.completed_orders.get(request.order_id) == "aborted":
                return pb.PrepareResponse(ready=False, message="Order already aborted.")
            if request.order_id in self.prepared_orders:
                return pb.PrepareResponse(ready=True, message="Order already prepared.")

            item_counts = Counter(request.items)
            for title, quantity in item_counts.items():
                reserved = sum(
                    prepared.get(title, 0)
                    for order_id, prepared in self.prepared_orders.items()
                    if order_id != request.order_id
                )
                available_stock = self.store.get(title, 0) - reserved
                if available_stock < quantity:
                    return pb.PrepareResponse(
                        ready=False,
                        message=f"Not enough stock for '{title}' (available={available_stock}, required={quantity}).",
                    )

            self.prepared_orders[request.order_id] = dict(item_counts)
            self._save_state()

        if ROLE == "primary" and not request.is_replica_sync:
            for backup_stub in self.backups:
                try:
                    response = backup_stub.Prepare(
                        pb.PrepareRequest(
                            order_id=request.order_id,
                            items=list(request.items),
                            is_replica_sync=True,
                        ),
                        timeout=2.0,
                    )
                    if not response.ready:
                        self._abort_backups(request.order_id)
                        with self.lock:
                            self.prepared_orders.pop(request.order_id, None)
                            self.completed_orders[request.order_id] = "aborted"
                            self._save_state()
                        return pb.PrepareResponse(ready=False, message=response.message)
                except Exception as exc:
                    self._abort_backups(request.order_id)
                    with self.lock:
                        self.prepared_orders.pop(request.order_id, None)
                        self.completed_orders[request.order_id] = "aborted"
                        self._save_state()
                    logger.error("Failed to prepare backup: %s", exc)
                    return pb.PrepareResponse(ready=False, message=f"Backup prepare failed: {exc}")

        logger.info("Database prepared | order_id=%s", request.order_id)
        return pb.PrepareResponse(ready=True, message="Database prepared")

    def Commit(self, request, context):
        with self.lock:
            if ROLE != "primary" and not request.is_replica_sync:
                return pb.CommitResponse(success=False, message="Commit must go through the primary replica.")
            if self.completed_orders.get(request.order_id) == "committed":
                return pb.CommitResponse(success=True, message="Order already committed.")
            if self.completed_orders.get(request.order_id) == "aborted":
                return pb.CommitResponse(success=False, message="Order already aborted.")

            staged_update = self.prepared_orders.get(request.order_id)
            if staged_update is None:
                return pb.CommitResponse(success=False, message="Order was not prepared.")

        if ROLE == "primary" and not request.is_replica_sync:
            for backup_stub in self.backups:
                try:
                    response = backup_stub.Commit(
                        pb.CommitRequest(order_id=request.order_id, is_replica_sync=True),
                        timeout=2.0,
                    )
                    if not response.success:
                        return pb.CommitResponse(success=False, message=response.message)
                except Exception as exc:
                    logger.error("Failed to commit backup: %s", exc)
                    return pb.CommitResponse(success=False, message=f"Backup commit failed: {exc}")

        with self.lock:
            staged_update = self.prepared_orders.pop(request.order_id, None)
            if staged_update is None and self.completed_orders.get(request.order_id) == "committed":
                return pb.CommitResponse(success=True, message="Order already committed.")
            if staged_update is None:
                return pb.CommitResponse(success=False, message="Order was not prepared.")
            for title, quantity in staged_update.items():
                self.store[title] = self.store.get(title, 0) - quantity
            self.completed_orders[request.order_id] = "committed"
            self._save_state()

        logger.info("Database committed | order_id=%s", request.order_id)
        return pb.CommitResponse(success=True, message="Database committed")

    def Abort(self, request, context):
        with self.lock:
            if ROLE != "primary" and not request.is_replica_sync:
                return pb.AbortResponse(aborted=False, message="Abort must go through the primary replica.")
            if self.completed_orders.get(request.order_id) == "committed":
                return pb.AbortResponse(aborted=False, message="Order already committed.")
            self.prepared_orders.pop(request.order_id, None)
            self.completed_orders[request.order_id] = "aborted"
            self._save_state()

        if ROLE == "primary" and not request.is_replica_sync:
            self._abort_backups(request.order_id)

        logger.info("Database aborted | order_id=%s", request.order_id)
        return pb.AbortResponse(aborted=True, message="Database aborted")

    def _abort_backups(self, order_id):
        for backup_stub in self.backups:
            try:
                backup_stub.Abort(pb.AbortRequest(order_id=order_id, is_replica_sync=True), timeout=2.0)
            except Exception as exc:
                logger.error("Failed to abort backup: %s", exc)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_BooksDatabaseServicer_to_server(BooksDatabaseServicer(), server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    logger.info(f"Books Database ({ROLE}) started on port {PORT}")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
