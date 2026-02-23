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
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FraudDetectionService(fraud_detection_grpc.FraudDetectionServiceServicer):
    """
    gRPC service for fraud detection.
    Implements simple heuristics to detect potentially fraudulent transactions.
    """
    
    def CheckFraud(self, request, context):
        """
        RPC method to check if a transaction is fraudulent.
        
        Fraud detection heuristics:
        - Unusual order amounts (very high)
        - Invalid card format
        - Suspicious patterns
        
        Args:
            request: FraudRequest with card_number and order_amount
            context: gRPC context
        
        Returns:
            FraudResponse with is_fraud flag
        """
        logger.info(f"Received fraud check request")
        logger.info(f"Card ending in: {request.card_number[-4:] if len(request.card_number) >= 4 else 'XXXX'}")
        logger.info(f"Order amount: {request.order_amount}")
        
        is_fraud = False
        reason = "No fraud detected"
        
        try:
            # Check 1: Validate credit card format (should be 16 digits)
            if not re.match(r"^\d{16}$", request.card_number):
                logger.warning("Fraud detected: Invalid card format")
                is_fraud = True
                reason = "Invalid card format"
            
            # Check 2: Check for suspicious order amounts
            try:
                amount = float(request.order_amount)
                if amount > 10000:  # Very high order amount
                    logger.warning(f"Fraud detected: Unusually high order amount: {amount}")
                    is_fraud = True
                    reason = "Unusually high order amount"
                elif amount < 0:
                    logger.warning("Fraud detected: Negative order amount")
                    is_fraud = True
                    reason = "Invalid order amount"
            except ValueError:
                logger.warning(f"Fraud detected: Invalid amount value: {request.order_amount}")
                is_fraud = True
                reason = "Invalid amount format"
            
            # Check 3: Simple pattern detection
            # Detect if card number starts with common fraud patterns
            if request.card_number.startswith("1111"):
                logger.warning("Fraud detected: Suspicious card pattern detected")
                is_fraud = True
                reason = "Suspicious card pattern"
            
            # Create response
            response = fraud_detection.FraudResponse()
            response.is_fraud = "true" if is_fraud else "false"
            
            logger.info(f"Fraud check result: {'FRAUD DETECTED' if is_fraud else 'NOT FRAUDULENT'} - {reason}")
            return response
            
        except Exception as e:
            logger.error(f"Error during fraud detection: {str(e)}")
            response = fraud_detection.FraudResponse()
            response.is_fraud = "false"
            return response


def serve():
    """
    Start the gRPC server for the Fraud Detection service.
    Listens on port 50051.
    """
    logger.info("Starting Fraud Detection Service...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    fraud_detection_grpc.add_FraudDetectionServiceServicer_to_server(FraudDetectionService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    logger.info("Fraud Detection Service started on port 50051")
    server.wait_for_termination()


if __name__ == '__main__':
    serve()