from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PingRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("executor_id", "leader_id", "is_leader", "status")
    EXECUTOR_ID_FIELD_NUMBER: _ClassVar[int]
    LEADER_ID_FIELD_NUMBER: _ClassVar[int]
    IS_LEADER_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    executor_id: str
    leader_id: str
    is_leader: bool
    status: str
    def __init__(self, executor_id: _Optional[str] = ..., leader_id: _Optional[str] = ..., is_leader: bool = ..., status: _Optional[str] = ...) -> None: ...
