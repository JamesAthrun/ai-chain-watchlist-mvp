"""Vector store module using ChromaDB for knowledge retrieval."""

import logging
from pathlib import Path
from uuid import uuid4

import chromadb

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "chroma_db"

_client = None
_collection = None


def _get_collection():
    """Lazy-initialize ChromaDB client and collection."""
    global _client, _collection
    if _collection is None:
        DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(DB_PATH))
        _collection = _client.get_or_create_collection(
            name="trading_knowledge",
        )
    return _collection


def add_knowledge(text: str, source: str = "manual", metadata: dict | None = None) -> str:
    """Add a knowledge document to the vector store.

    Returns the document ID.
    """
    collection = _get_collection()
    doc_id = f"doc_{uuid4().hex[:12]}"

    doc_metadata = {"source": source}
    if metadata:
        doc_metadata.update(metadata)

    collection.add(
        documents=[text],
        metadatas=[doc_metadata],
        ids=[doc_id],
    )
    logger.info(f"Added document {doc_id} to vector store (source={source})")
    return doc_id


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """Search for relevant knowledge documents.

    Returns list of {text, source, distance}.
    """
    collection = _get_collection()

    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
    )

    docs = []
    for i, doc in enumerate(results["documents"][0]):
        docs.append({
            "text": doc,
            "source": results["metadatas"][0][i].get("source", "unknown"),
            "distance": results["distances"][0][i] if results.get("distances") else None,
        })
    return docs


def get_all_documents(limit: int = 100) -> list[dict]:
    """Get all documents in the store (for debugging/viewing)."""
    collection = _get_collection()

    if collection.count() == 0:
        return []

    results = collection.get(limit=limit)

    docs = []
    for i, doc in enumerate(results["documents"]):
        docs.append({
            "id": results["ids"][i],
            "text": doc,
            "source": results["metadatas"][i].get("source", "unknown"),
        })
    return docs


def delete_document(doc_id: str) -> bool:
    """Delete a document by ID."""
    collection = _get_collection()
    try:
        collection.delete(ids=[doc_id])
        return True
    except Exception as e:
        logger.warning(f"Failed to delete document {doc_id}: {e}")
        return False


def get_stats() -> dict:
    """Get vector store statistics."""
    collection = _get_collection()
    return {
        "total_documents": collection.count(),
        "db_path": str(DB_PATH),
    }
