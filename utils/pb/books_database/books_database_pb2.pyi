from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ReadRequest(_message.Message):
    __slots__ = ("title",)
    TITLE_FIELD_NUMBER: _ClassVar[int]
    title: str
    def __init__(self, title: _Optional[str] = ...) -> None: ...

class ReadResponse(_message.Message):
    __slots__ = ("success", "message", "stock", "version")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STOCK_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    stock: int
    version: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., stock: _Optional[int] = ..., version: _Optional[int] = ...) -> None: ...

class WriteRequest(_message.Message):
    __slots__ = ("title", "new_stock", "client_id", "order_id")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    NEW_STOCK_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    title: str
    new_stock: int
    client_id: str
    order_id: str
    def __init__(self, title: _Optional[str] = ..., new_stock: _Optional[int] = ..., client_id: _Optional[str] = ..., order_id: _Optional[str] = ...) -> None: ...

class WriteResponse(_message.Message):
    __slots__ = ("success", "message", "version")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    version: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., version: _Optional[int] = ...) -> None: ...

class ReplicateWriteRequest(_message.Message):
    __slots__ = ("title", "new_stock", "client_id", "order_id", "version")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    NEW_STOCK_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    title: str
    new_stock: int
    client_id: str
    order_id: str
    version: int
    def __init__(self, title: _Optional[str] = ..., new_stock: _Optional[int] = ..., client_id: _Optional[str] = ..., order_id: _Optional[str] = ..., version: _Optional[int] = ...) -> None: ...

class ReplicateWriteResponse(_message.Message):
    __slots__ = ("success", "message", "version")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    version: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., version: _Optional[int] = ...) -> None: ...

class PingRequest(_message.Message):
    __slots__ = ("replica_id",)
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    replica_id: str
    def __init__(self, replica_id: _Optional[str] = ...) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("alive", "replica_id", "is_primary", "replica_count")
    ALIVE_FIELD_NUMBER: _ClassVar[int]
    REPLICA_ID_FIELD_NUMBER: _ClassVar[int]
    IS_PRIMARY_FIELD_NUMBER: _ClassVar[int]
    REPLICA_COUNT_FIELD_NUMBER: _ClassVar[int]
    alive: bool
    replica_id: str
    is_primary: bool
    replica_count: int
    def __init__(self, alive: bool = ..., replica_id: _Optional[str] = ..., is_primary: bool = ..., replica_count: _Optional[int] = ...) -> None: ...
