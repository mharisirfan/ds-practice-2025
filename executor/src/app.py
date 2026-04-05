import sys
import os
import time
import grpc
from concurrent import futures
import logging
import threading

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
executor_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/executor"))
sys.path.insert(0, executor_grpc_path)
import executor_pb2 as ex_pb
import executor_pb2_grpc as ex_grpc

queue_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_queue"))
sys.path.insert(0, queue_grpc_path)
import order_queue_pb2 as q_pb
import order_queue_pb2_grpc as q_grpc

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s - Executor {os.environ.get('EXECUTOR_ID')} - %(message)s")
logger = logging.getLogger(__name__)

class ExecutorService(ex_grpc.ExecutorServiceServicer):
    def __init__(self, executor_id, peers):
        self.executor_id = int(executor_id)
        # peers is a dictionary: {id: "hostname:port"}
        self.peers = {int(k): v for k, v in peers.items() if int(k) != self.executor_id}
        self.leader_id = None
        self.election_in_progress = False
        self.lock = threading.Lock()

    # --- Bully Algorithm RPC Handlers ---
    def Election(self, request, context):
        # Someone with a lower ID called an election. We are bigger, so we tell them to stop.
        logger.info(f"Received ELECTION from Node {request.sender_id}")
        threading.Thread(target=self.start_election).start() # Also start our own election to find the real boss
        return ex_pb.ElectionResponse(success=True)

    def Coordinator(self, request, context):
        with self.lock:
            self.leader_id = request.leader_id
            self.election_in_progress = False
        logger.info(f"Node {request.leader_id} is the new LEADER.")
        return ex_pb.CoordinatorResponse(success=True)

    def Heartbeat(self, request, context):
        return ex_pb.HeartbeatResponse(success=True)

    # --- Active Logic ---
    def start_election(self):
        with self.lock:
            if self.election_in_progress:
                return
            self.election_in_progress = True
            self.leader_id = None
        
        logger.info("Starting ELECTION...")
        higher_peers = {k: v for k, v in self.peers.items() if k > self.executor_id}
        
        got_response = False
        for peer_id, address in higher_peers.items():
            try:
                with grpc.insecure_channel(address) as channel:
                    stub = ex_grpc.ExecutorServiceStub(channel)
                    resp = stub.Election(ex_pb.ElectionRequest(sender_id=self.executor_id), timeout=2)
                    if resp.success:
                        got_response = True
            except grpc.RpcError:
                pass # Node is down
        
        if not got_response:
            # I am the biggest node alive!
            self.become_leader()
        else:
            # A bigger node is alive, wait for them to send Coordinator msg
            time.sleep(3)
            with self.lock:
                if self.leader_id is None: # If they failed to claim it, restart
                    self.election_in_progress = False
                    threading.Thread(target=self.start_election).start()

    def become_leader(self):
        with self.lock:
            self.leader_id = self.executor_id
            self.election_in_progress = False
        
        logger.info("I AM THE NEW LEADER! Broadcasting to lower IDs...")
        lower_peers = {k: v for k, v in self.peers.items() if k < self.executor_id}
        for peer_id, address in lower_peers.items():
            try:
                with grpc.insecure_channel(address) as channel:
                    stub = ex_grpc.ExecutorServiceStub(channel)
                    stub.Coordinator(ex_pb.CoordinatorRequest(leader_id=self.executor_id), timeout=2)
            except grpc.RpcError:
                pass

    def check_leader(self):
        """Background thread to monitor the leader's health."""
        while True:
            time.sleep(5)
            with self.lock:
                current_leader = self.leader_id
                in_election = self.election_in_progress

            if in_election:
                continue

            if current_leader is None:
                self.start_election()
            elif current_leader != self.executor_id:
                # Ping the leader
                leader_address = self.peers.get(current_leader)
                if leader_address:
                    try:
                        with grpc.insecure_channel(leader_address) as channel:
                            stub = ex_grpc.ExecutorServiceStub(channel)
                            stub.Heartbeat(ex_pb.HeartbeatRequest(leader_id=self.executor_id), timeout=2)
                    except grpc.RpcError:
                        logger.warning(f"Leader {current_leader} did not respond! Triggering election.")
                        self.start_election()

    def run_worker(self):
        """Background thread to process the queue if this node is the leader."""
        while True:
            time.sleep(2)
            with self.lock:
                is_leader = (self.leader_id == self.executor_id)
            
            if is_leader:
                try:
                    with grpc.insecure_channel("order_queue:50054") as channel:
                        stub = q_grpc.OrderQueueServiceStub(channel)
                        response = stub.Dequeue(q_pb.DequeueRequest(), timeout=2)
                        if response.success:
                            logger.info(f"==> Order {response.order_id} is being executed! <==")
                            time.sleep(2) # Simulate execution work
                except grpc.RpcError as e:
                    logger.error(f"Failed to connect to queue: {e.details()}")

def serve():
    executor_id = os.environ.get("EXECUTOR_ID")
    port = os.environ.get("PORT", "50055")
    # Format: "1:executor1:50055,2:executor2:50056,3:executor3:50057"
    peers_env = os.environ.get("PEERS", "")
    peers = {}
    if peers_env:
        for p in peers_env.split(","):
            pid, address = p.split(":", 1)
            peers[int(pid)] = address

    service = ExecutorService(executor_id, peers)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    ex_grpc.add_ExecutorServiceServicer_to_server(service, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    
    # Start background threads
    threading.Thread(target=service.check_leader, daemon=True).start()
    threading.Thread(target=service.run_worker, daemon=True).start()
    
    logger.info(f"Executor {executor_id} started on port {port}")
    # Force initial election
    service.start_election()
    
    server.wait_for_termination()

if __name__ == "__main__":
    serve()