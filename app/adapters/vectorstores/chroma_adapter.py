# app/adapters/vectorstores/chroma_adapter.py
"""
Chroma VectorStore adaptoru.
- load_or_create_chroma: persist klasoru ve koleksiyon ismiyle store doner.
- build_or_refresh_index: PDF kaynaklarindan chunk'lar uretip belirtilen koleksiyona yazar.
- retrieve_context: tenant/profil filtresi ile benzerlik aramasi yapar.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


# ---- Embeddings ----
def get_embeddings():
    """Tek noktadan embedding saglayicisi."""

    return OpenAIEmbeddings()


def _default_collection_name() -> str:
    tenant = settings.default_tenant_id or "default"
    return f"{tenant}_default"


# ---- Store lifecycle ----
def load_or_create_chroma(
    persist_dir: Optional[str] = None,
    *,
    collection_name: Optional[str] = None,
) -> Chroma:
    persist_dir = persist_dir or settings.persist_dir
    os.makedirs(persist_dir, exist_ok=True)
    collection = collection_name or _default_collection_name()
    return Chroma(
        persist_directory=persist_dir,
        collection_name=collection,
        embedding_function=get_embeddings(),
    )


def build_or_refresh_index(
    sources: Iterable[str],
    persist_dir: Optional[str] = None,
    *,
    tenant_id: Optional[str],
    profile_key: str,
    collection_name: Optional[str] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 50,
) -> Chroma:
    persist_dir = persist_dir or settings.persist_dir
    collection = collection_name or (f"{tenant_id}_{profile_key}" if tenant_id else profile_key)
    vector = load_or_create_chroma(persist_dir, collection_name=collection)

    all_docs = []
    for path in sources:
        p = path.strip()
        if not p:
            continue
        if not os.path.exists(p):
            continue
        loader = PyPDFLoader(p)
        docs = loader.load()

        for d in docs:
            md: Dict[str, str] = dict(d.metadata or {})
            md["profile_key"] = profile_key
            md["tenant_id"] = tenant_id or settings.default_tenant_id or "default"
            d.metadata = md
        all_docs.extend(docs)

    if not all_docs:
        return vector

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n\n", "\n\n", "\n", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )
    chunks = splitter.split_documents(all_docs)

    Chroma.from_documents(
        chunks,
        embedding=get_embeddings(),
        persist_directory=persist_dir,
        collection_name=collection,
    ).persist()

    return load_or_create_chroma(persist_dir, collection_name=collection)


# ---- Retrieval helper ----
def _build_filter(tenant_id: Optional[str], profile_key: str) -> Optional[Dict[str, object]]:
    clauses = []
    clauses.append({"profile_key": {"$eq": profile_key}})
    if tenant_id:
        clauses.append({"tenant_id": {"$eq": tenant_id}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def retrieve_context(
    vector: Chroma,
    query: str,
    *,
    tenant_id: Optional[str],
    profile_key: str,
    k: int = 6,
) -> str:
    filters = _build_filter(tenant_id, profile_key)
    docs = vector.similarity_search(query, k=k, filter=filters)
    return "\n\n".join([d.page_content for d in docs])
