from abc import ABC, abstractmethod
from asyncio import Task
from typing import (
    IO,
    Any,
    AsyncContextManager,
    Coroutine,
    Generic,
    Mapping,
    Protocol,
    Type,
    TypeVar,
)

T = TypeVar("T")

ArgsT = TypeVar("ArgsT")
OptsT = TypeVar("OptsT")
ActorT = TypeVar("ActorT")


class Context(Protocol):
    def open_file(self, name: str, mode: str = "r") -> IO:
        ...

    def create_task(self, coro: Coroutine[Any, Any, T]) -> Task[T]:
        ...


class DependsError(Exception):
    ...


class Resource(Generic[ArgsT, OptsT, ActorT], ABC):
    def __init__(self, ctx: Context):
        self.ctx = ctx

    @classmethod
    @abstractmethod
    def init(
        cls: Type[T], ctx: Context, depends: Mapping[str, Any], args: ArgsT
    ) -> AsyncContextManager[T]:
        ...

    @abstractmethod
    def set_up(
        self,
        ctx: Context,
        depends: Mapping[str, Any],
        opts: OptsT,
    ) -> AsyncContextManager[ActorT]:
        ...
