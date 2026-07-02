"""settings 单元测试：.env 解析（注释/引号/含=的值/不覆盖已存在）+ 缺变量异常。无网络。"""
import os

import pytest

from settings import Settings, load_env


def test_load_env_parses_and_does_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("T6T_EXISTING", "orig")  # 预置，load_env 不应覆盖
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# 注释行",
                "",
                "T6T_PLAIN=hello",
                'T6T_QUOTED="in quotes"',
                "T6T_SINGLE='single'",
                "T6T_HASEQ=a=b=c",  # 值里含 =，应按第一个 = 切分",
                "T6T_SPACES=  spaced  ",
                "NOEQUALSLINE",  # 无 = 应被忽略",
                "T6T_EXISTING=should_not_win",
            ]
        ),
        encoding="utf-8",
    )
    try:
        load_env(env)
        assert os.environ["T6T_PLAIN"] == "hello"
        assert os.environ["T6T_QUOTED"] == "in quotes"
        assert os.environ["T6T_SINGLE"] == "single"
        assert os.environ["T6T_HASEQ"] == "a=b=c"
        assert os.environ["T6T_SPACES"] == "spaced"
        assert "NOEQUALSLINE" not in os.environ
        assert os.environ["T6T_EXISTING"] == "orig"  # 未被覆盖
    finally:
        for k in ("T6T_PLAIN", "T6T_QUOTED", "T6T_SINGLE", "T6T_HASEQ", "T6T_SPACES"):
            os.environ.pop(k, None)


def test_load_env_missing_path_is_noop(tmp_path):
    load_env(tmp_path / "does_not_exist.env")  # 不应抛错


def test_settings_from_env_ok(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    s = Settings.from_env(load_dotenv=False)
    assert s.supabase_url == "https://x.supabase.co"
    assert s.claude_model == "claude-opus-4-8"  # 默认


def test_settings_from_env_missing_raises(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.from_env(load_dotenv=False)


def test_settings_custom_model(monkeypatch):
    for k, v in {
        "NEXT_PUBLIC_SUPABASE_URL": "u",
        "SUPABASE_SERVICE_ROLE_KEY": "k",
        "ANTHROPIC_API_KEY": "a",
        "CLAUDE_MODEL": "claude-sonnet-5",
    }.items():
        monkeypatch.setenv(k, v)
    assert Settings.from_env(load_dotenv=False).claude_model == "claude-sonnet-5"
