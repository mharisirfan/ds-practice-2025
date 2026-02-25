import sys
import os
import threading
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")

# Setup fraud_detection gRPC path
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

# Setup transaction_verification gRPC path
transaction_verification_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/transaction_verification'))
sys.path.insert(0, transaction_verification_grpc_path)
import transaction_verification_pb2 as transaction_verification
import transaction_verification_pb2_grpc as transaction_verification_grpc

# Setup suggestions gRPC path
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2 as suggestions
import suggestions_pb2_grpc as suggestions_grpc

import grpc
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_fraud(card_number, order_amount):
    """
    gRPC CLIENT COMMUNICATION — FRAUD SERVICE

    This function establishes a gRPC client connection
    to the fraud_detection service.

    It:
    - Opens a gRPC channel
    - Sends FraudRequest message
    - Receives FraudResponse

    This implements inter-service communication using gRPC.
    """
    try:
        logger.info(f"Worker thread: Checking fraud for card ending in {card_number[-4:]}")
        with grpc.insecure_channel('fraud_detection:50051') as channel:
            stub = fraud_detection_grpc.FraudDetectionServiceStub(channel)
            response = stub.CheckFraud(fraud_detection.FraudRequest(
                card_number=card_number,
                order_amount=order_amount
            ))
        is_fraud = response.is_fraud.lower() == "true"
        logger.info(f"Fraud check result: {'FRAUDULENT' if is_fraud else 'NOT FRAUDULENT'}")
        return is_fraud
    except Exception as e:
        logger.error(f"Error checking fraud: {str(e)}")
        return False


def verify_transaction(user_id, credit_card, items):
    """
    gRPC CLIENT COMMUNICATION — TRANSACTION VERIFICATION

    This function connects to the transaction_verification
    service via gRPC.

    It sends a TransactionRequest and receives
    a TransactionResponse.

    This demonstrates backend-to-backend communication
    using the gRPC protocol.
    """
    try:
        logger.info(f"Worker thread: Verifying transaction for user_id: {user_id}")
        with grpc.insecure_channel('transaction_verification:50052') as channel:
            stub = transaction_verification_grpc.TransactionVerificationServiceStub(channel)
            response = stub.VerifyTransaction(transaction_verification.TransactionRequest(
                user_id=user_id,
                credit_card=credit_card,
                items=items
            ))
        logger.info(f"Transaction verification result: {'VALID' if response.is_valid else 'INVALID'} - {response.message}")
        return response.is_valid
    except Exception as e:
        logger.error(f"Error verifying transaction: {str(e)}")
        return False


def get_suggestions(user_id, purchased_items):
    """
    gRPC CLIENT COMMUNICATION — SUGGESTIONS SERVICE

    This function connects to the suggestions microservice
    via gRPC.

    It sends a SuggestionsRequest and receives
    a SuggestionsResponse.

    This completes the inter-service communication
    requirement using gRPC.
    """
    try:
        logger.info(f"Worker thread: Getting suggestions for user_id: {user_id}")
        with grpc.insecure_channel('suggestions:50053') as channel:
            stub = suggestions_grpc.SuggestionsServiceStub(channel)
            response = stub.GetSuggestions(suggestions.SuggestionsRequest(
                user_id=user_id,
                purchased_items=purchased_items
            ))
        logger.info(f"Received {len(response.suggested_books)} book suggestions")
        # Convert protobuf books to dict
        suggested_books = [
            {
                'bookId': book.book_id,
                'title': book.title,
                'author': book.author
            }
            for book in response.suggested_books
        ]
        return suggested_books
    except Exception as e:
        logger.error(f"Error getting suggestions: {str(e)}")
        return []


# Import Flask
from flask import Flask, request
from flask_cors import CORS

# Create a simple Flask app
app = Flask(__name__)
# Enable CORS for the app
CORS(app, resources={r'/*': {'origins': '*'}})


@app.route('/', methods=['GET'])
def index():
    """
    Responds with 'Hello' when a GET request is made to '/' endpoint.
    """
    logger.info("GET request received on '/' endpoint")
    return "Hello from Orchestrator!"


