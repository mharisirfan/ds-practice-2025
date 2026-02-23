from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SuggestionsRequest(_message.Message):
    __slots__ = ("user_id", "purchased_items")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PURCHASED_ITEMS_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    purchased_items: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, user_id: _Optional[str] = ..., purchased_items: _Optional[_Iterable[str]] = ...) -> None: ...

class Book(_message.Message):
    __slots__ = ("book_id", "title", "author")
    BOOK_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    book_id: str
    title: str
    author: str
    def __init__(self, book_id: _Optional[str] = ..., title: _Optional[str] = ..., author: _Optional[str] = ...) -> None: ...

class SuggestionsResponse(_message.Message):
    __slots__ = ("suggested_books",)
    SUGGESTED_BOOKS_FIELD_NUMBER: _ClassVar[int]
    suggested_books: _containers.RepeatedCompositeFieldContainer[Book]
    def __init__(self, suggested_books: _Optional[_Iterable[_Union[Book, _Mapping]]] = ...) -> None: ...
