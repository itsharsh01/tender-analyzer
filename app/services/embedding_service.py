from typing import Any
import logging

logger = logging.getLogger(__name__)

# Global model instance for lazy loading
_model = None

def _get_embedding_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded successfully.")
        except ImportError:
            logger.error("sentence-transformers is not installed.")
            raise RuntimeError("sentence-transformers is not installed")
    return _model


def build_semantic_embeddings(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build semantic embedding documents from classified canonical items.
    The text for embedding is a concatenation of the raw values of:
    heading, text_norm, key_norm, value_norm, and category.
    """
    embeddings = []
    
    # Exclude metadata keys from canonical dict to iterate only over categories
    skip_keys = {"total_classified", "total_ignored", "batch_count", "tender_id", "pdf_path", "created_at"}
    
    for category_name, items in canonical.items():
        if category_name in skip_keys:
            continue
            
        for item in items:
            # Gather available text fields without label prefixes
            parts = []
            if item.get("heading"):
                parts.append(str(item["heading"]).strip())
            if item.get("text_norm"):
                parts.append(str(item["text_norm"]).strip())
            if item.get("key_norm"):
                parts.append(str(item["key_norm"]).strip())
            if item.get("value_norm"):
                parts.append(str(item["value_norm"]).strip())
            if item.get("category"):
                parts.append(str(item["category"]).strip())
                
            # Filter out empty strings
            parts = [p for p in parts if p]
            concatenated_text = " | ".join(parts)
            
            embeddings.append({
                "evidence_id": item.get("evidence_id"),
                "category": item.get("category"),
                "sub_component": item.get("sub_component"),
                "embedding": [],  # To be populated
                "text": concatenated_text,
                "status": "ready",
            })
            
    if not embeddings:
        return []

    # Batch generate embeddings
    try:
        model = _get_embedding_model()
        texts_to_embed = [doc["text"] for doc in embeddings]
        
        logger.info("Generating embeddings for %d items...", len(texts_to_embed))
        vectors = model.encode(texts_to_embed, convert_to_numpy=True)
        
        # Populate the actual float arrays
        for idx, doc in enumerate(embeddings):
            doc["embedding"] = vectors[idx].tolist()
            
    except Exception as e:
        logger.error("Failed to generate embeddings: %s", e)
        for doc in embeddings:
            doc["status"] = f"failed_generation: {e}"
            
    return embeddings


def build_submission_embeddings(evidence_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build semantic embeddings for submission evidence documents.
    Creates search_text from: heading, key_norm, value_norm, text_norm
    Then generates embeddings using the same sentence-transformers model.
    """
    embeddings = []

    for ev in evidence_docs:
        # Build search_text: heading | key_norm | value_norm | text_norm
        parts = list(filter(None, [
            str(ev.get("heading", "")).strip() or None,
            str(ev.get("key_norm", "")).strip() or None,
            str(ev.get("value_norm", "")).strip() or None,
            str(ev.get("text_norm", "")).strip() or None,
        ]))
        search_text = " | ".join(parts)

        embeddings.append({
            "evidence_id": ev.get("evidence_id"),
            "source": ev.get("source"),
            "page": ev.get("page"),
            "heading": ev.get("heading"),
            "text_norm": ev.get("text_norm"),
            "key_norm": ev.get("key_norm"),
            "value_norm": ev.get("value_norm"),
            "search_text": search_text,
            "embedding": [],
            "bbox": ev.get("bbox"),
            "confidence": ev.get("confidence"),
            "status": "ready",
        })

    if not embeddings:
        return []

    # Batch generate embeddings
    try:
        model = _get_embedding_model()
        texts_to_embed = [doc["search_text"] for doc in embeddings]

        logger.info("Generating submission embeddings for %d items...", len(texts_to_embed))
        vectors = model.encode(texts_to_embed, convert_to_numpy=True)

        for idx, doc in enumerate(embeddings):
            doc["embedding"] = vectors[idx].tolist()

    except Exception as e:
        logger.error("Failed to generate submission embeddings: %s", e)
        for doc in embeddings:
            doc["status"] = f"failed_generation: {e}"

    return embeddings

