import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


def _reload_config_with_env(**env_vars):
    """
    core/config.py reads env vars at import time, so tests need to set env vars
    and force a fresh import to see the effect, then clean up afterward.
    """
    keys_to_clear = ["ANTHROPIC_API_KEY", "CLAUDE_MODEL_TIER", "CLAUDE_MODEL"]
    saved = {k: os.environ.get(k) for k in keys_to_clear}
    for k in keys_to_clear:
        os.environ.pop(k, None)
    os.environ.update(env_vars)

    if "core.config" in sys.modules:
        del sys.modules["core.config"]
    import core.config as config

    yield config

    for k in keys_to_clear:
        os.environ.pop(k, None)
        if saved[k] is not None:
            os.environ[k] = saved[k]
    if "core.config" in sys.modules:
        del sys.modules["core.config"]


@pytest.fixture
def config_economy():
    yield from _reload_config_with_env(ANTHROPIC_API_KEY="sk-ant-test", CLAUDE_MODEL_TIER="economy")


@pytest.fixture
def config_quality():
    yield from _reload_config_with_env(ANTHROPIC_API_KEY="sk-ant-test", CLAUDE_MODEL_TIER="quality")


@pytest.fixture
def config_default():
    yield from _reload_config_with_env(ANTHROPIC_API_KEY="sk-ant-test")


@pytest.fixture
def config_bad_tier():
    yield from _reload_config_with_env(ANTHROPIC_API_KEY="sk-ant-test", CLAUDE_MODEL_TIER="ultra-max")


@pytest.fixture
def config_explicit_override():
    yield from _reload_config_with_env(
        ANTHROPIC_API_KEY="sk-ant-test", CLAUDE_MODEL_TIER="economy", CLAUDE_MODEL="claude-opus-4-8"
    )


def test_economy_tier_selects_haiku(config_economy):
    assert config_economy.CLAUDE_MODEL == "claude-haiku-4-5-20251001"


def test_quality_tier_selects_sonnet(config_quality):
    assert config_quality.CLAUDE_MODEL == "claude-sonnet-4-6"


def test_default_tier_is_quality(config_default):
    assert config_default.CLAUDE_MODEL_TIER == "quality"
    assert config_default.CLAUDE_MODEL == "claude-sonnet-4-6"


def test_invalid_tier_falls_back_to_quality_with_warning(config_bad_tier):
    assert config_bad_tier.CLAUDE_MODEL == "claude-sonnet-4-6"
    warns = config_bad_tier.warnings()
    assert any("ultra-max" in w for w in warns)


def test_invalid_tier_does_not_block_startup(config_bad_tier):
    # A bad tier value should be a soft warning, not a hard-blocking problem
    problems = config_bad_tier.validate(require_ebay=False)
    assert problems == []


def test_explicit_model_overrides_tier(config_explicit_override):
    assert config_explicit_override.CLAUDE_MODEL == "claude-opus-4-8"
