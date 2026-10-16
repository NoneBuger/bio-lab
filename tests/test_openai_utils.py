import pytest

from backend.openai_utils import is_placeholder_api_key


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("sk-your-key-here", True),
        ("sk-test-123", True),
        ("test-key", True),
        ("sk-xxxxxxx", True),
        ("sk-fake-12345678901234567890", True),
        ("sk-proj-1234567890abcdefghijklmnopqrstuvwxyz", False),
    ],
)
def test_placeholder_api_key_detection(value, expected):
    assert is_placeholder_api_key(value) is expected
