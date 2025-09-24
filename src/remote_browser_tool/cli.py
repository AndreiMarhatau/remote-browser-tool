"""Command line interface for remote-browser-tool."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from .config import load_config
from .factory import build_browser, build_llm, build_memory, build_notifier, build_portal
from .orchestrator.runner import Orchestrator

app = typer.Typer(help="Remote Browser Tool entry point")


@app.callback()
def main(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging"),
    ] = False,
) -> None:
    """Configure logging before executing any command."""

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def version() -> None:
    """Print the package version."""

    try:
        typer.echo(get_version("remote-browser-tool"))
    except PackageNotFoundError:  # pragma: no cover - when running from source tree
        typer.echo("0.0.0")


@app.command()
def run(
    config_path: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to YAML configuration."),
    ] = None,
    env_file: Annotated[
        Optional[Path],
        typer.Option(
            "--env-file",
            help="Path to an .env file with default configuration values.",
        ),
    ] = None,
    task: Annotated[
        Optional[str],
        typer.Option("--task", help="Override task description."),
    ] = None,
    goal: Annotated[
        Optional[str],
        typer.Option("--goal", help="Override task success criteria."),
    ] = None,
    llm_provider: Annotated[
        Optional[str],
        typer.Option("--llm-provider", help="LLM provider to use."),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", help="LLM model identifier."),
    ] = None,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", help="API key for the LLM provider."),
    ] = None,
    headless: Annotated[
        Optional[bool],
        typer.Option("--headless/--headed", help="Run the browser in headless mode (or headed)."),
    ] = None,
    enable_vnc: Annotated[
        Optional[bool],
        typer.Option("--enable-vnc/--disable-vnc", help="Enable or disable the VNC bridge."),
    ] = None,
    profile_path: Annotated[
        Optional[Path],
        typer.Option("--profile-path", help="Browser user data directory to reuse between runs."),
    ] = None,
    portal_port: Annotated[
        Optional[int],
        typer.Option("--portal-port", help="HTTP port for the user portal."),
    ] = None,
    portal_host: Annotated[
        Optional[str],
        typer.Option("--portal-host", help="Binding address for the user portal."),
    ] = None,
    memory_max: Annotated[
        Optional[int],
        typer.Option("--memory-max", help="Maximum stored memory entries."),
    ] = None,
) -> None:
    """Run a browser automation task."""

    overrides: dict[str, Any] = {}
    if task or goal:
        overrides.setdefault("task", {})
        if task:
            overrides["task"]["description"] = task
        if goal:
            overrides["task"]["goal"] = goal
    if any([llm_provider, model, api_key]):
        overrides.setdefault("llm", {})
        if llm_provider:
            overrides["llm"]["provider"] = llm_provider
        if model:
            overrides["llm"]["model"] = model
        if api_key:
            overrides["llm"]["api_key"] = api_key
    if headless is not None or enable_vnc is not None or profile_path is not None:
        overrides.setdefault("browser", {})
        if headless is not None:
            overrides["browser"]["headless"] = headless
        if enable_vnc is not None:
            overrides["browser"]["enable_vnc"] = enable_vnc
        if profile_path is not None:
            overrides["browser"]["profile_path"] = str(profile_path)
    if portal_port is not None or portal_host is not None:
        overrides.setdefault("portal", {})
        if portal_host is not None:
            overrides["portal"]["host"] = portal_host
        if portal_port is not None:
            overrides["portal"]["port"] = portal_port
    if memory_max is not None:
        overrides["memory_max_entries"] = memory_max

    config = load_config(config_path, env_file=env_file, **overrides)
    typer.echo(f"Loaded configuration for task: {config.task.description}")

    llm = build_llm(config.llm)
    browser = build_browser(config.browser)
    memory = build_memory(config)
    notifier = build_notifier(config.notifications)
    portal = build_portal(config.portal)

    orchestrator = Orchestrator(
        config=config,
        llm=llm,
        browser=browser,
        memory=memory,
        notifier=notifier,
        user_portal=portal,
    )
    success = orchestrator.run()
    if not success:
        raise typer.Exit(code=1)
    typer.echo("Task completed successfully.")


if __name__ == "__main__":
    app()
