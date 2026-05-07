from types import SimpleNamespace

import pytest

from agentclaw.config import KnowledgeBaseConfig
from agentclaw.api.routers.admin.knowledgebases import _search_hit_to_response
from agentclaw.knowledgebase.models import KnowledgeBaseRecord, SearchCandidate, SearchExecution
from agentclaw.knowledgebase.service import KnowledgeBaseService


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_search_reports_rerank_applied_without_assigning_rerank_scores():
    class FakeStore:
        async def get_knowledgebase(self, knowledgebase_id):
            return KnowledgeBaseRecord(
                id=knowledgebase_id,
                name="Docs",
                rerank_model_id="reranker",
                retrieval_config={},
            )

        async def get_chunks_by_ids(self, chunk_ids):
            return {
                "chunk-a": {
                    "document_id": "doc-1",
                    "document_name": "Document A",
                    "chunk_index": 0,
                    "content": "alpha content",
                    "stored_path": "",
                    "metadata": {},
                },
                "chunk-b": {
                    "document_id": "doc-2",
                    "document_name": "Document B",
                    "chunk_index": 0,
                    "content": "beta content",
                    "stored_path": "",
                    "metadata": {},
                },
            }

        async def keyword_search(self, *args, **kwargs):
            return []

    class FakeRetrievalBackend:
        async def search(self, **kwargs):
            return SearchExecution(
                strategy="hybrid",
                candidates=[
                    SearchCandidate(chunk_id="chunk-a", score=0.8, dense_score=0.8),
                    SearchCandidate(chunk_id="chunk-b", score=0.7, dense_score=0.7),
                ],
            )

    class FakeModelGateway:
        async def rerank_texts(self, **kwargs):
            assert kwargs["model_id"] == "reranker"
            return [{"index": 1, "score": 0.99}, {"index": 0, "score": 0.5}]

    service = KnowledgeBaseService(
        store=FakeStore(),
        storage=SimpleNamespace(),
        parser=SimpleNamespace(),
        model_gateway=FakeModelGateway(),
        retrieval_backend=FakeRetrievalBackend(),
        config=KnowledgeBaseConfig(default_top_k=2),
    )

    result = await service.search(query="beta", knowledgebase_id="kb-1", top_k=2)

    assert result.rerank_applied is True
    assert result.strategy == "hybrid+rerank"
    assert [hit.chunk_id for hit in result.hits] == ["chunk-b", "chunk-a"]
    assert [hit.rerank_score for hit in result.hits] == [None, None]
    assert "rerank_score" not in _search_hit_to_response(result.hits[0])
