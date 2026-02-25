import sys
import os
import grpc
from concurrent import futures
import logging

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/suggestions'))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2
import suggestions_pb2_grpc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Sample book catalog with categories
BOOK_CATALOG = {
    "fiction": [
        {"id": "B001", "title": "The Great Gatsby", "author": "F. Scott Fitzgerald"},
        {"id": "B002", "title": "To Kill a Mockingbird", "author": "Harper Lee"},
        {"id": "B003", "title": "1984", "author": "George Orwell"},
        {"id": "B004", "title": "The Catcher in the Rye", "author": "J.D. Salinger"},
    ],
    "science": [
        {"id": "B005", "title": "A Brief History of Time", "author": "Stephen Hawking"},
        {"id": "B006", "title": "The Selfish Gene", "author": "Richard Dawkins"},
        {"id": "B007", "title": "Cosmos", "author": "Carl Sagan"},
        {"id": "B008", "title": "The Elegant Universe", "author": "Brian Greene"},
    ],
    "history": [
        {"id": "B009", "title": "Sapiens", "author": "Yuval Noah Harari"},
        {"id": "B010", "title": "The Rise and Fall of the Third Reich", "author": "William Shirer"},
        {"id": "B011", "title": "Guns, Germs, and Steel", "author": "Jared Diamond"},
        {"id": "B012", "title": "The History of the Decline and Fall of the Roman Empire", "author": "Edward Gibbon"},
    ],
    "technology": [
        {"id": "B013", "title": "The Innovators", "author": "Walter Isaacson"},
        {"id": "B014", "title": "Code: The Hidden Language", "author": "Charles Petzold"},
        {"id": "B015", "title": "Clean Code", "author": "Robert C. Martin"},
        {"id": "B016", "title": "The Pragmatic Programmer", "author": "David Thomas & Andrew Hunt"},
    ],
}

# Map items to book categories for intelligent suggestions
ITEM_CATEGORY_MAP = {
    "science_book": "science",
    "history_book": "history",
    "fiction_book": "fiction",
    "tech_book": "technology",
}


def get_suggested_books(purchased_items):
    """
    gRPC BACKEND MICROSERVICE — SUGGESTIONS

    This service runs as a gRPC server on port 50053.

    It generates book suggestions based on purchased items
    and returns a list of recommended books.

    It implements the SuggestionsService defined
    in suggestions.proto.

    This fulfills the third required backend microservice.
    """
    
    logger.info(f"Generating suggestions for items: {purchased_items}")
    
    # Determine which categories the user is interested in
    interested_categories = set()
    
    for item in purchased_items:
        item_lower = item.lower()
        for item_type, category in ITEM_CATEGORY_MAP.items():
            if item_type in item_lower:
                interested_categories.add(category)
                break
    
    # If no specific category found, suggest a mix
    if not interested_categories:
        interested_categories = set(BOOK_CATALOG.keys())
    
    logger.info(f"Determined interested categories: {interested_categories}")
    
    # Select 2 books from each interested category
    suggestions = []
    for category in interested_categories:
        category_books = BOOK_CATALOG.get(category, [])
        # Take first 2 books from each category
        suggestions.extend(category_books[:2])
    
    # Limit to 5 suggestions max
    suggestions = suggestions[:5]
    logger.info(f"Generated {len(suggestions)} book suggestions")
    
    return suggestions


class SuggestionsServicer(suggestions_pb2_grpc.SuggestionsServiceServicer):
    """
    gRPC service for book suggestions.
    Provides intelligent book recommendations based on user purchase history.
    """
    
    def GetSuggestions(self, request, context):
        """
        RPC method to get book suggestions for a user.
        
        Args:
            request: SuggestionsRequest with user_id and purchased_items
            context: gRPC context
        
        Returns:
            SuggestionsResponse with list of suggested books
        """
        logger.info(f"Received suggestion request for user_id: {request.user_id}")
        logger.info(f"Purchased items: {list(request.purchased_items)}")
        
        try:
            # Get suggested books
            suggested_books = get_suggested_books(list(request.purchased_items))
            
            # Create response
            response = suggestions_pb2.SuggestionsResponse()
            for book in suggested_books:
                book_pb = response.suggested_books.add()
                book_pb.book_id = book['id']
                book_pb.title = book['title']
                book_pb.author = book['author']
            
            logger.info(f"Returning {len(response.suggested_books)} suggestions to user {request.user_id}")
            return response
            
        except Exception as e:
            logger.error(f"Error generating suggestions: {str(e)}")
            return suggestions_pb2.SuggestionsResponse()


def serve():
    """
    Start the gRPC server for the Suggestions service.
    Listens on port 50053.
    """
    logger.info("Starting Suggestions Service...")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    suggestions_pb2_grpc.add_SuggestionsServiceServicer_to_server(
        SuggestionsServicer(), server
    )
    server.add_insecure_port("[::]:50053")
    server.start()
    logger.info("Suggestions Service started on port 50053")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
