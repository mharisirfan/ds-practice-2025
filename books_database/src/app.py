import sys
import os
import grpc
import logging
import threading
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

class BooksDatabaseServicer(pb_grpc.BooksDatabaseServicer):
    def __init__(self):
        # Initialize with some mock data
        self.store = {"Book A": 10, "Book B": 15}
        self.lock = threading.Lock()
        
        # Set up backup connections if this node is the primary
        self.backups = []
        if ROLE == "primary" and BACKUP_ADDRESSES[0]:
            for addr in BACKUP_ADDRESSES:
                channel = grpc.insecure_channel(addr.strip())
                self.backups.append(pb_grpc.BooksDatabaseStub(channel))
                logger.info(f"Primary registered backup at {addr}")

    def Read(self, request, context):
        with self.lock:
            stock = self.store.get(request.title, 0)
        return pb.ReadResponse(stock=stock)

    def Write(self, request, context):
        with self.lock:
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

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_BooksDatabaseServicer_to_server(BooksDatabaseServicer(), server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    logger.info(f"Books Database ({ROLE}) started on port {PORT}")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()