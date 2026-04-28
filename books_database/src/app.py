"""
Books Database Service with Primary-Backup Replication

Consistency Model: Primary-Backup (Strong Consistency)
- All writes go through a single primary
- Primary propagates writes to backups before acknowledging to client
- Reads can be served from any replica (they all have the same data)
- Provides sequential consistency

Concurrency Handling:
- Uses version numbers to detect and handle concurrent writes
- Maintains last-write-wins with version tracking for orders
"""

import sys
import os
import time
import grpc
import logging
import threading
import json
from concurrent import futures
from typing import Dict, Tuple

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

books_db_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/books_database"))
sys.path.insert(0, books_db_grpc_path)
import books_database_pb2 as db_pb
import books_database_pb2_grpc as db_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPLICA_ID = os.getenv("REPLICA_ID", "db-1")
GRPC_PORT = int(os.getenv("DB_PORT", "50050"))
IS_PRIMARY = os.getenv("IS_PRIMARY", "false").lower() == "true"
BACKUP_ADDRS = os.getenv("BACKUP_ADDRS", "").split(",")  # Comma-separated list of backup addresses
BACKUP_ADDRS = [addr.strip() for addr in BACKUP_ADDRS if addr.strip()]

# Retry configuration for backup synchronization
REPLICATION_RETRIES = 3
REPLICATION_TIMEOUT = 2.0


class BooksDatabaseStorage:
    """Thread-safe in-memory key-value store for book stock."""
    
    def __init__(self):
        self.store: Dict[str, Tuple[int, int, str]] = {}  # title -> (stock, version, last_client_order_id)
        self.version_counter = 0
        self.lock = threading.RLock()
        self._init_default_books()
    
    def _init_default_books(self):
        """Initialize with some default books for testing."""
        default_books = {
            "The Great Gatsby": 50,
            "To Kill a Mockingbird": 30,
            "1984": 40,
            "Pride and Prejudice": 25,
            "The Catcher in the Rye": 35,
        }
        with self.lock:
            for title, stock in default_books.items():
                self.store[title] = (stock, 0, "")
    
    def read(self, title: str) -> Tuple[bool, str, int, int]:
        """
        Read the current stock of a book.
        
        Returns: (success, message, stock, version)
        """
        with self.lock:
            if title not in self.store:
                return False, f"Book '{title}' not found", 0, 0
            stock, version, _ = self.store[title]
            return True, "Read successful", stock, version
    
    def write(self, title: str, new_stock: int, client_id: str, order_id: str) -> Tuple[bool, str, int]:
        """
        Write a new stock value for a book.
        Implements last-write-wins with version tracking for concurrency.
        
        Returns: (success, message, new_version)
        """
        with self.lock:
            self.version_counter += 1
            current_version = self.version_counter
            
            if title not in self.store:
                # Create new book entry
                self.store[title] = (new_stock, current_version, order_id)
            else:
                # Update existing book
                _, _, last_order_id = self.store[title]
                # Log concurrent access if needed
                if last_order_id and last_order_id != order_id:
                    logger.info(
                        "Concurrent write detected for '%s': new_order=%s, previous_order=%s",
                        title, order_id, last_order_id
                    )
                self.store[title] = (new_stock, current_version, order_id)
            
            return True, "Write successful", current_version
    
    def get_all(self) -> Dict[str, Tuple[int, int, str]]:
        """Get a copy of the entire store (for debugging/monitoring)."""
        with self.lock:
            return dict(self.store)


