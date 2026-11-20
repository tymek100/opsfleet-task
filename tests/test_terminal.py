"""Command discovery and actual key handling without a terminal or model service."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.output import DummyOutput

from retail_agent.terminal import COMMANDS, SlashCommandCompleter, create_prompt_session


@asynccontextmanager
async def prompting() -> AsyncIterator[tuple[PromptSession[str], PipeInput, asyncio.Task[str]]]:
    with create_pipe_input() as pipe:
        session = create_prompt_session(input=pipe, output=DummyOutput())
        task = asyncio.create_task(session.prompt_async())
        try:
            yield session, pipe, task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def wait_for(session: PromptSession[str], predicate: Callable[[], bool]) -> None:
    """Observe real prompt events; no timing-sensitive sleeps or polling loops."""
    if predicate():
        return
    ready = asyncio.get_running_loop().create_future()

    def check(_sender) -> None:
        if predicate() and not ready.done():
            ready.set_result(None)

    events = (
        session.default_buffer.on_text_changed,
        session.default_buffer.on_completions_changed,
        session.app.after_render,
    )
    for event in events:
        event += check
    try:
        await asyncio.wait_for(ready, timeout=2)
    finally:
        for event in events:
            event -= check


def test_slash_completion_filters_fuzzy_characters_and_highlights_matches():
    completer = SlashCommandCompleter()
    all_commands = list(completer.get_completions(Document("/"), CompleteEvent()))
    assert [item.text for item in all_commands] == [command.name for command in COMMANDS]
    matches = list(completer.get_completions(Document("/rp"), CompleteEvent()))
    assert [item.text for item in matches] == ["/reports"]
    completion = matches[0]
    matched = "".join(
        text
        for style, text, *_ in to_formatted_text(completion.display)
        if "fuzzymatch.inside.character" in style
    )
    assert matched == "/rp"
    assert completion.start_position == -3
    assert completion.display_meta_text == "List your saved reports"


@pytest.mark.parametrize(
    "text", ["", "Compare our sales", "Show /reports", "/read report-one", "/confirm token", "/bad"]
)
def test_completion_does_not_modify_questions_arguments_or_unknown_commands(text: str):
    assert list(SlashCommandCompleter().get_completions(Document(text), CompleteEvent())) == []


@pytest.mark.asyncio
async def test_slash_opens_menu_and_arrows_then_enter_select_without_submitting():
    async with prompting() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text("/")
        await wait_for(session, lambda: buffer.complete_state is not None)
        assert buffer.complete_state is not None
        assert buffer.complete_state.complete_index is None
        assert len(buffer.complete_state.completions) == len(COMMANDS)
        assert session.reserve_space_for_menu > 0

        pipe.send_text("\x1b[B")
        await wait_for(session, lambda: buffer.text == "/help")
        pipe.send_text("\x1b[B")
        await wait_for(session, lambda: buffer.text == "/details")
        pipe.send_text("\x1b[A")
        await wait_for(session, lambda: buffer.text == "/help")
        pipe.send_text("\r")
        await wait_for(session, lambda: buffer.complete_state is None)
        assert buffer.text == "/help"
        assert not task.done()
        await wait_for(session, lambda: session.reserve_space_for_menu == 0)
        pipe.send_text("\r")
        assert await asyncio.wait_for(task, timeout=2) == "/help"


@pytest.mark.asyncio
async def test_typing_filters_menu_and_tab_inserts_command_without_submitting():
    async with prompting() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text("/rp")
        await wait_for(session, lambda: buffer.complete_state is not None)
        assert buffer.complete_state is not None
        assert [item.text for item in buffer.complete_state.completions] == ["/reports"]
        pipe.send_text("\t")
        await wait_for(session, lambda: buffer.text == "/reports" and buffer.complete_state is None)
        assert not task.done()
        pipe.send_text("\r")
        assert await asyncio.wait_for(task, timeout=2) == "/reports"


@pytest.mark.asyncio
async def test_argument_completion_never_inserts_a_confirmation_token_or_executes():
    async with prompting() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text("/conf")
        await wait_for(session, lambda: buffer.complete_state is not None)
        pipe.send_text("\x1b[B\r")
        await wait_for(session, lambda: buffer.text == "/confirm ")
        assert not task.done()
        assert buffer.complete_state is None
        pipe.send_text("exact-token\r")
        assert await asyncio.wait_for(task, timeout=2) == "/confirm exact-token"


@pytest.mark.asyncio
async def test_escape_dismisses_menu_and_restores_typed_filter():
    async with prompting() as (session, pipe, task):
        buffer = session.default_buffer
        pipe.send_text("/de")
        await wait_for(session, lambda: buffer.complete_state is not None)
        pipe.send_text("\x1b[B")
        await wait_for(session, lambda: buffer.text != "/de")
        pipe.send_text("\x1b")
        await wait_for(session, lambda: buffer.text == "/de" and buffer.complete_state is None)
        await wait_for(session, lambda: session.reserve_space_for_menu == 0)
        assert not task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/help", "/read exact-report-id", "Compare Q1 and Q4 revenue."])
async def test_enter_submits_explicit_text_without_an_extra_confirmation(text: str):
    async with prompting() as (_session, pipe, task):
        pipe.send_text(text + "\r")
        assert await asyncio.wait_for(task, timeout=2) == text
