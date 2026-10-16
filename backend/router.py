"""Intent router for data-analysis and literature agents."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import OpenAI


logger = logging.getLogger(__name__)
VALID_AGENT_TYPES = {"auto", "data_analyst", "literature", "hybrid"}
LITERATURE_KEYWORDS = (
    "文献", "研究", "论文", "发表", "综述", "机制", "最新进展", "pubmed", "europe pmc",
    "检索", "文献检索", "文献综述", "literature", "paper", "study", "review",
)
DATA_KEYWORDS = (
    "qc", "质控", "聚类", "umap", "批次效应", "h5ad", "单细胞", "表达矩阵", "data",
    "analysis", "scanpy", "anndata",
)

ROUTER_SYSTEM_PROMPT = """You route cell-biology research requests to one of three agents.
Return JSON only, exactly with these keys:
{"agent_type":"data_analyst|literature|hybrid", "reasoning":"...", "queries":[]}
Queries must be an array of initial literature directions. It must be empty for
data_analyst and non-empty for literature or hybrid when the instruction has text.

Examples:
User: 做 h5ad 的 QC
JSON: {"agent_type":"data_analyst","reasoning":"h5ad QC is data analysis","queries":[]}
User: 分析这个单细胞数据
JSON: {"agent_type":"data_analyst","reasoning":"single-cell analysis","queries":[]}
User: 检索 TP53 在细胞周期中的作用
JSON: {"agent_type":"literature","reasoning":"literature retrieval request","queries":["TP53 cell cycle"]}
User: 总结 CD8 T 细胞在肿瘤微环境的最新研究
JSON: {"agent_type":"literature","reasoning":"recent literature review","queries":["CD8 T cell tumor microenvironment"]}
User: 对我的数据做 QC 并总结相关基因的研究
JSON: {"agent_type":"hybrid","reasoning":"data analysis plus literature","queries":["related genes and single-cell QC"]}
User: 帮我看看
JSON: {"agent_type":"data_analyst","reasoning":"ambiguous request defaults to data analysis","queries":[]}
User: [file upload with no text instruction]
JSON: {"agent_type":"data_analyst","reasoning":"file-only request defaults to data analysis","queries":[]}
"""


def _clean_queries(value: Any, instruction: str, agent_type: str) -> list[str]:
    if not isinstance(value, list):
        value = []
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            continue
        query = re.sub(r"[\x00-\x1f\x7f]", " ", item).strip()
        if query.count('"') % 2:
            query = query.replace('"', "")
        query = re.sub(r"\s+", " ", query).strip()
        if query:
            cleaned.append(query)
    if agent_type in {"literature", "hybrid"} and not cleaned and instruction.strip():
        cleaned = [re.sub(r"\s+", " ", instruction).strip()]
    return list(dict.fromkeys(cleaned))


def keyword_route(instruction: str) -> dict[str, Any]:
    text = instruction.lower().strip()
    has_literature = any(keyword in text for keyword in LITERATURE_KEYWORDS)
    has_data = any(keyword in text for keyword in DATA_KEYWORDS)
    if has_literature and has_data:
        agent_type = "hybrid"
        reasoning = "matched both literature and data-analysis keywords"
    elif has_literature:
        agent_type = "literature"
        reasoning = "matched literature keywords"
    else:
        agent_type = "data_analyst"
        reasoning = "matched data-analysis keywords or defaulted to data analysis"
    return {
        "agent_type": agent_type,
        "reasoning": reasoning,
        "queries": _clean_queries([], instruction, agent_type),
        "source": "keyword_fallback",
    }


def _parse_llm_result(text: str, instruction: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("Router LLM returned invalid JSON")
    if not isinstance(value, dict):
        raise ValueError("Router LLM returned a non-object")
    agent_type = value.get("agent_type")
    if agent_type not in {"data_analyst", "literature", "hybrid"}:
        raise ValueError("Router LLM returned an invalid agent_type")
    return {
        "agent_type": agent_type,
        "reasoning": str(value.get("reasoning") or "LLM route"),
        "queries": _clean_queries(value.get("queries"), instruction, agent_type),
        "source": "llm",
    }


def _llm_route(instruction: str, client: OpenAI | None = None) -> dict[str, Any]:
    if client is None:
        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=15.0,
            max_retries=0,
        )
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL_ROUTER", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
        instructions=ROUTER_SYSTEM_PROMPT,
        input=instruction,
    )
    return _parse_llm_result(response.output_text, instruction)


def route_instruction(
    instruction: str | None,
    *,
    requested_agent_type: str = "auto",
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Return a route, preferring LLM classification and falling back safely."""
    instruction = instruction or ""
    if requested_agent_type not in VALID_AGENT_TYPES:
        raise ValueError(
            f"Invalid agent_type: {requested_agent_type}. "
            f"Expected one of {sorted(VALID_AGENT_TYPES)}."
        )
    if requested_agent_type != "auto":
        result = {
            "agent_type": requested_agent_type,
            "reasoning": "explicit agent_type requested by caller",
            "queries": _clean_queries([], instruction, requested_agent_type),
            "source": "explicit",
        }
        logger.info("route_source=explicit agent_type=%s", requested_agent_type)
        return result
    if not instruction.strip() or not os.getenv("OPENAI_API_KEY"):
        result = keyword_route(instruction)
        logger.info("route_source=keyword_fallback reason=no_instruction_or_api_key")
        return result
    try:
        result = _llm_route(instruction, client=client)
        logger.info("route_source=llm agent_type=%s", result["agent_type"])
        return result
    except Exception as exc:  # noqa: BLE001 - routing must never block execution.
        logger.warning("route_source=keyword_fallback llm_error=%s", exc)
        result = keyword_route(instruction)
        result["reasoning"] = f"LLM routing failed; {result['reasoning']}"
        return result
