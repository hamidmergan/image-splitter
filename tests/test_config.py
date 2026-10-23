import pytest

from image_splitter import config
from image_splitter.errors import ConfigError


def test_works_without_any_model_settings():
    s = config.resolve()
    assert s.vision is False
    assert s.base_url is None and s.model is None


def test_vision_needs_base_url_and_model():
    with pytest.raises(ConfigError) as e:
        config.resolve(vision=True)
    assert "base_url" in str(e.value) and "model" in str(e.value)


def test_base_url_alone_turns_vision_on_and_asks_for_model():
    with pytest.raises(ConfigError) as e:
        config.resolve(base_url="http://x/v1")
    assert "model" in str(e.value) and "base_url (" not in str(e.value)


def test_no_vision_ignores_incomplete_model_settings():
    s = config.resolve(base_url="http://x/v1", vision=False)
    assert s.vision is False


def test_api_key_optional_uses_placeholder():
    s = config.resolve(base_url="http://x/v1", model="m")
    assert s.vision is True
    assert s.api_key == config.PLACEHOLDER_API_KEY


def test_openai_api_key_as_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert config.resolve(base_url="http://x/v1", model="m").api_key == "sk-test"


def test_env_for_connection(monkeypatch):
    monkeypatch.setenv("IMAGE_SPLITTER_BASE_URL", "http://h/v1")
    monkeypatch.setenv("IMAGE_SPLITTER_MODEL", "mm")
    monkeypatch.setenv("IMAGE_SPLITTER_API_KEY", "k")
    s = config.resolve()
    assert (s.vision, s.base_url, s.model, s.api_key) == (True, "http://h/v1", "mm", "k")


def test_env_vision_off(monkeypatch):
    monkeypatch.setenv("IMAGE_SPLITTER_BASE_URL", "http://h/v1")
    monkeypatch.setenv("IMAGE_SPLITTER_VISION", "off")
    assert config.resolve().vision is False


def test_precedence_arg_env_default(monkeypatch):
    monkeypatch.setenv("IMAGE_SPLITTER_MIN_AREA", "0.05")
    assert config.resolve().min_area == 0.05
    assert config.resolve(min_area=0.2).min_area == 0.2
    monkeypatch.delenv("IMAGE_SPLITTER_MIN_AREA")
    assert config.resolve().min_area == config.MIN_AREA


@pytest.mark.parametrize("name,value", [("MAX_PAGES", "abc"), ("VISION", "maybe"), ("PADDING", "1.5")])
def test_invalid_env_value(monkeypatch, name, value):
    monkeypatch.setenv("IMAGE_SPLITTER_" + name, value)
    with pytest.raises(ConfigError):
        config.resolve()


@pytest.mark.parametrize("kwargs", [{"max_pages": 0}, {"pdf_dpi": -1}, {"min_area": 0}, {"min_area": 1.5}, {"max_retries": -1}])
def test_invalid_values_rejected(kwargs):
    with pytest.raises(ConfigError):
        config.resolve(**kwargs)
