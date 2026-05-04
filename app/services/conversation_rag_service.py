"""Conversation history RAG retrieval using embeddings."""

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import MessageEmbedding
from . import embedding_service


async def save_turn_embedding(
    *,
    user_id: str,
    conversation_id: str,
    turn_start_id: str | None,
    turn_end_id: str | None,
    content: str,
) -> None:
    """Compute and store embedding for a conversation turn (fire-and-forget)."""
    if not embedding_service.is_available() or not content.strip():
        return
    db = SessionLocal()
    try:
        vector = await embedding_service.compute_embedding(content)
        if vector:
            record = MessageEmbedding(
                user_id=user_id,
                conversation_id=conversation_id,
                turn_start_id=turn_start_id,
                turn_end_id=turn_end_id,
                content=content.strip(),
                embedding=embedding_service.serialize(vector),
            )
            db.add(record)
            db.commit()
    except Exception as error:
        db.rollback()
        print(f"Failed to save turn embedding: {error}")
    finally:
        db.close()


async def search_relevant_turns(
    db,
    user_id: str,
    query: str,
) -> list[MessageEmbedding]:
    """Search conversation history for turns relevant to the current query."""
    if not embedding_service.is_available() or not query.strip():
        return []

    query_embedding = await embedding_service.compute_embedding(query)
    if not query_embedding:
        return []

    stmt = (
        select(MessageEmbedding)
        .where(
            MessageEmbedding.user_id == user_id,
            MessageEmbedding.embedding.isnot(None),
        )
        .order_by(MessageEmbedding.created_at.desc())
        .limit(200)
    )
    all_embeddings = list(db.execute(stmt).scalars().all())

    # Lazy backfill for any that are missing
    missing = [e for e in all_embeddings if not e.embedding]
    if missing:
        texts = [e.content for e in missing]
        vectors = await embedding_service.compute_embeddings(texts)
        for record, vector in zip(missing, vectors):
            if vector:
                record.embedding = embedding_service.serialize(vector)
        db.flush()

    # Score and rank
    scored: list[tuple[float, MessageEmbedding]] = []
    for record in all_embeddings:
        vec = embedding_service.deserialize(record.embedding)
        if vec:
            score = embedding_service.cosine_similarity(query_embedding, vec)
            scored.append((score, record))

    threshold = settings.RAG_SIMILARITY_THRESHOLD
    max_results = settings.RAG_MAX_RESULTS
    scored.sort(key=lambda x: x[0], reverse=True)

    return [record for score, record in scored if score >= threshold][:max_results]


def format_rag_context(turns: list[MessageEmbedding]) -> str | None:
    """Format retrieved conversation turns as context for LLM injection."""
    if not turns:
        return None

    sections: list[str] = []
    for turn in turns:
        sections.append(f"- [历史对话片段] {turn.content}")

    return (
        "以下是用户历史对话中与当前话题相关的片段：\n"
        + "\n".join(sections)
        + "\n请结合这些历史上下文来回答用户的问题。如果历史片段与当前问题无关，请忽略。"
    )
