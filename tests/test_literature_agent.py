import json
from unittest.mock import patch

import pytest
import requests

from backend.agents import literature_agent as agent


class FakeResponse:
    def __init__(self, payload=None, output_text=None):
        self.payload = payload
        self.output_text = output_text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def create(self, **kwargs):
        return FakeResponse(output_text=next(self.outputs))


class FakeClient:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


def europe_pmc_payload():
    return {
        "resultList": {
            "result": [
                {
                    "pmid": "111",
                    "doi": "10.1000/example1",
                    "title": "CD8 T cells in tumors",
                    "authorString": "Author A",
                    "journalTitle": "Cell",
                    "firstPublicationDate": "2025-01-01",
                    "abstractText": "A study of CD8 T cells.",
                },
                {
                    "pmid": "222",
                    "title": "Metadata-only paper",
                    "authorString": "Author B",
                    "journalTitle": "Nature",
                    "firstPublicationDate": "2024-01-01",
                },
            ]
        }
    }


def test_run_literature_preserves_missing_abstract_metadata(tmp_path):
    agent._SEARCH_CACHE.clear()
    client = FakeClient([
        '{"genes": ["CD8A"], "cell_types": ["CD8 T cell"], "diseases": ["cancer"], "topics": ["tumor microenvironment"]}',
        '[{"pmid":"111","topic":"tumor immunity","key_findings":"finding","methods":"single-cell","relevance":"high","limitations":"small cohort"}]',
    ])
    with patch("backend.agents.literature_agent.requests.get", return_value=FakeResponse(europe_pmc_payload())), patch("backend.agents.literature_agent.time.sleep"):
        result = agent.run_literature("总结 CD8A 在肿瘤中的研究", tmp_path, client=client)

    assert result["status"] == "success"
    assert [paper["pmid"] for paper in result["papers"]] == ["111", "222"]
    missing = result["papers"][1]
    assert missing["abstract_status"] == "摘要不可用（abstract missing）"
    assert missing["summary"]["status"] == "摘要不可用（abstract missing）"
    report = (tmp_path / "literature_report.md").read_text()
    assert "摘要不可用（abstract missing）" in report
    assert (tmp_path / "literature.json").exists()
    assert json.loads((tmp_path / "literature.json").read_text())["papers"][0]["pmid"] == "111"


def test_europe_pmc_no_results(tmp_path):
    agent._SEARCH_CACHE.clear()
    with patch("backend.agents.literature_agent.requests.get", return_value=FakeResponse({"resultList": {"result": []}})), patch("backend.agents.literature_agent.time.sleep"):
        result = agent.run_literature("CD8A 文献", tmp_path)
    assert result["status"] == "no_results"
    assert result["papers"] == []


def test_europe_pmc_failure_is_reported(tmp_path):
    agent._SEARCH_CACHE.clear()
    with patch("backend.agents.literature_agent.requests.get", side_effect=requests.RequestException("offline")), patch("backend.agents.literature_agent.time.sleep"):
        result = agent.run_literature("CD8A 文献", tmp_path)
    assert result["status"] == "unavailable"
    assert "offline" in result["summary"]


def test_summary_batches_at_five_and_preserves_pmid_order():
    papers = [
        {"pmid": str(index), "title": f"Paper {index}", "abstract": "abstract", "abstract_status": "available"}
        for index in range(6)
    ]
    outputs = [
        json.dumps([{"pmid": str(index), "topic": "t"} for index in range(5)]),
        json.dumps([{"pmid": "5", "topic": "t"}]),
    ]
    result = agent.summarize_papers(papers, "summarize", client=FakeClient(outputs))
    assert [paper["summary"]["pmid"] for paper in result] == [str(index) for index in range(6)]


def test_query_uses_fielded_syntax_and_cleans_quotes():
    queries = agent.build_queries({"genes": ['CD8A"'], "cell_types": ["CD8 T cell"], "diseases": [], "topics": []})
    assert 'GENE:"CD8A"' in queries[0]
    assert 'CELL:"CD8 T cell"' in queries[0]
    assert queries[0].count('"') % 2 == 0
