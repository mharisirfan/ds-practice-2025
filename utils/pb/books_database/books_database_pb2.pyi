from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ReadRequest(_message.Message):
    __slots__ = ("title",)
    TITLE_FIELD_NUMBER: _ClassVar[int]
    title: str
    def __init__(self, title: _Optional[str] = ...) -> None: ...

class ReadResponse(_message.Message):
    __slots__ = ("stock",)
    STOCK_FIELD_NUMBER: _ClassVar[int]
    stock: int
    def __init__(self, stock: _Optional[int] = ...) -> None: ...

class WriteRequest(_message.Message):
    __slots__ = ("title", "new_stock", "expected_stock", "is_replica_sync")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    NEW_STOCK_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_STOCK_FIELD_NUMBER: _ClassVar[int]
    IS_REPLICA_SYNC_FIELD_NUMBER: _ClassVar[int]
    title: str
    new_stock: int
    expected_stock: int
    is_replica_sync: bool
    def __init__(self, title: _Optional[str] = ..., new_stock: _Optional[int] = ..., expected_stock: _Optional[int] = ..., is_replica_sync: bool = ...) -> None: ...

class WriteResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class PrepareRequest(_message.Message):
    __slots__ = ("order_id", "items", "is_replica_sync")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    IS_REPLICA_SYNC_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    items: _containers.RepeatedScalarFieldContainer[str]
    is_replica_sync: bool
    def __init__(self, order_id: _Optional[str] = ..., items: _Optional[_Iterable[str]] = ..., is_replica_sync: bool = ...) -> None: ...

class PrepareResponse(_message.Message):
    __slots__ = ("ready", "message")
    READY_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ready: bool
    message: str
    def __init__(self, ready: bool = ..., message: _Optional[str] = ...) -> None: ...

class CommitRequest(_message.Message):
    __slots__ = ("order_id", "is_replica_sync")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_REPLICA_SYNC_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    is_replica_sync: bool
    def __init__(self, order_id: _Optional[str] = ..., is_replica_sync: bool = ...) -> None: ...

class CommitResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class AbortRequest(_message.Message):
    __slots__ = ("order_id", "is_replica_sync")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_REPLICA_SYNC_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    is_replica_sync: bool
    def __init__(self, order_id: _Optional[str] = ..., is_replica_sync: bool = ...) -> None: ...

class AbortResponse(_message.Message):
    __slots__ = ("aborted", "message")
    ABORTED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    aborted: bool
    message: str
    def __init__(self, aborted: bool = ..., message: _Optional[str] = ...) -> None: ...
