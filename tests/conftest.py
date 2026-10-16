import pytest


@pytest.fixture(autouse=True)
def mock_openai_disabled(request, monkeypatch):
    """Prevent accidental network calls unless a test explicitly opts in."""
    if request.node.get_closest_marker("with_real_key") is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
