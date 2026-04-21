import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..config import AVAILABLE_MODEL_OPTIONS, get_default_model, get_supported_model_ids
from ..database import SessionLocal, get_db
from ..models import Conversation, User
from ..schemas import ChatRequest, LandingChatRequest, ModelCatalog
from ..services import llm_service, memory_service
from ..services.attachment_service import save_attachments
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api", tags=["chat"])

LANDING_AGENT_SYSTEM_PROMPT = """
你是 CHAT A.I+ 网站首页里的导览 agent。

你的任务不是泛泛介绍 AI，而是准确介绍这个网站当前已经具备的能力，并引导用户继续体验。

当前网站可以明确介绍的能力：
1. 用户可以注册、登录、退出登录，账号数据会保存在本地数据库中。
2. 登录后可以创建和保存对话，会话按用户隔离。
3. 聊天支持长记忆上下文，历史消息会参与后续对话。
4. 支持上传图片和普通文件，消息里会展示附件。
5. 侧边栏支持会话搜索和清空全部会话。
6. 用户可以在设置中切换模型和推理强度。

请遵守这些要求：
1. 用自然、简洁、友好的中文回答。
2. 把自己当作网站导览助手，而不是代码助手。
3. 只介绍当前已经具备的能力；如果用户问到未实现的功能，要明确说明“目前还没有”。
4. 多用“你可以在这个网站里……”这种面向访客的表达。
5. 回答尽量控制在 3 到 6 句话，除非用户明确要求详细说明。
""".strip()


@router.get("/models", response_model=ModelCatalog)
def list_models():
    return {
        "default_model": get_default_model(),
        "models": AVAILABLE_MODEL_OPTIONS,
    }


@router.post("/landing-chat")
async def landing_chat(body: LandingChatRequest):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    history = [
        {"role": item.role, "content": item.content.strip()}
        for item in body.history[-8:]
        if item.content.strip()
    ]
    history.append({"role": "user", "content": message})

    async def event_stream():
        stream_cancelled = False

        try:
            async for chunk in llm_service.stream_chat_completion(
                history,
                model=get_default_model(),
                reasoning_level="off",
                system_prompt=LANDING_AGENT_SYSTEM_PROMPT,
            ):
                yield f"data: {json.dumps({'content': chunk})}\n\n"
        except asyncio.CancelledError:
            stream_cancelled = True
            raise
        except Exception as error:
            yield f"data: {json.dumps({'error': str(error)})}\n\n"

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


async def _parse_chat_request(request: Request) -> tuple[ChatRequest, list[UploadFile]]:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploads = [item for item in form.getlist("files") if isinstance(item, StarletteUploadFile)]
        chat_request = ChatRequest(
            conversation_id=form.get("conversation_id") or None,
            message=(form.get("message") or "").strip(),
            model=form.get("model") or None,
            reasoning_level=form.get("reasoning_level") or None,
            mode=form.get("mode") or None,
        )
        return chat_request, uploads

    payload = await request.json()
    return ChatRequest(**payload), []


@router.post("/chat")
async def chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message and receive a streaming LLM response via SSE."""

    req, uploads = await _parse_chat_request(request)
    if not req.message.strip() and not uploads:
        raise HTTPException(status_code=400, detail="Message text or attachments are required")

    created_new_conversation = req.conversation_id is None

    if req.conversation_id:
        conv = db.get(Conversation, req.conversation_id)
        if not conv or conv.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = Conversation(user_id=current_user.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)

    chosen_model = req.model or get_default_model()
    if chosen_model not in get_supported_model_ids():
        raise HTTPException(status_code=400, detail=f"Model `{chosen_model}` is not supported")

    user_message = memory_service.store_message(db, conv.id, "user", req.message.strip())
    if uploads:
        try:
            save_db = SessionLocal()
            try:
                await save_attachments(save_db, user_message.id, uploads)
            finally:
                save_db.close()
        except HTTPException:
            db.delete(user_message)
            if created_new_conversation:
                db.delete(conv)
            db.commit()
            raise

    if created_new_conversation:
        title_source = req.message.strip() or next(
            (upload.filename for upload in uploads if upload.filename),
            "新对话",
        )
        conv.title = title_source[:50] + ("..." if len(title_source) > 50 else "")
        db.commit()

    context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)
    conv_id = conv.id

    async def event_stream():
        full_response: list[str] = []
        stream_cancelled = False

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
        except Exception as error:
            yield f"data: {json.dumps({'error': str(error)})}\n\n"
        finally:
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
