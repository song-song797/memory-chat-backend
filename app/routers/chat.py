import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..config import (
    AVAILABLE_MODEL_OPTIONS,
    get_default_model,
    get_memory_model,
    get_supported_model_ids,
    settings,
)
from ..database import SessionLocal, get_db
from ..models import Conversation, User
from ..schemas import ChatRequest, LandingChatRequest, ModelCatalog
from ..services import (
    conversation_memory_service,
    llm_service,
    memory_candidate_service,
    memory_document_service,
    memory_extraction_service,
    memory_service,
)
from ..services.attachment_service import save_attachments
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project

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
            project_id=form.get("project_id") or None,
            message=(form.get("message") or "").strip(),
            model=form.get("model") or None,
            reasoning_level=form.get("reasoning_level") or None,
            mode=form.get("mode") or None,
        )
        return chat_request, uploads

    payload = await request.json()
    return ChatRequest(**payload), []


async def _extract_and_store_memory_candidate(
    *,
    user_id: str,
    project_id: str | None,
    conversation_id: str | None,
    source_message_id: str | None,
    user_content: str,
    model: str | None,
) -> None:
    if not settings.MEMORY_AUTO_SUGGESTIONS_ENABLED:
        return
    if memory_service.has_explicit_memory_intent(user_content):
        return

    db = SessionLocal()
    try:
        existing_memories = memory_service.get_enabled_memories_for_context(
            db,
            user_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        memory_model = get_memory_model()
        candidate = await memory_extraction_service.extract_memory_candidate(
            user_content,
            project_id,
            conversation_id,
            existing_memories,
            model=memory_model,
        )
        if candidate is None:
            return

        scope, resolved_project_id, resolved_conversation_id = (
            memory_extraction_service.resolve_candidate_scope(
                project_id=project_id,
                conversation_id=conversation_id,
                kind=candidate.kind,
                suggested_scope=candidate.scope,
            )
        )
        if scope is None:
            return

        if scope == "conversation" and settings.MEMORY_CONVERSATION_AUTO_ACCEPT:
            memory_candidate_service.auto_accept_memory_candidate(
                db,
                user_id=user_id,
                scope=scope,
                project_id=resolved_project_id,
                conversation_id=resolved_conversation_id,
                action=candidate.action,
                target_memory_id=candidate.target_memory_id,
                content=candidate.content,
                kind=candidate.kind,
                confidence=candidate.confidence,
                importance=candidate.importance,
                reason=candidate.reason,
                source_message_id=source_message_id,
                extraction_model=memory_model,
            )
            await conversation_memory_service.compact_conversation_memories(
                db,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
            )
            await memory_document_service.rebuild_memory_document(
                db,
                user_id=user_id,
                scope="conversation",
                conversation_id=resolved_conversation_id,
            )
            return

        surface = memory_extraction_service.choose_candidate_surface(candidate)
        memory_candidate_service.create_memory_candidate(
            db,
            user_id=user_id,
            scope=scope,
            project_id=resolved_project_id,
            conversation_id=resolved_conversation_id,
            action=candidate.action,
            target_memory_id=candidate.target_memory_id,
            content=candidate.content,
            kind=candidate.kind,
            confidence=candidate.confidence,
            importance=candidate.importance,
            reason=candidate.reason,
            surface=surface,
            source_message_id=source_message_id,
            extraction_model=memory_model,
        )
    except Exception as error:
        db.rollback()
        print(f"Failed to extract memory candidate: {error}")
    finally:
        db.close()


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
        if req.project_id is not None and req.project_id != conv.project_id:
            raise HTTPException(status_code=400, detail="Conversation project mismatch")
    else:
        project_id = None
        if req.project_id:
            project_id = get_user_project(db, current_user.id, req.project_id).id
        conv = Conversation(user_id=current_user.id, project_id=project_id)
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

    memory_state_notice: dict[str, str] | None = None
    try:
        explicit_memory_values = memory_service.get_explicit_memory_values(
            user_message,
            project_id=conv.project_id,
            conversation_id=conv.id,
        )
        if explicit_memory_values is not None:
            scope = explicit_memory_values["scope"] or "global"
            project_id = explicit_memory_values["project_id"]
            conversation_id = explicit_memory_values["conversation_id"]
            content = explicit_memory_values["content"] or ""
            kind = explicit_memory_values["kind"] or "fact"
            match_action, target_memory = memory_candidate_service.find_existing_memory_match(
                db,
                user_id=current_user.id,
                scope=scope,
                project_id=project_id,
                conversation_id=conversation_id,
                content=content,
                kind=kind,
            )
            if match_action == "duplicate":
                memory_state_notice = {
                    "role": "system",
                    "content": (
                        "用户刚刚要求记录一条长期记忆，但系统发现同作用域内已经有等价的已确认记忆。"
                        "不要说刚刚新增或覆盖了记忆；请简短说明这条记忆已经存在，无需重复保存。"
                    ),
                }
            else:
                candidate_action = "update" if match_action == "update" else "create"
                if scope == "conversation" and settings.MEMORY_CONVERSATION_AUTO_ACCEPT:
                    memory_candidate_service.auto_accept_memory_candidate(
                        db,
                        user_id=current_user.id,
                        scope=scope,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        action=candidate_action,
                        target_memory_id=target_memory.id if target_memory is not None else None,
                        content=content,
                        kind=kind,
                        confidence=100,
                        importance=100,
                        reason=(
                            "用户明确要求更新当前会话记忆。"
                            if candidate_action == "update"
                            else "用户明确要求记录当前会话记忆。"
                        ),
                        source_message_id=user_message.id,
                        extraction_model=get_memory_model(),
                    )
                    await conversation_memory_service.compact_conversation_memories(
                        db,
                        user_id=current_user.id,
                        conversation_id=conversation_id,
                    )
                    await memory_document_service.rebuild_memory_document(
                        db,
                        user_id=current_user.id,
                        scope="conversation",
                        conversation_id=conversation_id,
                    )
                    memory_state_notice = {
                        "role": "system",
                        "content": (
                            "用户刚刚要求记录或更新当前会话记忆。"
                            "系统已经自动保存到当前会话记忆，不需要用户在提示卡片中确认。"
                            "回答时可以简短说明当前会话记忆已更新。"
                        ),
                    }
                else:
                    memory_candidate_service.create_memory_candidate(
                        db,
                        user_id=current_user.id,
                        scope=scope,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        action=candidate_action,
                        target_memory_id=target_memory.id if target_memory is not None else None,
                        content=content,
                        kind=kind,
                        confidence=100,
                        importance=100,
                        reason=(
                            "用户明确要求更新这条信息。"
                            if candidate_action == "update"
                            else "用户明确要求记住这条信息。"
                        ),
                        surface="inline",
                        source_message_id=user_message.id,
                        extraction_model=None,
                    )
                    memory_state_notice = {
                        "role": "system",
                        "content": (
                            "用户刚刚提出了需要记录或更新长期记忆的内容。"
                            "系统目前只创建了待确认的候选记忆，尚未正式保存或覆盖任何长期记忆。"
                            "回答时不要说已经记住、已经保存或已经覆盖；请说明需要用户在右侧提示卡片中确认后才会生效。"
                        ),
                    }
    except Exception as error:
        db.rollback()
        print(f"Failed to create explicit memory candidate: {error}")

    try:
        context = memory_service.get_chat_context_messages(
            db,
            current_user.id,
            conv.id,
            current_model=chosen_model,
            project_id=conv.project_id,
        )
    except Exception as error:
        db.rollback()
        print(f"Failed to load long-term memory context: {error}")
        context = memory_service.get_context_messages(db, conv.id, current_model=chosen_model)
    if memory_state_notice is not None:
        context.append(memory_state_notice)
    conv_id = conv.id
    conv_project_id = conv.project_id
    user_id = current_user.id
    user_content = user_message.content
    user_message_id = user_message.id
    is_explicit_memory_request = memory_service.has_explicit_memory_intent(user_content)

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
                if not is_explicit_memory_request:
                    asyncio.create_task(
                        _extract_and_store_memory_candidate(
                            user_id=user_id,
                            project_id=conv_project_id,
                            conversation_id=conv_id,
                            source_message_id=user_message_id,
                            user_content=user_content,
                            model=chosen_model,
                        )
                    )

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
