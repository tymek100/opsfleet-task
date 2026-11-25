"""Exercise actual keyboard events; selection must not submit commands."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from retail_insight.interfaces.terminal import SlashCommandCompleter, create_prompt_session


@asynccontextmanager
async def prompt():
    with create_pipe_input() as pipe:
        session = create_prompt_session(input=pipe, output=DummyOutput())
        task = asyncio.create_task(session.prompt_async())
        try:
            yield session, pipe, task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def observed(session, predicate):
    if predicate():
        return
    ready = asyncio.get_running_loop().create_future()

    def check(_sender):
        if predicate() and not ready.done():
            ready.set_result(None)

    events = [
        session.default_buffer.on_text_changed,
        session.default_buffer.on_completions_changed,
        session.app.after_render,
    ]
    for event in events:
        event += check
    try:
        await asyncio.wait_for(ready, timeout=2)
    finally:
        for event in events:
            event -= check


def test_fuzzy_filter_marks_only_typed_matching_characters():
    matches = list(SlashCommandCompleter().get_completions(Document("/rp"), CompleteEvent()))
    assert [match.text for match in matches] == ["/reports"]
    marked = "".join(
        text
        for style, text, *_ in to_formatted_text(matches[0].display)
        if "fuzzymatch.inside.character" in style
    )
    assert marked == "/rp"


@pytest.mark.parametrize(
    "value", ["Compare revenue", "Show /reports", "/confirm exact-token", "/unknown"]
)
def test_normal_text_and_arguments_are_not_command_completions(value):
    assert list(SlashCommandCompleter().get_completions(Document(value), CompleteEvent())) == []


@pytest.mark.parametrize(
    "prefix,key,expected",
    [
        ("/", "\x1b[B\r", "/help"),
        ("/rp", "\t", "/reports"),
        ("/conf", "\x1b[B\r", "/confirm "),
    ],
)
async def test_selecting_with_arrows_or_tab_never_executes(prefix, key, expected):
    async with prompt() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text(prefix)
        await observed(session, lambda: buffer.complete_state is not None)
        pipe.send_text(key)
        await observed(session, lambda: buffer.text == expected and buffer.complete_state is None)
        assert not task.done()
        if expected.endswith(" "):
            pipe.send_text("trusted-token")
        pipe.send_text("\r")
        assert await asyncio.wait_for(task, 2) == expected + (
            "trusted-token" if expected.endswith(" ") else ""
        )


async def test_escape_restores_typed_filter_after_arrow_selection():
    async with prompt() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text("/de")
        await observed(session, lambda: buffer.complete_state is not None)
        pipe.send_text("\x1b[B")
        await observed(session, lambda: buffer.text != "/de")
        pipe.send_text("\x1b")
        await observed(session, lambda: buffer.text == "/de" and buffer.complete_state is None)
        assert not task.done()
