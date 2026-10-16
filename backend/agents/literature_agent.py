"""Europe PMC literature retrieval and LLM-assisted summarization."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from openai import AuthenticationError, OpenAI

from ..openai_utils import configured_api_key


EUROPE_PMC_URL = os.getenv(
    "EUROPE_PMC_URL",
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
)
_SEARCH_CACHE: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)


class LiteratureAgentError(RuntimeError):
    """Raised for configuration or LLM failures in the literature agent."""


def _model_name() -> str:
    return os.getenv(
        "OPENAI_MODEL_SUMMARY",
        os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    )


def _extract_json(text: str) -> Any:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = min((index for index in (candidate.find("{"), candidate.find("[")) if index >= 0), default=-1)
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if start < 0 or end < start:
            raise LiteratureAgentError("LLM did not return valid JSON")
        return json.loads(candidate[start : end + 1])


def _clean_term(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff\s_.-]", " ", str(value))
    return re.sub(r"\s+", " ", value).strip()


def _fallback_entities(instruction: str) -> dict[str, list[str]]:
    genes = sorted(set(re.findall(r"\b[A-Z][A-Z0-9-]{1,14}\b", instruction)))
    return {
        "genes": genes,
        "cell_types": [],
        "diseases": [],
        "topics": [instruction.strip()] if instruction.strip() else [],
    }


def extract_entities(
    instruction: str,
    *,
    qc_context: dict[str, Any] | None = None,
    client: OpenAI | None = None,
) -> dict[str, list[str]]:
    """Extract searchable entities, using a conservative local fallback."""
    if client is None:
        api_key = configured_api_key()
    else:
        api_key = None
    if client is None and api_key is None:
        entities = _fallback_entities(instruction)
    else:
        client = client or OpenAI(api_key=api_key)
        try:
            response = client.responses.create(
                model=os.getenv("OPENAI_MODEL_ROUTER", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
                instructions=(
                    "Extract literature search entities as JSON with exactly these arrays: "
                    "genes, cell_types, diseases, topics. Return JSON only. Do not invent entities."
                ),
                input=json.dumps({"instruction": instruction, "qc_context": qc_context or {}}, ensure_ascii=False),
            )
            value = _extract_json(response.output_text)
            if not isinstance(value, dict):
                raise LiteratureAgentError("Entity extraction did not return a JSON object")
            entities = {
                key: [_clean_term(item) for item in value.get(key, []) if _clean_term(item)]
                for key in ("genes", "cell_types", "diseases", "topics")
            }
        except AuthenticationError:
            logger.warning("OpenAI AuthenticationError during entity extraction; using keyword fallback")
            entities = _fallback_entities(instruction)

    if qc_context:
        for key in ("genes", "cell_types", "diseases", "topics"):
            for item in qc_context.get(key, []):
                cleaned = _clean_term(item)
                if cleaned and cleaned not in entities[key]:
                    entities[key].append(cleaned)
    return entities


def build_queries(entities: dict[str, list[str]]) -> list[str]:
    """Build Europe PMC fielded queries with validated quoted terms."""
    groups = []
    for key, field in (("genes", "GENE"), ("cell_types", "CELL"), ("diseases", "DISEASE")):
        terms = [_clean_term(item) for item in entities.get(key, [])]
        terms = [item for item in terms if item]
        if terms:
            groups.append("(" + " OR ".join(f'{field}:"{item}"' for item in terms) + ")")
    topics = [_clean_term(item) for item in entities.get("topics", [])]
    topics = [item for item in topics if item]
    if topics:
        groups.append("(" + " OR ".join(f'"{item}"' for item in topics) + ")")
    query = " AND ".join(groups) or '"single-cell"'
    if query.count('"') % 2:
        raise LiteratureAgentError("Generated Europe PMC query contains unbalanced quotes")
    return [query]


def _parse_paper(item: dict[str, Any]) -> dict[str, Any]:
    pmid = str(item.get("pmid") or item.get("id") or "")
    abstract = item.get("abstractText") or ""
    return {
        "pmid": pmid,
        "doi": item.get("doi") or "",
        "title": item.get("title") or "Untitled",
        "authors": item.get("authorString") or "",
        "journal": item.get("journalTitle") or "",
        "year": str(item.get("firstPublicationDate", ""))[:4],
        "abstract": abstract,
        "abstract_status": "available" if abstract else "摘要不可用（abstract missing）",
        "url": f"https://europepmc.org/article/MED/{pmid}" if pmid else "",
    }


def search_europe_pmc(
    query: str,
    *,
    years: int | None = None,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    years = years or int(os.getenv("LITERATURE_YEARS", "5"))
    max_results = max_results or int(os.getenv("LITERATURE_MAX_RESULTS", "10"))
    since = date.today() - timedelta(days=365 * years)
    full_query = f"{query} AND FIRST_PDATE:[{since.isoformat()} TO {date.today().isoformat()}]"
    cache_key = hashlib.sha256(full_query.encode("utf-8")).hexdigest()
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]
    time.sleep(0.5)
    response = requests.get(
        EUROPE_PMC_URL,
        params={"query": full_query, "format": "json", "pageSize": max_results, "resultType": "core"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    papers = [_parse_paper(item) for item in payload.get("resultList", {}).get("result", [])[:max_results]]
    _SEARCH_CACHE[cache_key] = papers
    return papers


def summarize_papers(
    papers: list[dict[str, Any]],
    instruction: str,
    *,
    client: OpenAI | None = None,
) -> list[dict[str, Any]]:
    """Summarize at most five abstracts per LLM request and preserve PMID order."""
    available = [paper for paper in papers if paper.get("abstract")]
    summaries: dict[str, dict[str, Any]] = {}
    def fallback_summary(paper: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "status": reason if paper.get("abstract") else paper["abstract_status"],
            "excerpt": str(paper.get("abstract") or "")[:300],
            "topic": "",
            "key_findings": "",
            "methods": "",
            "relevance": "",
            "limitations": "",
        }

    api_key = configured_api_key() if client is None else None
    if client is None and api_key is None:
        return [
            {**paper, "summary": fallback_summary(paper, "LLM 摘要不可用：未配置 OPENAI_API_KEY")}
            for paper in papers
        ]
    client = client or OpenAI(api_key=api_key)
    try:
        for start in range(0, len(available), 5):
            batch = available[start : start + 5]
            payload = [{"pmid": paper["pmid"], "title": paper["title"], "abstract": paper["abstract"]} for paper in batch]
            response = client.responses.create(
                model=_model_name(),
                instructions=(
                    "Summarize each input paper. Return a JSON array with exactly the same "
                    "length and order as the input. Every item must contain the matching PMID, "
                    "topic, key_findings, methods, relevance, and limitations. Do not invent facts."
                ),
                input=json.dumps({"instruction": instruction, "papers": payload}, ensure_ascii=False),
            )
            values = _extract_json(response.output_text)
            if not isinstance(values, list) or len(values) != len(batch):
                raise LiteratureAgentError("Literature summary JSON length does not match input batch")
            for paper, summary in zip(batch, values):
                if not isinstance(summary, dict) or str(summary.get("pmid", "")) != paper["pmid"]:
                    raise LiteratureAgentError("Literature summary PMID order does not match input")
                summaries[paper["pmid"]] = summary
    except AuthenticationError:
        return [
            {**paper, "summary": fallback_summary(paper, "LLM 摘要不可用：OPENAI_API_KEY 无效")}
            for paper in papers
        ]

    result = []
    for paper in papers:
        enriched = dict(paper)
        enriched["summary"] = summaries.get(paper["pmid"], fallback_summary(paper, "摘要不可用（abstract missing）"))
        result.append(enriched)
    return result


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _render_report(result: dict[str, Any]) -> str:
    lines = ["# 文献专家 Agent 报告", "", f"状态：`{result['status']}`", "", "## 查询", ""]
    lines.extend(f"- `{query}`" for query in result["queries"])
    lines.extend(["", "## 文献", ""])
    for paper in result["papers"]:
        lines.extend([
            f"### {paper['title']}",
            f"- PMID：{paper['pmid']}  DOI：{paper['doi'] or '不可用'}",
            f"- 作者：{paper['authors'] or '不可用'}",
            f"- 期刊/年份：{paper['journal'] or '不可用'} / {paper['year'] or '不可用'}",
            f"- 链接：{paper['url'] or '不可用'}",
            f"- 摘要状态：{paper['abstract_status']}",
            f"- 结构化总结：{json.dumps(paper['summary'], ensure_ascii=False)}",
            "",
        ])
    lines.extend(["## 总结", "", result["summary"], ""])
    return "\n".join(lines)


def run_literature(
    instruction: str,
    output_dir: str | Path,
    *,
    qc_context: dict[str, Any] | None = None,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Extract entities, search Europe PMC, summarize, and atomically write reports."""
    output_dir = Path(output_dir)
    entities = extract_entities(instruction, qc_context=qc_context, client=client)
    queries = build_queries(entities)
    try:
        papers = []
        seen = set()
        for query in queries:
            for paper in search_europe_pmc(query):
                if paper["pmid"] not in seen:
                    papers.append(paper)
                    seen.add(paper["pmid"])
    except requests.RequestException as exc:
        result = {"status": "unavailable", "queries": queries, "papers": [], "summary": f"Europe PMC API unavailable: {exc}"}
    else:
        if not papers:
            result = {"status": "no_results", "queries": queries, "papers": [], "summary": "No papers matched the query."}
        else:
            enriched = summarize_papers(papers, instruction, client=client)
            result = {
                "status": "success",
                "queries": queries,
                "papers": enriched,
                "summary": f"Retrieved and summarized {len(enriched)} papers.",
            }
    result["entities"] = entities
    result["generated_at_utc"] = datetime.now(UTC).isoformat()
    _atomic_write(output_dir / "literature.json", json.dumps(result, ensure_ascii=False, indent=2))
    _atomic_write(output_dir / "literature_report.md", _render_report(result))
    return result
