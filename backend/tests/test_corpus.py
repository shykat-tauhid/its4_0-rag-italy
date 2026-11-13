import json

import pytest

import corpus


def test_corpus_reale_valido():
    items = corpus.load_corpus()
    kinds = {item["kind"] for item in items}

    assert kinds <= {corpus.PAGE_KIND, *corpus.FILE_KINDS}
    pages = [item for item in items if item["kind"] == corpus.PAGE_KIND]
    assert pages and all(page["text"] for page in pages)


def test_clean_markdown_toglie_coda_del_portale_e_tag():
    text = (
        "### Costi\n\nSul sito <u>https://www.poste.it/</u>.\n"
        "Vedi [la guida](https://example.org/g).\n\n"
        "#### Ti è stata utile questa pagina?\n\nCiao, sono Julia"
    )

    assert corpus.clean_markdown(text) == (
        "### Costi\n\nSul sito https://www.poste.it/.\n"
        "Vedi la guida (https://example.org/g)."
    )


def _write(tmp_path, entries, files=()):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in files:
        (docs / name).write_text("### Titolo\n\nTesto.", encoding="utf-8")
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps(entries), encoding="utf-8")
    return sources, docs


def test_load_corpus_segnala_file_mancanti(tmp_path):
    sources, docs = _write(
        tmp_path, [{"id": "a", "title": "A", "kind": "pagina", "file": "a.md"}]
    )
    with pytest.raises(corpus.CorpusError, match="File mancante"):
        corpus.load_corpus(sources, docs)


def test_load_corpus_segnala_moduli_inesistenti(tmp_path):
    sources, docs = _write(
        tmp_path,
        [{"id": "a", "title": "A", "kind": "pagina", "file": "a.md", "forms": ["x"]}],
        files=["a.md"],
    )
    with pytest.raises(corpus.CorpusError, match="moduli inesistenti"):
        corpus.load_corpus(sources, docs)
