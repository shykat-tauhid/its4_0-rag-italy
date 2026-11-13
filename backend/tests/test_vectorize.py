import importlib
import sys

import pytest


@pytest.fixture
def vectorize(monkeypatch):
    import chromadb
    from chromadb.utils import embedding_functions

    class EmptyCollection:
        metadata = {}

    class EmptyClient:
        def get_or_create_collection(self, **_kwargs):
            return EmptyCollection()

        def delete_collection(self, _name):
            return None

    monkeypatch.setattr(
        embedding_functions,
        "SentenceTransformerEmbeddingFunction",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        chromadb,
        "PersistentClient",
        lambda **_kwargs: EmptyClient(),
    )
    sys.modules.pop("vectorize", None)
    module = importlib.import_module("vectorize")
    yield module
    sys.modules.pop("vectorize", None)


def test_rerank_uses_glossary_terms_for_non_italian_questions(
    vectorize, monkeypatch
):
    class FakeCrossEncoder:
        queries = []

        def predict(self, pairs, **_kwargs):
            self.queries.extend(query for query, _document in pairs)
            return [
                1.0
                if "residenza" in query.lower()
                and "residenza" in document.lower()
                else -2.0
                for query, document in pairs
            ]

    encoder = FakeCrossEncoder()
    monkeypatch.setattr(vectorize, "_cross_encoder", encoder)
    monkeypatch.setattr(vectorize, "_cross_encoder_failed", False)
    records = [
        {
            "id": "identity-card",
            "document": "Servizio: Carta d'identità elettronica",
            "metadata": {"service": "Carta d'identità", "type": "service"},
        },
        {
            "id": "residence-certificate",
            "document": "Servizio: Certificati anagrafici. Residenza online.",
            "metadata": {"service": "Certificati anagrafici", "type": "service"},
        },
    ]

    ranked = vectorize._rerank(
        "অনলাইনে বসবাসের সনদ চাওয়া যায় কি?",
        records,
        limit=1,
    )

    assert any("residenza" in query for query in encoder.queries)
    assert [record["id"] for record in ranked] == ["residence-certificate"]


def test_multilingual_glossary_matches_each_script(vectorize):
    terms = vectorize._glossary_terms

    assert {"cambio", "residenza"} <= set(terms("palitan ang aking tirahan"))
    assert "documenti" in terms("Які потрібні документи?")
    assert "residenza" in terms("বসবাসের সনদ চাওয়া যায়")
    assert "residenza" in terms("كيف أحصل على شهادة الإقامة؟")
    assert {"carta", "identità"} <= set(terms("如何在罗马申请电子身份证？"))
    assert terms("Come posso cambiare residenza?") == []


def test_with_glossary_adds_only_missing_terms(vectorize):
    enriched = vectorize._with_glossary(
        "Quali documenti per sostituire la residenza?",
        ["documenti", "cambio", "residenza"],
    )

    assert enriched == "Quali documenti per sostituire la residenza? cambio"


def test_pages_are_chunked_by_markdown_heading(vectorize):
    page = next(item for item in vectorize.corpus if item["id"] == "cie-costi")
    chunks = list(vectorize._page_chunks(page))

    assert chunks
    document, metadata = chunks[0]
    assert metadata["section"] == "Costi"
    assert metadata["source_id"] == "cie-costi"
    assert metadata["type"] == "pagina"
    assert document.startswith(f"Servizio: {page['title']}\nSezione: Costi\n")
    assert "22,21" in document
    assert "###" not in document


def test_every_page_produces_chunks_without_portal_boilerplate(vectorize):
    for page in (item for item in vectorize.corpus if item["kind"] == "pagina"):
        chunks = list(vectorize._page_chunks(page))
        assert chunks, page["id"]
        for document, _metadata in chunks:
            assert "Ti è stata utile" not in document
            assert "Julia" not in document