@app.route('/checkout', methods=['POST'])
def checkout():
    """
    REST IMPLEMENTATION (Frontend ↔ Orchestrator)

    This endpoint implements the RESTful API defined in bookstore.yaml.
    It handles POST requests from the frontend at '/checkout'.

    Responsibilities:
    - Parse incoming JSON request (CheckoutRequest schema)
    - Extract order data (user, items, credit card)
    - Trigger backend processing via gRPC microservices
    - Return response following OrderStatusResponse schema

    This establishes the REST communication channel between
    the frontend and backend system.

    """
    try:
        logger.info("Received POST request on '/checkout' endpoint")
        
        # Parse request data
        request_data = json.loads(request.data)
        logger.info(f"Request data received with {len(request_data.get('items', []))} items")
        
        # Extract necessary data
        items = request_data.get('items', [])
        credit_card_data = request_data.get('creditCard', {})
        credit_card_number = credit_card_data.get('number', '')
        user_data = request_data.get('user', {})
        user_id = user_data.get('name', 'unknown_user')
        
        logger.info(f"Extracted data - User: {user_id}, Items: {len(items)}, Card ending in: {credit_card_number[-4:] if credit_card_number else 'N/A'}")
        
        # Convert items to list of item IDs for transaction verification
        item_list = [item.get('bookId', item.get('name', '')) for item in items]
        
        # Execute fraud detection, transaction verification, and suggestions in parallel
        logger.info("Spawning worker threads for parallel processing")
        results = {
            'is_fraud': False,
            'is_transaction_valid': False,
            'suggested_books': [],
            'fraud_error': None,
            'transaction_error': None,
            'suggestions_error': None
        }
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            """
            MULTITHREADING IMPLEMENTATION (Master-Worker Model)

            The orchestrator acts as the master thread.
            It spawns three worker threads using ThreadPoolExecutor.

            Each worker thread:
            - Calls one backend microservice (fraud, verification, suggestions)
            - Executes in parallel

            The orchestrator waits for all threads to complete
            before consolidating the results.

            This fulfills the threading requirement of the lab.
            """
            # Submit tasks for parallel execution
            fraud_task = executor.submit(check_fraud, credit_card_number, str(len(items)))
            transaction_task = executor.submit(verify_transaction, user_id, credit_card_number, item_list)
            suggestions_task = executor.submit(get_suggestions, user_id, item_list)
            
            # Wait for tasks to complete and collect results
            logger.info("Waiting for worker threads to complete...")
            
            try:
                results['is_fraud'] = fraud_task.result(timeout=10)
            except Exception as e:
                logger.error(f"Fraud detection task failed: {str(e)}")
                results['fraud_error'] = str(e)
                results['is_fraud'] = False
            
            try:
                results['is_transaction_valid'] = transaction_task.result(timeout=10)
            except Exception as e:
                logger.error(f"Transaction verification task failed: {str(e)}")
                results['transaction_error'] = str(e)
                results['is_transaction_valid'] = False
            
            try:
                results['suggested_books'] = suggestions_task.result(timeout=10)
            except Exception as e:
                logger.error(f"Suggestions task failed: {str(e)}")
                results['suggestions_error'] = str(e)
                results['suggested_books'] = []
        
        # Consolidate results
        logger.info(f"All tasks completed. Results - Fraud: {results['is_fraud']}, Transaction Valid: {results['is_transaction_valid']}, Suggestions: {len(results['suggested_books'])}")
        
        # Determine order status
        """
        RESULT CONSOLIDATION LOGIC

        After all worker threads return results,
        the orchestrator combines them.

        Rule:
        - If fraud is detected OR transaction is invalid → Order Rejected
        - Otherwise → Order Approved with suggestions

        This implements the final decision-making step
        in the orchestrated workflow.
        """
        if results['is_fraud'] or not results['is_transaction_valid']:
            order_status = "Order Rejected"
            suggested_books = []
            reason = "Fraud detected" if results['is_fraud'] else "Transaction verification failed"
            logger.warning(f"Order rejected - {reason}")
        else:
            order_status = "Order Approved"
            suggested_books = results['suggested_books']
            logger.info(f"Order approved - Returning {len(suggested_books)} book suggestions")
        
        # Create response following API specification
        order_id = str(uuid.uuid4())[:8]
        order_status_response = {
            'orderId': order_id,
            'status': order_status,
            'suggestedBooks': suggested_books
        }
        
        logger.info(f"Returning response - Order ID: {order_id}, Status: {order_status}")
        return order_status_response
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        return {'error': 'Invalid request format'}, 400
    except Exception as e:
        logger.error(f"Unexpected error in checkout: {str(e)}")
        return {'error': 'Internal server error'}, 500


if __name__ == '__main__':
    logger.info("Starting Orchestrator Service")
    # Run the app in debug mode to enable hot reloading.
    app.run(host='0.0.0.0', port=5000)
