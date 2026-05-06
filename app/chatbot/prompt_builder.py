def build_answer_prompt(query: str, contexts: list[dict]) -> str:
    context_text = "\n".join(f"- {c.get('text_norm', '')}" for c in contexts[:10])
    return f"Question: {query}\n\nRelevant Context:\n{context_text}"

