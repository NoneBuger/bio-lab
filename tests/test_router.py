import json
from unittest.mock import Mock

import pytest

from backend.router import route_instruction


class FakeResponse:
    def __init__(self, text: str):
        self.output_text = text


def fake_client(text: str) -> Mock:
    client = Mock()
    client.responses.create.return_value = FakeResponse(text)
    return client


def test_explicit_routes_and_invalid_type() -> None:
    assert route_instruction("检索 TP53", requested_agent_type="literature")["source"] == "explicit"
    with pytest.raises(ValueError):
        route_instruction("QC", requested_agent_type="unknown")


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("做 h5ad 的 QC", "data_analyst"),
        ("ANALYZE this single-cell DATA", "data_analyst"),
        ("检索 TP53 在细胞周期中的作用", "literature"),
        ("最新 literature review of CD8 T cells", "literature"),
        ("对数据做 QC 并总结相关 gene 的研究", "hybrid"),
        ("帮我看看", "data_analyst"),
        ("", "data_analyst"),
    ],
)
def test_keyword_fallback_is_case_insensitive_and_handles_mixed_intent(instruction, expected, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert route_instruction(instruction)["agent_type"] == expected


def test_keyword_route_queries_are_nonempty_for_literature() -> None:
    result = route_instruction("研究 TP53", requested_agent_type="literature")
    assert result["queries"] == ["研究 TP53"]


def test_llm_route_uses_router_model_and_cleans_queries(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = fake_client(json.dumps({"agent_type": "literature", "reasoning": "papers", "queries": ["TP53 \"cell cycle", ""]}))
    result = route_instruction("检索 TP53", client=client)
    assert result["source"] == "llm"
    assert result["queries"] == ["TP53 cell cycle"]
    call = client.responses.create.call_args.kwargs
    assert call["model"] == "gpt-4.1-mini"


def test_invalid_llm_json_falls_back_to_keywords(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    result = route_instruction("检索 TP53 文献", client=fake_client("not-json"))
    assert result["source"] == "keyword_fallback"
    assert result["agent_type"] == "literature"


def test_llm_timeout_falls_back_to_keywords(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = Mock()
    client.responses.create.side_effect = TimeoutError("timed out")
    result = route_instruction("h5ad QC and literature review", client=client)
    assert result["source"] == "keyword_fallback"
    assert result["agent_type"] == "hybrid"


def test_missing_api_key_never_calls_llm(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = Mock()
    result = route_instruction("做 h5ad QC", client=client)
    assert result["source"] == "keyword_fallback"
    client.responses.create.assert_not_called()
