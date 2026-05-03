from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PrepareRequest(_message.Message):
    __slots__ = ("order_id", "amount")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    amount: int
    def __init__(self, order_id: _Optional[str] = ..., amount: _Optional[int] = ...) -> None: ...

class PrepareResponse(_message.Message):
    __slots__ = ("ready", "message")
    READY_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ready: bool
    message: str
    def __init__(self, ready: bool = ..., message: _Optional[str] = ...) -> None: ...

class CommitRequest(_message.Message):
    __slots__ = ("order_id",)
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    def __init__(self, order_id: _Optional[str] = ...) -> None: ...

class CommitResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class AbortRequest(_message.Message):
    __slots__ = ("order_id",)
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    def __init__(self, order_id: _Optional[str] = ...) -> None: ...

class AbortResponse(_message.Message):
    __slots__ = ("aborted", "message")
    ABORTED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    aborted: bool
    message: str
    def __init__(self, aborted: bool = ..., message: _Optional[str] = ...) -> None: ...

class TransactionStatusRequest(_message.Message):
    __slots__ = ("order_id",)
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    def __init__(self, order_id: _Optional[str] = ...) -> None: ...

class TransactionStatusResponse(_message.Message):
    __slots__ = ("order_id", "state")
    ORDER_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    order_id: str
    state: str
    def __init__(self, order_id: _Optional[str] = ..., state: _Optional[str] = ...) -> None: ...
