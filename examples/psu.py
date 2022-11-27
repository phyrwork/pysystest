from __future__ import annotations

from asyncio import CancelledError, Queue, Task, sleep
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Generic,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Type,
    TypeVar,
)

from aiohttp.client import URL, ClientSession

from pysystest import testing

T = TypeVar("T")


@asynccontextmanager
async def cancel(task: Task) -> AsyncIterator[None]:
    try:
        yield None
    finally:
        task.cancel()
        with suppress(CancelledError):
            await task


class Events(Generic[T]):
    def __init__(self) -> None:
        self.callbacks: Set[Callable[[T], None]] = set()

    @contextmanager
    def callback(self, cb: Callable[[T], None]) -> Iterator[None]:
        if cb in self.callbacks:
            raise Exception
        self.callbacks.add(cb)
        try:
            yield None
        finally:
            self.callbacks.remove(cb)

    @contextmanager
    def queue(self, queue: Optional["Queue[T]"] = None) -> Iterator["Queue[T]"]:
        if not queue:
            queue = Queue()
        with self.callback(queue.put_nowait):
            yield queue

    def emit(self, status: T) -> None:
        for cb in self.callbacks:
            cb(status)


@dataclass
class OutputStatus:
    current: Decimal
    voltage: Decimal
    enabled: bool


class OutputActor:
    def __init__(
        self,
        ctx: testing.Context,
        events: Events[OutputStatus],
        client: ClientSession,
        port: int,
    ) -> None:
        self.ctx = ctx
        self.events = events
        self.client = client
        self.port = port

    async def on(self) -> None:
        ...

    async def off(self) -> None:
        ...

    async def status(self) -> OutputStatus:
        raise NotImplementedError


@dataclass
class SupplyStatus:
    current: Decimal
    voltage: Decimal


@dataclass
class BaseStatus:
    supplies: Optional[SupplyStatus]
    outputs: List[OutputStatus]


class BaseActor:
    def __init__(
        self, ctx: testing.Context, events: Events[BaseStatus], client: ClientSession
    ) -> None:
        self.ctx = ctx
        self.events = events
        self.client = client

    async def status(self) -> BaseStatus:
        raise NotImplementedError


@dataclass
class OutputArgs:
    port: int


@dataclass
class OutputOpts:
    ...


class OutputResource(testing.Resource[OutputArgs, OutputOpts, OutputActor]):
    def __init__(self, ctx: testing.Context, port: int) -> None:
        super().__init__(ctx)
        self.events: Events[OutputStatus] = Events()
        self.port = port

    @classmethod
    @asynccontextmanager
    async def init(
        cls, ctx: testing.Context, depends: Mapping[str, Any], args: OutputArgs
    ) -> AsyncIterator[OutputResource]:
        base = depends.get("base")
        if not isinstance(base, BaseResource):
            raise TypeError

        output = OutputResource(ctx, args.port)

        def handle(status: BaseStatus) -> None:
            output.events.emit(status.outputs[args.port])

        with base.events.callback(handle):
            yield output

    @asynccontextmanager
    async def set_up(
        self, ctx: testing.Context, depends: Mapping[str, Any], opts: OutputOpts
    ) -> AsyncIterator[OutputActor]:
        base = depends.get("base")
        if not isinstance(base, BaseActor):
            raise TypeError
        yield OutputActor(ctx, self.events, base.client, self.port)


@dataclass
class BaseArgs:
    url: str
    poll: float = 1


@dataclass
class BaseOpts:
    ...


class BaseResource(testing.Resource[BaseArgs, BaseOpts, BaseActor]):
    def __init__(self, ctx: testing.Context, url: URL) -> None:
        super().__init__(ctx)
        self.events: Events[BaseStatus] = Events()
        self.polling: Optional[Task] = None
        self.url = url

    def init_client(self) -> ClientSession:
        return ClientSession(self.url)

    @cached_property
    def client(self) -> ClientSession:
        return self.init_client()

    async def status(self) -> BaseStatus:
        raise NotImplementedError

    async def poll(self, interval: float) -> None:
        while True:
            await sleep(interval)
            status = await self.status()
            self.events.emit(status)

    async def __aenter__(self) -> BaseResource:
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if client := self.__dict__.get("client"):
            assert isinstance(client, ClientSession)
            await client.close()
        return None

    @classmethod
    @asynccontextmanager
    async def init(
        cls, ctx: testing.Context, depends: Mapping[str, Any], args: BaseArgs
    ) -> AsyncIterator[BaseResource]:
        base = BaseResource(ctx, URL(args.url))
        async with cancel(ctx.create_task(base.poll(args.poll))):
            yield base

    @asynccontextmanager
    async def set_up(
        self, ctx: testing.Context, depends: Mapping[str, Any], opts: BaseOpts
    ) -> AsyncIterator[BaseActor]:
        async with self.init_client() as client:
            yield BaseActor(ctx, self.events, client)
