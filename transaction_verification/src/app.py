import sys
import os
import grpc
from concurrent import futures
import logging
import re

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2
import transaction_verification_pb2_grpc


class TransactionVerificationServicer(
    transaction_verification_pb2_grpc.TransactionVerificationServiceServicer
):

    def VerifyTransaction(self, request, context):
        logging.info(f"Received transaction verification request for user_id: {request.user_id}")
        logging.info(f"Items count: {len(request.items)}, Credit card: {request.credit_card[:4]}****")

        # Verify cart is not empty
        if not request.items:
            logging.warning("Transaction verification failed: Cart is empty")
            return transaction_verification_pb2.TransactionResponse(
                is_valid=False,
                message="Cart is empty"
            )

        # Verify user_id is provided
        if not request.user_id or request.user_id.strip() == "":
            logging.warning("Transaction verification failed: User ID is missing")
            return transaction_verification_pb2.TransactionResponse(
                is_valid=False,
                message="User ID is required"
            )

        # Verify credit card format (16 digits)
        if not re.match(r"^\d{16}$", request.credit_card):
            logging.warning(f"Transaction verification failed: Invalid credit card format")
            return transaction_verification_pb2.TransactionResponse(
                is_valid=False,
                message="Invalid credit card format"
            )

        logging.info(f"Transaction verified successfully for user_id: {request.user_id}")
        return transaction_verification_pb2.TransactionResponse(
            is_valid=True,
            message="Transaction valid"
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    transaction_verification_pb2_grpc.add_TransactionVerificationServiceServicer_to_server(
        TransactionVerificationServicer(), server
    )
    server.add_insecure_port("[::]:50052")
    server.start()
    logging.info("Transaction Verification Service started on port 50052")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    serve()