from pathlib import Path

from remote_browser_tool.config import load_config


def test_load_config_reads_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "REMOTE_BROWSER_TOOL_TASK__DESCRIPTION=Task from env",
                "REMOTE_BROWSER_TOOL_TASK__GOAL=Goal from env",
                "REMOTE_BROWSER_TOOL_LLM__PROVIDER=mock",
                "REMOTE_BROWSER_TOOL_MEMORY_MAX_ENTRIES=10",
            ]
        )
    )

    config = load_config(env_file=env_path)

    assert config.task.description == "Task from env"
    assert config.task.goal == "Goal from env"
    assert config.llm.provider == "mock"
    assert config.memory_max_entries == 10


def test_load_config_prioritises_overrides(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "REMOTE_BROWSER_TOOL_TASK__DESCRIPTION=Env description",
                "REMOTE_BROWSER_TOOL_TASK__GOAL=Env goal",
                "REMOTE_BROWSER_TOOL_LLM__PROVIDER=mock",
            ]
        )
    )

    config_path = tmp_path / "task.yaml"
    config_path.write_text(
        "\n".join(
            [
                "task:",
                "  description: File description",
            ]
        )
    )

    config = load_config(config_path, env_file=env_path, task={"goal": "Override goal"})

    assert config.task.description == "File description"
    assert config.task.goal == "Override goal"
    assert config.llm.provider == "mock"
