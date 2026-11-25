"""Interactive command discovery without submitting or authorizing operations."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, FuzzyWordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_completions
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    argument: str = ""

    @property
    def usage(self) -> str:
        return f"{self.name} {self.argument}" if self.argument else self.name


COMMANDS = (
    Command("/help", "Show commands"),
    Command("/details", "Inspect the latest query evidence"),
    Command("/reports", "List your saved reports"),
    Command("/read", "Read a saved report", "ID"),
    Command("/delete", "Preview reports matching this text", "TEXT"),
    Command("/confirm", "Confirm the exact previewed deletion", "TOKEN"),
    Command("/cancel", "Cancel the pending deletion"),
    Command("/new", "Clear this conversation"),
    Command("/exit", "Exit"),
    Command("/quit", "Exit (alias for /exit)"),
)


def command_help(commands: Sequence[Command] = COMMANDS) -> str:
    lines = ["Commands:", *(f"{c.usage:<18}{c.description}" for c in commands)]
    lines.extend(
        [
            "Type / to browse commands; keep typing to filter, then use arrows and Enter or Tab.",
            "Selecting a command fills the input. Press Enter again to run it.",
            "Ask naturally to analyze data, create a report, or explicitly save an answer.",
        ]
    )
    return "\n".join(lines) + "\n"


def _command_token(document: Document) -> bool:
    return (
        document.text.startswith("/")
        and document.cursor_position == len(document.text)
        and not any(character.isspace() for character in document.text)
    )


class SlashCommandCompleter(Completer):
    """Offer command names only; arguments and natural-language questions stay untouched."""

    def __init__(self, commands: Sequence[Command] = COMMANDS) -> None:
        self._completer = FuzzyWordCompleter(
            [command.name for command in commands],
            meta_dict={
                command.name: (
                    f"{command.argument} — {command.description}"
                    if command.argument
                    else command.description
                )
                for command in commands
            },
            WORD=True,
        )

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        if _command_token(document):
            yield from self._completer.get_completions(document, complete_event)


def create_prompt_session(
    *,
    commands: Sequence[Command] = COMMANDS,
    input: Input | None = None,
    output: Output | None = None,
) -> PromptSession[str]:
    bindings = KeyBindings()
    command_token = Condition(lambda: _command_token(get_app().current_buffer.document))

    def accept_completion(buffer: Buffer, *, first: bool = False) -> None:
        state = buffer.complete_state
        if state is None:
            return
        completion = state.current_completion
        if completion is None and first and state.completions:
            completion = state.completions[0]
            buffer.go_to_completion(0)
        if completion is not None:
            # Arrow navigation already inserts the selected completion. Commit it
            # without triggering a new completion task or submitting the input.
            buffer.complete_state = None
            if any(command.name == completion.text and command.argument for command in commands):
                buffer.insert_text(" ", fire_event=False)

    @bindings.add("down", filter=command_token)
    def next_command(event: KeyPressEvent) -> None:
        if event.current_buffer.complete_state is None:
            event.current_buffer.start_completion(select_first=True)
        else:
            event.current_buffer.complete_next()

    @bindings.add("up", filter=command_token)
    def previous_command(event: KeyPressEvent) -> None:
        if event.current_buffer.complete_state is None:
            event.current_buffer.start_completion(select_last=True)
        else:
            event.current_buffer.complete_previous()

    @bindings.add("enter", filter=has_completions)
    def accept_or_submit(event: KeyPressEvent) -> None:
        state = event.current_buffer.complete_state
        if state is not None and state.current_completion is not None:
            accept_completion(event.current_buffer)
        else:
            event.current_buffer.validate_and_handle()

    @bindings.add("tab", filter=command_token)
    def complete_command(event: KeyPressEvent) -> None:
        if event.current_buffer.complete_state is None:
            event.current_buffer.start_completion(select_first=True)
        else:
            accept_completion(event.current_buffer, first=True)

    @bindings.add("escape", filter=has_completions, eager=True)
    def dismiss(event: KeyPressEvent) -> None:
        event.current_buffer.cancel_completion()

    session = PromptSession[str](
        [("class:prompt", "You> ")],
        completer=SlashCommandCompleter(commands),
        complete_while_typing=command_token,
        enable_history_search=False,
        history=InMemoryHistory(),
        key_bindings=bindings,
        reserve_space_for_menu=0,
        style=Style.from_dict(
            {
                "prompt": "bold",
                "completion-menu.completion": "bg:#20252d #dce2ea",
                "completion-menu.completion.current": "bg:#42536d #ffffff bold reverse",
                "completion-menu.meta.completion": "bg:#20252d #aeb9ca",
                "completion-menu.meta.completion.current": "bg:#42536d #ffffff bold reverse",
                "fuzzymatch.inside.character": "bold #7dd3fc",
            }
        ),
        input=input,
        output=output,
    )

    def fit_menu(buffer: Buffer) -> None:
        state = buffer.complete_state
        session.reserve_space_for_menu = min(11, len(state.completions) + 1) if state else 0

    session.default_buffer.on_completions_changed += fit_menu
    session.app.before_render += lambda _app: fit_menu(session.default_buffer)
    return session
