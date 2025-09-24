from __future__ import annotations

import sys
import types

from typer.testing import CliRunner

from remote_browser_tool.cli import app
from remote_browser_tool.config import RunnerConfig


def _base_config() -> RunnerConfig:
    return RunnerConfig.model_validate(
        {
            "task": {"description": "CLI test task"},
            "llm": {"provider": "mock"},
            "browser": {"headless": True, "enable_vnc": False},
            "portal": {"host": "127.0.0.1", "port": 9000},
        }
    )


def _capture_builder(name: str, calls: dict[str, list[object]]):
    def _factory(config_section: object) -> str:
        calls.setdefault(name, []).append(config_section)
        return f"{name}-stub"

    return _factory


def _make_orchestrator(state: dict[str, object], result: bool):
    class DummyOrchestrator:
        def __init__(self, **kwargs):
            state.update(kwargs)
            state["run_calls"] = 0

        def run(self) -> bool:
            state["run_calls"] += 1
            return result

    return DummyOrchestrator


def test_run_command_success(monkeypatch, tmp_path):
    runner = CliRunner()

    config_path = tmp_path / "config.yaml"
    config_path.write_text("task: {}\n")
    env_file = tmp_path / "vars.env"
    env_file.write_text("TOKEN=test\n")
    profile_dir = tmp_path / "profile"

    config = _base_config()
    load_args: dict[str, object] = {}

    def fake_load_config(path, *, env_file=None, **overrides):  # type: ignore[no-untyped-def]
        load_args["path"] = path
        load_args["env_file"] = env_file
        load_args["overrides"] = overrides
        return config

    monkeypatch.setattr("remote_browser_tool.cli.load_config", fake_load_config)

    builder_calls: dict[str, list[object]] = {}
    monkeypatch.setattr("remote_browser_tool.cli.build_llm", _capture_builder("llm", builder_calls))
    monkeypatch.setattr("remote_browser_tool.cli.build_browser", _capture_builder("browser", builder_calls))
    monkeypatch.setattr("remote_browser_tool.cli.build_memory", _capture_builder("memory", builder_calls))
    monkeypatch.setattr("remote_browser_tool.cli.build_notifier", _capture_builder("notifier", builder_calls))
    monkeypatch.setattr("remote_browser_tool.cli.build_portal", _capture_builder("portal", builder_calls))

    orchestrator_state: dict[str, object] = {}
    monkeypatch.setattr(
        "remote_browser_tool.cli.Orchestrator",
        _make_orchestrator(orchestrator_state, result=True),
    )

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--env-file",
            str(env_file),
            "--task",
            "Write summary",
            "--goal",
            "Deliver overview",
            "--llm-provider",
            "mock-provider",
            "--model",
            "mock-model",
            "--api-key",
            "secret",
            "--headless",
            "--disable-vnc",
            "--profile-path",
            str(profile_dir),
            "--portal-port",
            "9999",
            "--portal-host",
            "localhost",
            "--memory-max",
            "33",
        ],
    )

    assert result.exit_code == 0
    assert "Loaded configuration for task: CLI test task" in result.stdout
    assert "Task completed successfully." in result.stdout

    assert load_args["path"] == config_path
    assert load_args["env_file"] == env_file
    overrides = load_args["overrides"]
    assert overrides["task"]["description"] == "Write summary"
    assert overrides["task"]["goal"] == "Deliver overview"
    assert overrides["llm"] == {
        "provider": "mock-provider",
        "model": "mock-model",
        "api_key": "secret",
    }
    assert overrides["browser"] == {
        "headless": True,
        "enable_vnc": False,
        "profile_path": str(profile_dir),
    }
    assert overrides["portal"] == {"host": "localhost", "port": 9999}
    assert overrides["memory_max_entries"] == 33

    assert builder_calls["llm"] == [config.llm]
    assert builder_calls["browser"] == [config.browser]
    assert builder_calls["memory"] == [config]
    assert builder_calls["notifier"] == [config.notifications]
    assert builder_calls["portal"] == [config.portal]

    assert orchestrator_state["config"] is config
    assert orchestrator_state["llm"] == "llm-stub"
    assert orchestrator_state["browser"] == "browser-stub"
    assert orchestrator_state["memory"] == "memory-stub"
    assert orchestrator_state["notifier"] == "notifier-stub"
    assert orchestrator_state["user_portal"] == "portal-stub"
    assert orchestrator_state["run_calls"] == 1


def test_run_command_failure(monkeypatch):
    runner = CliRunner()
    config = _base_config()

    monkeypatch.setattr("remote_browser_tool.cli.load_config", lambda *_, **__: config)
    monkeypatch.setattr("remote_browser_tool.cli.build_llm", lambda _: "llm-stub")
    monkeypatch.setattr("remote_browser_tool.cli.build_browser", lambda _: "browser-stub")
    monkeypatch.setattr("remote_browser_tool.cli.build_memory", lambda _: "memory-stub")
    monkeypatch.setattr("remote_browser_tool.cli.build_notifier", lambda _: "notifier-stub")
    monkeypatch.setattr("remote_browser_tool.cli.build_portal", lambda _: "portal-stub")

    orchestrator_state: dict[str, object] = {}
    monkeypatch.setattr(
        "remote_browser_tool.cli.Orchestrator",
        _make_orchestrator(orchestrator_state, result=False),
    )

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Task completed successfully." not in result.stdout
    assert orchestrator_state["run_calls"] == 1



def test_executor_command_invokes_uvicorn(monkeypatch):
    runner = CliRunner()

    calls: list[dict[str, object]] = []

    def fake_run(app, host, port, reload):  # type: ignore[no-untyped-def]
        calls.append({"app": app, "host": host, "port": port, "reload": reload})

    dummy_uvicorn = types.SimpleNamespace(run=fake_run)
    monkeypatch.setitem(sys.modules, "uvicorn", dummy_uvicorn)

    result = runner.invoke(app, ["executor", "--host", "127.0.0.1", "--port", "9100", "--reload"])

    assert result.exit_code == 0
    assert len(calls) == 1
    call = calls[0]
    from remote_browser_tool.executor.service import app as executor_app

    assert call["app"] is executor_app
    assert call["host"] == "127.0.0.1"
    assert call["port"] == 9100
    assert call["reload"] is True



def test_admin_command_invokes_uvicorn_with_created_app(monkeypatch):
    runner = CliRunner()

    calls: list[dict[str, object]] = []

    def fake_run(app, host, port, reload):  # type: ignore[no-untyped-def]
        calls.append({"app": app, "host": host, "port": port, "reload": reload})

    dummy_uvicorn = types.SimpleNamespace(run=fake_run)
    monkeypatch.setitem(sys.modules, "uvicorn", dummy_uvicorn)

    created: dict[str, object] = {}

    def fake_create_admin_app(specs: list[str]):
        created["specs"] = specs
        return "admin-app"

    monkeypatch.setattr("remote_browser_tool.admin.service.create_admin_app", fake_create_admin_app)

    result = runner.invoke(
        app,
        [
            "admin",
            "--executor",
            "primary=http://localhost:9001",
            "--host",
            "0.0.0.0",
            "--port",
            "9200",
            "--reload",
        ],
    )

    assert result.exit_code == 0
    assert created["specs"] == ["primary=http://localhost:9001"]
    assert len(calls) == 1
    call = calls[0]
    assert call["app"] == "admin-app"
    assert call["host"] == "0.0.0.0"
    assert call["port"] == 9200
    assert call["reload"] is True
