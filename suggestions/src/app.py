import sys
import os
import grpc
from concurrent import futures
import logging
import threading

FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
suggestions_grpc_path = os.path.abspath(os.path.join(FILE, "../../../utils/pb/suggestions"))
sys.path.insert(0, suggestions_grpc_path)
import suggestions_pb2 as pb
import suggestions_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SERVICE_KEY = "suggestions"
EVENT_MARKERS = {
    "e": "evt_e_done",
    "f": "evt_f_done",
}

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

ITEM_CATEGORY_MAP = {
    "science_book": "science",
    "history_book": "history",
    "fiction_book": "fiction",
    "tech_book": "technology",
}


def merge_clocks(*clocks):
    """Merge vector clocks by taking the component-wise maximum."""
    merged = {}
    for clock in clocks:
        for key, value in clock.items():
            merged[key] = max(merged.get(key, 0), int(value))
    return merged


def clock_lte(local_clock, final_clock):
    """Return True when local clock is less than or equal to VCf for all keys."""
    keys = set(local_clock.keys()) | set(final_clock.keys())
    for key in keys:
        if local_clock.get(key, 0) > final_clock.get(key, 0):
            return False
    return True


def get_suggested_books(purchased_items):
    """Produce deterministic demo recommendations from purchased item categories."""
    interested_categories = set()
    for item in purchased_items:
        for item_type, category in ITEM_CATEGORY_MAP.items():
            if item_type in item.lower():
                interested_categories.add(category)
                break

    if not interested_categories:
        interested_categories = set(BOOK_CATALOG.keys())

    output = []
    for category in interested_categories:
        output.extend(BOOK_CATALOG.get(category, [])[:2])
    return output[:5]


class SuggestionsServicer(pb_grpc.SuggestionsServiceServicer):
    def __init__(self):
        """Store per-order cached payload and per-order vector clock state."""
        self.order_cache = {}
        self.order_clocks = {}
        self.order_events = {}
        self.lock = threading.Lock()

    @staticmethod
    def _clock_msg(clock_dict):
        """Convert dictionary clock into protobuf vector clock message."""
        msg = pb.VectorClock()
        msg.clock.update(clock_dict)
        return msg

    def _merge_incoming(self, order_id, incoming_clock):
        """Merge incoming clock with local order clock before processing an event."""
        current = self.order_clocks.get(order_id, {})
        merged = merge_clocks(current, incoming_clock)
        self.order_clocks[order_id] = merged
        return dict(merged)

    def _tick(self, order_id, event_name):
        """Advance local service component for the current order event and log it."""
        clock = self.order_clocks.get(order_id, {})
        clock[SERVICE_KEY] = clock.get(SERVICE_KEY, 0) + 1
        self.order_clocks[order_id] = clock
        logger.info("Event %s | order_id=%s | VC=%s", event_name, order_id, clock)
        return dict(clock)

    def _causal_violation(self, order_id, event_name, reason, clock):
        """Build a consistent causal-violation response and log it."""
        logger.warning("Causal violation | event=%s | order_id=%s | reason=%s | VC=%s", event_name, order_id, reason, clock)
        return pb.SuggestionsResponse(
            ok=False,
            message=f"Causal violation: {reason}",
            vector_clock=self._clock_msg(clock),
        )

    def InitOrder(self, request, context):
        """Cache order input and initialize vector-clock tracking for this service."""
        with self.lock:
            self.order_cache[request.order_id] = {
                "user_id": request.user_id,
                "purchased_items": list(request.purchased_items),
            }
            self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            clock = self._tick(request.order_id, "init")
            self.order_events[request.order_id] = {"done": {"init"}}

        return pb.InitOrderResponse(success=True, message="Suggestions order initialized", vector_clock=self._clock_msg(clock))

    def GenerateSuggestions(self, request, context):
        """Event f: generate suggestions after upstream checks have passed."""
        with self.lock:
            data = self.order_cache.get(request.order_id)
            merged = self._merge_incoming(request.order_id, dict(request.vector_clock.clock))
            state = self.order_events.get(request.order_id)

            if data is None or state is None:
                return pb.SuggestionsResponse(ok=False, message="Order not initialized", vector_clock=self._clock_msg(merged))

            has_e_vc = merged.get(EVENT_MARKERS["e"], 0) >= 1
            if not has_e_vc:
                return self._causal_violation(
                    request.order_id,
                    "f_generate_suggestions",
                    "event f requires completed event e",
                    merged,
                )

            if "f" in state["done"]:
                return self._causal_violation(request.order_id, "f_generate_suggestions", "event f already executed", merged)

            clock = self._tick(request.order_id, "f_generate_suggestions")

        books = get_suggested_books(data["purchased_items"])

        with self.lock:
            state = self.order_events.get(request.order_id)
            if state is not None:
                state["done"].add("f")
            clock = self.order_clocks.get(request.order_id, {})
            clock[EVENT_MARKERS["f"]] = 1
            self.order_clocks[request.order_id] = clock
            out = dict(clock)

        response = pb.SuggestionsResponse(ok=True, message="Suggestions generated", vector_clock=self._clock_msg(out))
        for book in books:
            item = response.suggested_books.add()
            item.book_id = book["id"]
            item.title = book["title"]
            item.author = book["author"]

        return response

    def ClearOrder(self, request, context):
        """Clear cached order state only when local VC is causally <= VCf."""
        with self.lock:
            local = self.order_clocks.get(request.order_id, {})
            final_clock = dict(request.final_vector_clock.clock)
            if not clock_lte(local, final_clock):
                logger.error("ClearOrder rejected | order_id=%s | local=%s | VCf=%s", request.order_id, local, final_clock)
                return pb.ClearOrderResponse(
                    success=False,
                    message="Local VC is greater than VCf; refusing to clear",
                    vector_clock=self._clock_msg(local),
                )

            self.order_cache.pop(request.order_id, None)
            self.order_clocks.pop(request.order_id, None)
            self.order_events.pop(request.order_id, None)

        logger.info("ClearOrder success | order_id=%s | VCf=%s", request.order_id, final_clock)
        return pb.ClearOrderResponse(success=True, message="Order state cleared", vector_clock=self._clock_msg(final_clock))


def serve():
    """Start gRPC server for suggestions service."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsServicer(), server)
    server.add_insecure_port("[::]:50053")
    server.start()
    logger.info("Suggestions Service started on port 50053")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
