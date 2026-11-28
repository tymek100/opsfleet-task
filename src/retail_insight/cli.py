"""Interactive retail chat with slash commands and Markdown answers."""

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

from retail_insight.agent import RetailAgent
from retail_insight.config import Settings
from retail_insight.tools.skills import SKILLS
from retail_insight.ui.progress import ThinkingStatus
from retail_insight.ui.terminal import command_help, create_prompt_session

app = typer.Typer(help="A small LangGraph retail analyst.", no_args_is_help=True)
console = Console()


@app.callback()
def main():
    """Analyze TheLook retail data using Gemini and BigQuery."""


def handle_command(text: str, agent: RetailAgent, last_answer: str) -> str:
    command, _, argument = text.partition(" ")
    match command.lower():
        case "/" | "/help":
            console.print(command_help(), markup=False)
        case "/new":
            agent.reset()
            last_answer = ""
            console.print("Started a new conversation.")
        case "/details":
            if agent.last_tools:
                console.print_json(json.dumps(agent.last_tools, default=str))
            else:
                console.print("No tool calls yet.")
        case "/skills":
            for name, description in SKILLS.items():
                console.print(f"{name}: {description}", markup=False)
        case "/save":
            if not argument.strip() or not last_answer:
                console.print("Use /save PATH after receiving an answer.")
            else:
                try:
                    path = Path(argument.strip()).expanduser()
                    with path.open("x") as file:
                        file.write(last_answer + "\n")
                    console.print(f"Saved {path}", markup=False)
                except OSError:
                    console.print("Could not save: choose a new file in an existing directory.")
        case _:
            console.print("Unknown command. Use /help.")
    return last_answer


@app.command()
def chat():
    """Start a conversation; type / to discover commands."""
    try:
        agent = RetailAgent(Settings.load())
    except ValueError as exc:
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from None
    session = create_prompt_session() if sys.stdin.isatty() and console.is_terminal else None
    console.print("Retail agent — Gemini + BigQuery. Type / for commands.")
    last_answer = ""
    with asyncio.Runner() as runner:
        try:
            while True:
                try:
                    question = (
                        session.prompt() if session else console.input("[bold]You> [/bold]")
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    break
                if question.lower() in {"/exit", "/quit"}:
                    break
                if not question:
                    continue
                if question.startswith("/"):
                    last_answer = handle_command(question, agent, last_answer)
                    continue
                console.print()
                try:
                    with console.status(ThinkingStatus(), spinner="dots"):
                        answer = runner.run(agent.ask(question))
                    last_answer = answer
                    console.print(Markdown(answer))
                except KeyboardInterrupt:
                    console.print("Stopped. You can ask another question.")
                except TimeoutError:
                    console.print("This request timed out. Try a narrower question.")
                except RuntimeError as exc:
                    console.print(str(exc), markup=False)
                except Exception as exc:
                    console.print(
                        f"Request failed ({type(exc).__name__}). Check your Google credentials and connection."
                    )
                console.print()
        finally:
            runner.run(agent.close())


if __name__ == "__main__":
    app()