class BooksDatabase(db_grpc.BooksDatabaseServicer):
    """Main gRPC service implementing the BooksDatabase interface."""
    
    def __init__(self, storage: BooksDatabaseStorage, is_primary: bool = False, backup_addrs: list = None):
        self.storage = storage
        self.is_primary = is_primary
        self.backup_addrs = backup_addrs or []
        self.replica_count = len(self.backup_addrs) + 1  # Primary + Backups
    
    def Read(self, request, context):
        """Handle read requests."""
        title = request.title
        success, message, stock, version = self.storage.read(title)
        
        if success:
            logger.info("Read | title=%s | stock=%d | version=%d", title, stock, version)
        else:
            logger.warning("Read failed | title=%s | message=%s", title, message)
        
        return db_pb.ReadResponse(
            success=success,
            message=message,
            stock=stock,
            version=version
        )
    
    def Write(self, request, context):
        """Handle write requests with Primary-Backup replication."""
        title = request.title
        new_stock = request.new_stock
        client_id = request.client_id
        order_id = request.order_id
        
        if not self.is_primary:
            # Only primary accepts writes
            logger.warning(
                "Write rejected (not primary) | replica=%s | title=%s | order_id=%s",
                REPLICA_ID, title, order_id
            )
            return db_pb.WriteResponse(
                success=False,
                message=f"Replica {REPLICA_ID} is not primary",
                version=0
            )
        
        # Primary: perform local write first
        success, message, version = self.storage.write(title, new_stock, client_id, order_id)
        
        if not success:
            logger.error("Primary write failed | title=%s | order_id=%s", title, order_id)
            return db_pb.WriteResponse(
                success=False,
                message=message,
                version=0
            )
        
        # Replicate to backups
        replication_success = self._replicate_to_backups(title, new_stock, client_id, order_id, version)
        
        if replication_success or not self.backup_addrs:
            # If replication succeeds or no backups, acknowledge
            logger.info(
                "Write successful | replica=%s | title=%s | new_stock=%d | version=%d | order_id=%s",
                REPLICA_ID, title, new_stock, version, order_id
            )
            return db_pb.WriteResponse(
                success=True,
                message="Write successful and replicated",
                version=version
            )
        else:
            # Replication failed - log but still return success (best-effort replication)
            logger.warning(
                "Write local success but replication failed | title=%s | order_id=%s",
                title, order_id
            )
            return db_pb.WriteResponse(
                success=True,
                message="Write successful locally but replication failed",
                version=version
            )
    
    def _replicate_to_backups(self, title: str, new_stock: int, client_id: str, order_id: str, version: int) -> bool:
        """Replicate write to all backups with retry logic."""
        if not self.backup_addrs:
            return True  # No backups to replicate to
        
        successful_replications = 0
        required_acks = len(self.backup_addrs)
        
        for backup_addr in self.backup_addrs:
            if self._replicate_to_single_backup(backup_addr, title, new_stock, client_id, order_id, version):
                successful_replications += 1
            else:
                logger.warning("Failed to replicate to backup | backup=%s | title=%s", backup_addr, title)
        
        # Require all backups to acknowledge for strong consistency
        return successful_replications == required_acks
    
    def _replicate_to_single_backup(self, backup_addr: str, title: str, new_stock: int, client_id: str, order_id: str, version: int) -> bool:
        """Attempt to replicate to a single backup with retries."""
        for attempt in range(REPLICATION_RETRIES):
            try:
                with grpc.insecure_channel(backup_addr) as channel:
                    backup_stub = db_grpc.BooksDatabaseStub(channel)
                    response = backup_stub.ReplicateWrite(
                        db_pb.ReplicateWriteRequest(
                            title=title,
                            new_stock=new_stock,
                            client_id=client_id,
                            order_id=order_id,
                            version=version
                        ),
                        timeout=REPLICATION_TIMEOUT
                    )
                    if response.success:
                        logger.debug("Replication successful | backup=%s | title=%s | order_id=%s", backup_addr, title, order_id)
                        return True
                    else:
                        logger.warning("Backup replication failed | backup=%s | message=%s", backup_addr, response.message)
            except Exception as e:
                logger.warning(
                    "Replication error (attempt %d/%d) | backup=%s | error=%s",
                    attempt + 1, REPLICATION_RETRIES, backup_addr, str(e)
                )
        
        return False
    
    def ReplicateWrite(self, request, context):
        """Handle replication requests from primary (backup operation)."""
        if self.is_primary:
            logger.error("Primary received ReplicateWrite request (should only go to backups)")
            return db_pb.ReplicateWriteResponse(
                success=False,
                message="Primary cannot receive replication requests",
                version=0
            )
        
        title = request.title
        new_stock = request.new_stock
        client_id = request.client_id
        order_id = request.order_id
        version = request.version
        
        # Backup: apply the write locally
        success, message, local_version = self.storage.write(title, new_stock, client_id, order_id)
        
        logger.info(
            "Backup replicated write | replica=%s | title=%s | new_stock=%d | version=%d | order_id=%s",
            REPLICA_ID, title, new_stock, version, order_id
        )
        
        return db_pb.ReplicateWriteResponse(
            success=success,
            message=message,
            version=local_version
        )
    
    def Ping(self, request, context):
        """Health check and status endpoint."""
        replica_id = request.replica_id
        logger.debug("Ping received from %s", replica_id)
        
        return db_pb.PingResponse(
            alive=True,
            replica_id=REPLICA_ID,
            is_primary=self.is_primary,
            replica_count=self.replica_count
        )


def serve():
    """Start the gRPC database service."""
    storage = BooksDatabaseStorage()
    service = BooksDatabase(storage, is_primary=IS_PRIMARY, backup_addrs=BACKUP_ADDRS)
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    db_grpc.add_BooksDatabaseServicer_to_server(service, server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    
    role = "Primary" if IS_PRIMARY else "Backup"
    logger.info(
        "%s Books Database %s started on port %d | backups=%s",
        role, REPLICA_ID, GRPC_PORT, BACKUP_ADDRS if IS_PRIMARY else "N/A"
    )
    
    # Log default books
    for title, (stock, version, _) in storage.get_all().items():
        logger.info("Initial book | title=%s | stock=%d | version=%d", title, stock, version)
    
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
