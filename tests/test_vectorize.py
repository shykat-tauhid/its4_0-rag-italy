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


def test_rerank_uses_italian_translation_for_italian_documents(
    vectorize, monkeypatch
):
    class FakeCrossEncoder:
        queries = []

        def predict(self, pairs, **_kwargs):
            self.queries.extend(query for query, _document in pairs)
            return [
                1.0
                if "certificato di residenza" in query.lower()
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
        italian="È possibile richiedere online il certificato di residenza?",
    )

    assert encoder.queries == [
        "È possibile richiedere online il certificato di residenza?",
        "È possibile richiedere online il certificato di residenza?",
    ]
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


def test_cie_documentation_is_chunked_by_application_type(vectorize):
    from data.anagrafe import docs

    cie = next(doc for doc in docs if doc["id"] == "anagrafe_Carta_identita_elettronica")
    chunks = list(vectorize._service_chunks(cie))

    first_issue = next(
        document
        for document, metadata in chunks
        if metadata["section"] == "Documenti per il primo rilascio o il rinnovo della CIE"
    )
    duplicate = next(
        document
        for document, metadata in chunks
        if metadata["section"]
        == "Documenti per il duplicato della CIE in caso di deterioramento, furto o smarrimento"
    )

    assert "Fototessera" in first_issue
    assert "Documento di riconoscimento valido" in first_issue
    assert "Codice fiscale o tessera sanitaria" in first_issue
    assert "denuncia originale" not in first_issue.lower()
    assert "carta d'identità deteriorata" not in first_issue.lower()
    assert "denuncia originale" in duplicate.lower()
    assert "carta d'identità deteriorata" in duplicate.lower()
    assert "Fototessera" not in duplicate
