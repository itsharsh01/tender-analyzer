from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer


def build_tfidf_index(evidence_docs: list[dict[str, Any]]) -> dict[str, Any]:
    texts = [doc.get("text_norm", "") for doc in evidence_docs if doc.get("text_norm")]
    if not texts:
        return {"vocabulary": {}, "matrix_shape": [0, 0]}

    vectorizer = TfidfVectorizer(max_features=5000)
    matrix = vectorizer.fit_transform(texts)
    return {
        "vocabulary": vectorizer.vocabulary_,
        "matrix_shape": [int(matrix.shape[0]), int(matrix.shape[1])],
    }


def build_semantic_embeddings(evidence_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Placeholder: replace with real embedding model integration.
    return [
        {
            "evidence_id": doc.get("evidence_id"),
            "embedding": [],
            "text": doc.get("text_norm", ""),
            "status": "pending_model_integration",
        }
        for doc in evidence_docs
    ]

