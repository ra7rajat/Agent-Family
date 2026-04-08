"""
agent_family.runner
====================

CLI entry point for the Agent Family multi-agent system.

Usage::

    # Interactive REPL
    python -m agent_family.runner

    # Process a single prompt
    python -m agent_family.runner --prompt "Schedule a meeting tomorrow at 3pm"

    # Show registered agents
    python -m agent_family.runner --list-agents
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from google.adk.sessions import CliSession

# Load .env before any google imports
load_dotenv()

from agent_family.a2a.agent_card import AgentCard
from agent_family.agents.calendar_agent import calendar_agent, calendar_agent_card
from agent_family.agents.master_agent import master_agent, master_agent_card
from agent_family.agents.task_agent import task_agent, task_agent_card
from agent_family.registry.registry import AgentRegistry
from agent_family.auth.oauth2 import GoogleOAuth2Manager

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def setup_registry() -> AgentRegistry:
    """Register all sub-agents and return the populated registry."""
    registry = AgentRegistry()
    registry.clear()  # fresh start each time

    registry.register(calendar_agent_card, calendar_agent)
    registry.register(task_agent_card, task_agent)
    registry.register(master_agent_card, master_agent)

    logger.info("Registry initialized and populated.")
    return registry


async def bootstrap_auth():
    """Ensure Google Auth is initialized before agents run."""
    try:
        manager = GoogleOAuth2Manager.get_instance()
        _ = manager.get_credentials()  # Will prompt flow if missing
        logger.info("OAuth2 credentials validated and ready.")
    except Exception as e:
        logger.warning(f"Could not bootstrap OAuth2. Sub-agents may fail if requiring live GCP APIs. Error: {e}")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def print_agent_table(registry: AgentRegistry) -> None:
    table = Table(title="Registered Agents", border_style="blue")
    table.add_column("Name", style="cyan bold")
    table.add_column("URL", style="dim")
    table.add_column("Skills", style="green")
    table.add_column("Version")

    for card in registry.list_all():
        table.add_row(
            card.name,
            card.url,
            ", ".join(card.skill_ids()),
            card.version,
        )

    console.print(table)


def print_master_response(response: MasterResponse) -> None:
    # Status colour
    colour = {"success": "green", "partial_failure": "yellow", "failure": "red"}.get(
        response.overall_status, "white"
    )

    console.print(
        Panel(
            f"[bold {colour}]Status: {response.overall_status.upper()}[/]\n\n"
            f"[dim]Decomposition:[/] {response.decomposition_id}\n"
            f"[dim]Reasoning:[/] {response.reasoning}\n\n"
            + response.summary,
            title="[bold]Master Agent Response[/]",
            border_style=colour,
            padding=(1, 2),
        )
    )

    # Results table
    table = Table(title="Sub-Agent Results", border_style=colour)
    table.add_column("Agent", style="cyan")
    table.add_column("Skill")
    table.add_column("Status")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Output / Error")

    for r in response.results:
        status_style = "green" if r.status.value == "completed" else "red"
        table.add_row(
            r.agent_name,
            r.skill_id,
            f"[{status_style}]{r.status.value}[/]",
            f"{r.latency_ms:.1f}",
            (r.output or r.error or "—")[:80],
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Async main
# ---------------------------------------------------------------------------


async def async_main(
    prompt: str | None = None,
    list_agents: bool = False,
    log_level: str = "INFO",
) -> None:
    configure_logging(log_level)

    console.print(
        Panel(
            "[bold cyan]Agent Family[/] — Google ADK Multi-Agent System\n"
            "[dim]Master Agent (Gemini 3.1 Flash Lite) | A2A Protocol | Pydantic v2[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    registry = bootstrap_registry()

    if list_agents:
        print_agent_table(registry)
        return

    master = MasterAgent(registry=registry)

    if prompt:
        # Single-shot mode
        console.print(f"\n[bold]Prompt:[/] {prompt}\n")
        response = await master.run(prompt)
        print_master_response(response)
        return

    # Interactive REPL
    console.print("\n[dim]Type your request and press Enter. Type 'exit' to quit.[/]\n")
    while True:
        try:
            user_input = console.input("[bold cyan]You ❯[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/]")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            console.print("[dim]Goodbye![/]")
            break
        if user_input.lower() in {"agents", "list", "ls"}:
            print_agent_table(registry)
            continue

        with console.status("[bold green]Master Agent thinking…[/]"):
            response = await master.run(user_input)

        print_master_response(response)
        console.print()


# ---------------------------------------------------------------------------
# CLI wrapper
# ---------------------------------------------------------------------------


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent Family — Google ADK multi-agent system CLI"
    )
    parser.add_argument("--prompt", "-p", type=str, help="Single prompt to process")
    parser.add_argument(
        "--list-agents", "-l", action="store_true", help="List registered agents and exit"
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "WARNING"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            async_main(
                prompt=args.prompt,
                list_agents=args.list_agents,
                log_level=args.log_level,
            )
        )
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
