import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import AVAILABLE_MODEL_OPTIONS, get_default_model, get_supported_model_ids
from ..database import SessionLocal, get_db
from ..models import Conversation
from ..schemas import ChatRequest, ModelCatalog
from ..services import llm_service, memory_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/models", response_model=ModelCatalog)
def list_models():
    return {
        "default_model": get_default_model(),
        "models": AVAILABLE_MODEL_OPTIONS,
    }


@router.post("/chat")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """Send a message and receive a streaming LLM response via SSE.

    If conversation_id is not provided, a new conversation is created.
    The user message is stored before calling the LLM.
    The assistant response is stored after the stream completes.
    """
    # Create or validate conversation
    if req.conversation_id:
        conv = db.get(Conversation, req.conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = Conversation()
        db.add(conv)
        db.commit()
        db.refresh(conv)

    chosen_model = req.model or get_default_model()
    if chosen_model not in get_supported_model_ids():
        raise HTTPException(status_code=400, detail=f"Model `{chosen_model}` is not supported")

    # Store user message
    memory_service.store_message(db, conv.id, "user", req.message)

    # Auto-generate title from the first user message
    if conv.title == "新对话":
        conv.title = req.message[:50] + ("..." if len(req.message) > 50 else "")
        db.commit()

    # Build context from memory
    context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)

    # Capture values before the DB session closes
    conv_id = conv.id

    async def event_stream():
        full_response = []
        stream_cancelled = False

        # Send conversation_id as the first event (for new conversations)
        yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"

        try:
            async for chunk in llm_service.stream_chat_completion(
                context,
                model=chosen_model,
                reasoning_level=req.reasoning_level,
                legacy_mode=req.mode,
            ):
                full_response.append(chunk)
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except asyncio.CancelledError:
            stream_cancelled = True
            raise
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Persist partial assistant output even if the client stops streaming midway.
            assistant_content = "".join(full_response)
            if assistant_content:
                save_db = SessionLocal()
                try:
                    memory_service.store_message(
                        save_db,
                        conv_id,
                        "assistant",
                        assistant_content,
                        model=chosen_model,
                    )
                finally:
                    save_db.close()

        if not stream_cancelled:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
