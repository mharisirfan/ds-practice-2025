from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VectorClock(_message.Message):
    __slots__ = ("clock",)
    class ClockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    CLOCK_FIELD_NUMBER: _ClassVar[int]
    clock: _containers.ScalarMap[str, int]
    def __init__(self, clock: _Optional[_Mapping[str, int]] = ...) -> None: ...

class QueuedOrder(_message.Message):
    __slots__ = ("order_id", "user_id", "items", "vector_clock")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    user_id: str
    items: _containers.RepeatedScalarFieldContainer[str]
    vector_clock: VectorClock
    def __init__(self, order_id: _Optional[str] = ..., user_id: _Optional[str] = ..., items: _Optional[_Iterable[str]] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class EnqueueRequest(_message.Message):
    __slots__ = ("order",)
    ORDER_FIELD_NUMBER: _ClassVar[int]
    order: QueuedOrder
    def __init__(self, order: _Optional[_Union[QueuedOrder, _Mapping]] = ...) -> None: ...

class EnqueueResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class LeadershipRequest(_message.Message):
    __slots__ = ("executor_id", "lease_seconds")
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_SECONDS_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    lease_seconds: int
    def __init__(self, executor_id: _Optional[str] = ..., lease_seconds: _Optional[int] = ...) -> None: ...

class LeadershipResponse(_message.Message):
    __slots__ = ("granted", "leader_id", "lease_expiry_unix_ms", "message")
    GRANTED_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRY_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    granted: bool
    leader_id: str
    lease_expiry_unix_ms: int
    message: str
    def __init__(self, granted: bool = ..., leader_id: _Optional[str] = ..., lease_expiry_unix_ms: _Optional[int] = ..., message: _Optional[str] = ...) -> None: ...

class DequeueRequest(_message.Message):
    __slots__ = ("executor_id", "vector_clock")
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    VECTOR_CLOCK_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    vector_clock: VectorClock
    def __init__(self, executor_id: _Optional[str] = ..., vector_clock: _Optional[_Union[VectorClock, _Mapping]] = ...) -> None: ...

class DequeueResponse(_message.Message):
    __slots__ = ("success", "has_order", "message", "order")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    HAS_ORDER_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ORDER_FIELD_NUMBER: _ClassVar[int]
    success: bool
    has_order: bool
    message: str
    order: QueuedOrder
    def __init__(self, success: bool = ..., has_order: bool = ..., message: _Optional[str] = ..., order: _Optional[_Union[QueuedOrder, _Mapping]] = ...) -> None: ...
