import pytest

from types import SimpleNamespace

from sovara.cli import so_tool


def _install_args(tmp_path, **overrides):
    defaults = {
        "project_dir": None,
        "level": "global",
        "target": "both",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_install_skill_command_installs_codex_and_claude_targets_globally(tmp_path, monkeypatch):
    monkeypatch.setattr(so_tool.Path, "home", lambda: tmp_path)
    args = _install_args(tmp_path)

    so_tool.install_skill_command(args)

    codex_skill = tmp_path / ".agents" / "skills" / "sovara" / "SKILL.md"
    claude_skill = tmp_path / ".claude" / "skills" / "sovara" / "SKILL.md"

    assert codex_skill.exists()
    assert claude_skill.exists()
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_install_skill_command_codex_project_target_skips_claude_files(tmp_path):
    args = _install_args(tmp_path, level="project", project_dir=str(tmp_path), target="codex")

    so_tool.install_skill_command(args)

    codex_skill = tmp_path / ".agents" / "skills" / "sovara" / "SKILL.md"
    claude_skill = tmp_path / ".claude" / "skills" / "sovara" / "SKILL.md"
    claude_settings_file = tmp_path / ".claude" / "settings.local.json"

    assert codex_skill.exists()
    assert not claude_skill.exists()
    assert not claude_settings_file.exists()


def test_install_skill_command_rejects_project_dir_for_global_level(tmp_path):
    args = _install_args(tmp_path, project_dir=str(tmp_path))

    with pytest.raises(SystemExit) as exc_info:
        so_tool.install_skill_command(args)

    assert exc_info.value.code == 1


def test_install_skill_parser_accepts_level_and_target_flags():
    parser = so_tool.create_parser()

    args = parser.parse_args([
        "install-skill",
        "--level",
        "project",
        "--project-dir",
        "/tmp/demo",
        "--target",
        "claude",
    ])

    assert args.command == "install-skill"
    assert args.level == "project"
    assert args.project_dir == "/tmp/demo"
    assert args.target == "claude"
