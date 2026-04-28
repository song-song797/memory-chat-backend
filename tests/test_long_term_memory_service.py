import asyncio
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Conversation, Memory, MemoryCandidate, MemoryDocument, Message, Project, User
from app.routers import chat as chat_router
from app.config import get_memory_model
from app.services import memory_service
from app.services.memory_extraction_service import ExtractedMemoryCandidate


class LongTermMemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def test_explicit_memory_intent_creates_user_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="memory@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="memory")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="请记住我使用 PyCharm 开发 Python 项目",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(db, user.id, message)

            self.assertIsNotNone(memory)
            self.assertEqual(memory.user_id, user.id)
            self.assertEqual(memory.source_message_id, message.id)
            self.assertEqual(memory.kind, "tool")
            self.assertEqual(memory.scope, "conversation")
            self.assertEqual(memory.conversation_id, conversation.id)
            self.assertIn("PyCharm", memory.content)
            self.assertFalse(memory.content.startswith("请"))
        finally:
            db.close()

    def test_non_explicit_message_does_not_create_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="quiet@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="memory")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="这个数据库怎么打开",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(db, user.id, message)

            self.assertIsNone(memory)
            self.assertEqual(db.query(Memory).count(), 0)
        finally:
            db.close()

    def test_disabled_memories_are_not_injected(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="context@example.com", password_hash="hash")
            db.add(user)
            db.commit()
            db.refresh(user)

            enabled = Memory(user_id=user.id, content="用户喜欢简洁中文回答", kind="preference")
            disabled = Memory(
                user_id=user.id,
                content="用户喜欢英文回答",
                kind="preference",
                enabled=False,
            )
            db.add_all([enabled, disabled])
            db.commit()

            context = memory_service.get_long_term_memory_context(db, user.id)

            self.assertIsNotNone(context)
            self.assertEqual(context["role"], "system")
            self.assertIn("用户喜欢简洁中文回答", context["content"])
            self.assertNotIn("用户喜欢英文回答", context["content"])
            self.assertIsNone(enabled.last_used_at)
        finally:
            db.close()

    def test_compose_context_prepends_long_term_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="compose@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="compose")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            db.add(Memory(user_id=user.id, content="用户使用 PyCharm", kind="tool"))
            db.add(Message(conversation_id=conversation.id, role="user", content="怎么打开数据库"))
            db.commit()

            context = memory_service.get_chat_context_messages(
                db,
                user.id,
                conversation.id,
                current_model="MiniMax-M2.5",
            )

            self.assertEqual(context[0]["role"], "system")
            self.assertIn("用户使用 PyCharm", context[0]["content"])
            self.assertEqual(context[1], {"role": "user", "content": "怎么打开数据库"})
        finally:
            db.close()

    def test_project_explicit_memory_is_stored_as_project_scope(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="project-memory@example.com", password_hash="hash")
            project = Project(user=user, name="Memory App")
            conversation = Conversation(user=user, project=project, title="project memory")
            db.add_all([user, project, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(project)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="请记住这个项目的接口统一走 FastAPI",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(
                db,
                user.id,
                message,
                project_id=project.id,
            )

            self.assertIsNotNone(memory)
            self.assertEqual(memory.scope, "project")
            self.assertEqual(memory.project_id, project.id)
            self.assertEqual(memory.kind, "tool")
        finally:
            db.close()

    def test_ordinary_explicit_non_preference_memory_becomes_conversation_scoped(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="global-memory@example.com", password_hash="hash")
            conversation = Conversation(user=user, title="global memory")
            db.add_all([user, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content="请记住我使用 PyCharm 开发 Python 项目",
            )
            db.add(message)
            db.commit()
            db.refresh(message)

            memory = memory_service.maybe_store_explicit_memory(db, user.id, message)

            self.assertIsNotNone(memory)
            self.assertEqual(memory.scope, "conversation")
            self.assertIsNone(memory.project_id)
            self.assertEqual(memory.conversation_id, conversation.id)
        finally:
            db.close()

    def test_memory_context_layers_global_and_current_project_active_memories(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="layered-context@example.com", password_hash="hash")
            current_project = Project(user=user, name="Current")
            other_project = Project(user=user, name="Other")
            db.add_all([user, current_project, other_project])
            db.commit()
            db.refresh(user)
            db.refresh(current_project)
            db.refresh(other_project)

            db.add_all(
                [
                    Memory(user_id=user.id, content="全局偏好：中文简洁回答", kind="preference"),
                    Memory(
                        user_id=user.id,
                        project_id=current_project.id,
                        scope="project",
                        content="当前项目：API 使用 FastAPI",
                        kind="tool",
                    ),
                    Memory(
                        user_id=user.id,
                        project_id=other_project.id,
                        scope="project",
                        content="其他项目：API 使用 Flask",
                        kind="tool",
                    ),
                    Memory(
                        user_id=user.id,
                        content="已归档：不要注入",
                        kind="fact",
                        status="archived",
                    ),
                    Memory(
                        user_id=user.id,
                        content="已禁用：不要注入",
                        kind="fact",
                        enabled=False,
                    ),
                ]
            )
            db.commit()

            ordinary_context = memory_service.get_long_term_memory_context(db, user.id)
            project_context = memory_service.get_long_term_memory_context(
                db,
                user.id,
                project_id=current_project.id,
            )

            self.assertIsNotNone(ordinary_context)
            self.assertIn("全局偏好：中文简洁回答", ordinary_context["content"])
            self.assertNotIn("当前项目：API 使用 FastAPI", ordinary_context["content"])
            self.assertNotIn("其他项目：API 使用 Flask", ordinary_context["content"])
            self.assertNotIn("已归档：不要注入", ordinary_context["content"])
            self.assertNotIn("已禁用：不要注入", ordinary_context["content"])

            self.assertIsNotNone(project_context)
            self.assertIn("全局长期记忆", project_context["content"])
            self.assertIn("当前项目长期记忆", project_context["content"])
            self.assertIn(
                "如果会话记忆、项目记忆和全局记忆冲突，优先遵循当前会话记忆，其次当前项目记忆，最后全局记忆。",
                project_context["content"],
            )
            self.assertIn("全局偏好：中文简洁回答", project_context["content"])
            self.assertIn("当前项目：API 使用 FastAPI", project_context["content"])
            self.assertNotIn("其他项目：API 使用 Flask", project_context["content"])
            self.assertNotIn("已归档：不要注入", project_context["content"])
            self.assertNotIn("已禁用：不要注入", project_context["content"])
        finally:
            db.close()

    def test_memory_context_prefers_memory_documents_when_available(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="document-context@example.com", password_hash="hash")
            project = Project(user=user, name="Memory Project")
            conversation = Conversation(user=user, project=project, title="Document Context")
            db.add_all([user, project, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(project)
            db.refresh(conversation)

            db.add_all(
                [
                    Memory(
                        user_id=user.id,
                        content="原子全局记忆：中文回答",
                        kind="preference",
                        scope="global",
                    ),
                    MemoryDocument(
                        user_id=user.id,
                        scope="global",
                        content_md="# 全局记忆\n\n## 回答偏好\n- 用户喜欢中文回答。",
                        source_memory_ids="memory-a",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_long_term_memory_context(
                db,
                user.id,
                project_id=project.id,
                conversation_id=conversation.id,
            )

            self.assertIsNotNone(context)
            self.assertIn("# 全局记忆", context["content"])
            self.assertIn("用户喜欢中文回答", context["content"])
            self.assertNotIn("原子全局记忆：中文回答", context["content"])
        finally:
            db.close()

    def test_context_injects_current_conversation_memory_only(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="conversation-context@example.com", password_hash="hash")
            current_conversation = Conversation(user=user, title="Current")
            other_conversation = Conversation(user=user, title="Other")
            db.add_all([user, current_conversation, other_conversation])
            db.commit()
            db.refresh(user)
            db.refresh(current_conversation)
            db.refresh(other_conversation)

            db.add_all(
                [
                    Memory(
                        user_id=user.id,
                        conversation_id=current_conversation.id,
                        scope="conversation",
                        content="当前会话：用户正在排查上传失败",
                        kind="fact",
                    ),
                    Memory(
                        user_id=user.id,
                        conversation_id=other_conversation.id,
                        scope="conversation",
                        content="其他会话：用户正在写发布说明",
                        kind="fact",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_long_term_memory_context(
                db,
                user.id,
                conversation_id=current_conversation.id,
            )

            self.assertIsNotNone(context)
            self.assertIn("当前会话记忆", context["content"])
            self.assertIn("当前会话：用户正在排查上传失败", context["content"])
            self.assertNotIn("其他会话：用户正在写发布说明", context["content"])
        finally:
            db.close()

    def test_same_project_different_conversation_shares_project_memory(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="project-shared-context@example.com", password_hash="hash")
            project = Project(user=user, name="Shared Project")
            current_conversation = Conversation(user=user, project=project, title="Current")
            other_conversation = Conversation(user=user, project=project, title="Other")
            db.add_all([user, project, current_conversation, other_conversation])
            db.commit()
            db.refresh(user)
            db.refresh(project)
            db.refresh(current_conversation)
            db.refresh(other_conversation)

            db.add_all(
                [
                    Memory(
                        user_id=user.id,
                        project_id=project.id,
                        scope="project",
                        content="项目共享：后端使用 FastAPI",
                        kind="tool",
                    ),
                    Memory(
                        user_id=user.id,
                        conversation_id=other_conversation.id,
                        scope="conversation",
                        content="其他会话：不要进入当前上下文",
                        kind="fact",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_long_term_memory_context(
                db,
                user.id,
                project_id=project.id,
                conversation_id=current_conversation.id,
            )

            self.assertIsNotNone(context)
            self.assertIn("项目共享：后端使用 FastAPI", context["content"])
            self.assertNotIn("其他会话：不要进入当前上下文", context["content"])
        finally:
            db.close()

    def test_memory_context_sections_are_ordered_global_project_conversation(self) -> None:
        db = self.SessionLocal()
        try:
            user = User(email="section-order@example.com", password_hash="hash")
            project = Project(user=user, name="Ordered Project")
            conversation = Conversation(user=user, project=project, title="Ordered")
            db.add_all([user, project, conversation])
            db.commit()
            db.refresh(user)
            db.refresh(project)
            db.refresh(conversation)

            db.add_all(
                [
                    Memory(user_id=user.id, content="全局：使用中文", kind="preference"),
                    Memory(
                        user_id=user.id,
                        project_id=project.id,
                        scope="project",
                        content="项目：使用 PostgreSQL",
                        kind="tool",
                    ),
                    Memory(
                        user_id=user.id,
                        conversation_id=conversation.id,
                        scope="conversation",
                        content="会话：正在定位 500",
                        kind="fact",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_long_term_memory_context(
                db,
                user.id,
                project_id=project.id,
                conversation_id=conversation.id,
            )

            self.assertIsNotNone(context)
            content = context["content"]
            self.assertLess(content.index("全局长期记忆："), content.index("当前项目长期记忆："))
            self.assertLess(content.index("当前项目长期记忆："), content.index("当前会话记忆："))
            self.assertIn(
                "如果会话记忆、项目记忆和全局记忆冲突，优先遵循当前会话记忆，其次当前项目记忆，最后全局记忆。",
                content,
            )
        finally:
            db.close()


class ChatMemoryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "chat-memory-route.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.original_chat_session_local = chat_router.SessionLocal

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        chat_router.SessionLocal = self.original_chat_session_local
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _install_db_override(self) -> None:
        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        chat_router.SessionLocal = self.SessionLocal

    def _register(self, client: TestClient, email: str) -> dict[str, str]:
        register_response = client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 201)
        return {"Authorization": f"Bearer {register_response.json()['token']}"}

    def _create_project(self, client: TestClient, headers: dict[str, str], name: str) -> str:
        response = client.post("/api/projects", json={"name": name}, headers=headers)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def _create_chat_records(
        self,
        *,
        project_chat: bool,
        user_content: str = "这个项目后端使用 FastAPI",
    ) -> tuple[str, str | None, str, str]:
        db = self.SessionLocal()
        try:
            user = User(email="candidate@example.com", password_hash="hash")
            db.add(user)
            db.commit()
            db.refresh(user)

            project = None
            if project_chat:
                project = Project(user_id=user.id, name="Candidate Project")
                db.add(project)
                db.commit()
                db.refresh(project)

            conversation = Conversation(
                user_id=user.id,
                project_id=project.id if project else None,
                title="Candidate Chat",
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

            message = Message(
                conversation_id=conversation.id,
                role="user",
                content=user_content,
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            return user.id, project.id if project else None, conversation.id, message.id
        finally:
            db.close()

    def _candidate_count(self) -> int:
        db = self.SessionLocal()
        try:
            return db.query(MemoryCandidate).count()
        finally:
            db.close()

    def test_attachment_failure_does_not_create_explicit_memory(self) -> None:
        self._install_db_override()

        with TestClient(app) as client:
            headers = self._register(client, "orphan-memory@example.com")

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                response = client.post(
                    "/api/chat",
                    data={"message": "请记住我使用 PyCharm 开发 Python 项目"},
                    files={"files": ("empty.txt", b"", "text/plain")},
                    headers=headers,
                )

        self.assertEqual(response.status_code, 400)
        db = self.SessionLocal()
        try:
            self.assertEqual(db.query(Memory).count(), 0)
        finally:
            db.close()

    def test_new_chat_with_project_id_creates_project_conversation(self) -> None:
        self._install_db_override()

        async def fake_stream_chat_completion(messages, **kwargs):
            yield "ok"

        def fake_create_task(coroutine):
            coroutine.close()
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "new-project-chat@example.com")
            project_id = self._create_project(client, headers, "Chat Project")

            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "你好", "project_id": project_id},
                    headers=headers,
                )

        self.assertEqual(response.status_code, 200)
        db = self.SessionLocal()
        try:
            conversation = db.query(Conversation).one()
            self.assertEqual(conversation.project_id, project_id)
        finally:
            db.close()

    def test_existing_conversation_rejects_conflicting_project_id(self) -> None:
        self._install_db_override()

        with TestClient(app) as client:
            headers = self._register(client, "conflict-project-chat@example.com")
            first_project_id = self._create_project(client, headers, "First")
            second_project_id = self._create_project(client, headers, "Second")
            conversation = client.post(
                "/api/conversations",
                json={"title": "Project chat", "project_id": first_project_id},
                headers=headers,
            ).json()

            response = client.post(
                "/api/chat",
                json={
                    "conversation_id": conversation["id"],
                    "project_id": second_project_id,
                    "message": "继续",
                },
                headers=headers,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Conversation project mismatch")

    def test_existing_conversation_uses_persisted_project_for_context(self) -> None:
        self._install_db_override()
        captured_messages = []

        async def fake_stream_chat_completion(messages, **kwargs):
            captured_messages.extend(messages)
            yield "ok"

        def fake_create_task(coroutine):
            coroutine.close()
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "persisted-project-chat@example.com")
            project_id = self._create_project(client, headers, "Persisted")
            conversation = client.post(
                "/api/conversations",
                json={"title": "Project chat", "project_id": project_id},
                headers=headers,
            ).json()

            db = self.SessionLocal()
            try:
                user = db.query(User).filter_by(email="persisted-project-chat@example.com").one()
                db.add_all(
                    [
                        Memory(user_id=user.id, content="全局记忆：简洁回答", kind="preference"),
                        Memory(
                            user_id=user.id,
                            project_id=project_id,
                            scope="project",
                            content="项目记忆：使用 FastAPI",
                            kind="tool",
                        ),
                    ]
                )
                db.commit()
            finally:
                db.close()

            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"conversation_id": conversation["id"], "message": "继续"},
                    headers=headers,
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_messages[0]["role"], "system")
        self.assertIn("全局记忆：简洁回答", captured_messages[0]["content"])
        self.assertIn("项目记忆：使用 FastAPI", captured_messages[0]["content"])

    def test_multipart_chat_carries_project_id(self) -> None:
        self._install_db_override()

        async def fake_stream_chat_completion(messages, **kwargs):
            yield "ok"

        def fake_create_task(coroutine):
            coroutine.close()
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "multipart-project-chat@example.com")
            project_id = self._create_project(client, headers, "Multipart")

            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    data={"message": "带附件", "project_id": project_id},
                    files={"files": ("note.txt", b"hello", "text/plain")},
                    headers=headers,
                )

        self.assertEqual(response.status_code, 200)
        db = self.SessionLocal()
        try:
            conversation = db.query(Conversation).one()
            self.assertEqual(conversation.project_id, project_id)
        finally:
            db.close()

    def test_project_chat_creates_project_candidate(self) -> None:
        self._install_db_override()
        scheduled_coroutines = []

        async def fake_stream_chat_completion(messages, **kwargs):
            yield "助手回复"

        async def fake_extract_memory_candidate(*args, **kwargs):
            return ExtractedMemoryCandidate(
                content="项目后端使用 FastAPI",
                kind="project",
                scope="project",
                action="create",
                confidence=92,
                importance=75,
                reason="项目技术栈",
            )

        def fake_create_task(coroutine):
            scheduled_coroutines.append(coroutine)
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "project-candidate@example.com")
            project_id = self._create_project(client, headers, "Candidate Project")
            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch(
                    "app.routers.chat.memory_extraction_service.extract_memory_candidate",
                    fake_extract_memory_candidate,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "这个项目后端使用 FastAPI", "project_id": project_id},
                    headers=headers,
                )
                self.assertEqual(len(scheduled_coroutines), 1)
                asyncio.run(scheduled_coroutines[0])

        self.assertEqual(response.status_code, 200)

        db = self.SessionLocal()
        try:
            candidate = db.query(MemoryCandidate).one()
            source_message = db.get(Message, candidate.source_message_id)
            self.assertEqual(candidate.scope, "project")
            self.assertEqual(candidate.project_id, project_id)
            self.assertIsNone(candidate.conversation_id)
            self.assertIsNotNone(source_message)
            self.assertEqual(source_message.content, "这个项目后端使用 FastAPI")
            self.assertEqual(candidate.extraction_model, get_memory_model())
        finally:
            db.close()

    def test_chat_auto_accepts_conversation_candidate(self) -> None:
        self._install_db_override()
        user_id, project_id, conversation_id, message_id = self._create_chat_records(
            project_chat=False,
            user_content="我们决定这个会话先只讨论后端接口",
        )

        async def fake_extract_memory_candidate(*args, **kwargs):
            return ExtractedMemoryCandidate(
                content="本会话先只讨论后端接口",
                kind="decision",
                scope="conversation",
                action="create",
                confidence=88,
                importance=80,
                reason="会话决策",
            )

        with patch(
            "app.routers.chat.memory_extraction_service.extract_memory_candidate",
            fake_extract_memory_candidate,
        ), patch(
            "app.routers.chat.memory_document_service.rebuild_memory_document",
        ) as rebuild_document:
            asyncio.run(
                chat_router._extract_and_store_memory_candidate(
                    user_id=user_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    source_message_id=message_id,
                    user_content="我们决定这个会话先只讨论后端接口",
                    model="qwen3-coder-next",
                )
            )

        db = self.SessionLocal()
        try:
            candidate = db.query(MemoryCandidate).one()
            memory = db.query(Memory).one()
            self.assertEqual(candidate.scope, "conversation")
            self.assertIsNone(candidate.project_id)
            self.assertEqual(candidate.conversation_id, conversation_id)
            self.assertEqual(candidate.status, "accepted")
            self.assertEqual(candidate.accepted_memory_id, memory.id)
            self.assertEqual(memory.scope, "conversation")
            self.assertEqual(memory.conversation_id, conversation_id)
            self.assertEqual(memory.content, "本会话先只讨论后端接口")
        finally:
            db.close()
        rebuild_document.assert_awaited_once()

    def test_global_preference_candidate_can_be_created_inside_project_chat(self) -> None:
        self._install_db_override()
        user_id, project_id, conversation_id, message_id = self._create_chat_records(
            project_chat=True,
            user_content="我偏好你以后用中文简洁回答",
        )

        async def fake_extract_memory_candidate(*args, **kwargs):
            return ExtractedMemoryCandidate(
                content="用户偏好中文简洁回答",
                kind="preference",
                scope="global",
                action="create",
                confidence=91,
                importance=85,
                reason="用户偏好",
            )

        with patch(
            "app.routers.chat.memory_extraction_service.extract_memory_candidate",
            fake_extract_memory_candidate,
        ):
            asyncio.run(
                chat_router._extract_and_store_memory_candidate(
                    user_id=user_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    source_message_id=message_id,
                    user_content="我偏好你以后用中文简洁回答",
                    model="qwen3-coder-next",
                )
            )

        db = self.SessionLocal()
        try:
            candidate = db.query(MemoryCandidate).one()
            self.assertEqual(candidate.scope, "global")
            self.assertIsNone(candidate.project_id)
            self.assertIsNone(candidate.conversation_id)
        finally:
            db.close()

    def test_explicit_conversation_memory_request_is_saved_without_prompt(self) -> None:
        self._install_db_override()
        scheduled_coroutines = []
        captured_messages = []

        async def fake_stream_chat_completion(messages, **kwargs):
            captured_messages.extend(messages)
            yield "ok"

        def fake_create_task(coroutine):
            scheduled_coroutines.append(coroutine)
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "explicit-candidate@example.com")
            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch("app.routers.chat.memory_document_service.rebuild_memory_document"),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "请记住我使用 PyCharm 开发 Python 项目"},
                    headers=headers,
                )

        for coroutine in scheduled_coroutines:
            coroutine.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(scheduled_coroutines, [])
        db = self.SessionLocal()
        try:
            candidate = db.query(MemoryCandidate).one()
            memory = db.query(Memory).one()
            self.assertEqual(candidate.surface, "settings")
            self.assertEqual(candidate.status, "accepted")
            self.assertEqual(candidate.action, "create")
            self.assertEqual(candidate.scope, "conversation")
            self.assertEqual(candidate.accepted_memory_id, memory.id)
            self.assertEqual(memory.scope, "conversation")
            self.assertIn("PyCharm", candidate.content)
            self.assertFalse(candidate.content.startswith("请"))
        finally:
            db.close()
        notices = "\n".join(
            str(message["content"])
            for message in captured_messages
            if message.get("role") == "system"
        )
        self.assertIn("自动保存到当前会话记忆", notices)

    def test_explicit_memory_request_updates_existing_global_preference_candidate(self) -> None:
        self._install_db_override()
        captured_messages = []
        scheduled_coroutines = []

        async def fake_stream_chat_completion(messages, **kwargs):
            captured_messages.extend(messages)
            yield "ok"

        def fake_create_task(coroutine):
            scheduled_coroutines.append(coroutine)
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "explicit-update-candidate@example.com")
            db = self.SessionLocal()
            try:
                user = db.query(User).filter_by(email="explicit-update-candidate@example.com").one()
                existing = Memory(
                    user_id=user.id,
                    content="我喜欢喝可乐",
                    kind="preference",
                    scope="global",
                    status="active",
                    enabled=True,
                )
                db.add(existing)
                db.commit()
                db.refresh(existing)
                existing_id = existing.id
            finally:
                db.close()

            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "请记住我不喜欢喝可乐"},
                    headers=headers,
                )

        for coroutine in scheduled_coroutines:
            coroutine.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(scheduled_coroutines, [])
        db = self.SessionLocal()
        try:
            candidate = db.query(MemoryCandidate).one()
            self.assertEqual(candidate.surface, "inline")
            self.assertEqual(candidate.status, "pending")
            self.assertEqual(candidate.action, "update")
            self.assertEqual(candidate.scope, "global")
            self.assertEqual(candidate.target_memory_id, existing_id)
            self.assertIn("不喜欢喝可乐", candidate.content)
            self.assertEqual(db.query(Memory).count(), 1)
        finally:
            db.close()

        pending_notice = "\n".join(
            str(message["content"])
            for message in captured_messages
            if message.get("role") == "system"
        )
        self.assertIn("待确认", pending_notice)
        self.assertIn("尚未正式保存或覆盖", pending_notice)

    def test_candidate_extraction_failure_does_not_break_chat(self) -> None:
        self._install_db_override()
        scheduled_coroutines = []

        async def fake_stream_chat_completion(messages, **kwargs):
            yield "助手回复"

        async def failing_extract_memory_candidate(*args, **kwargs):
            raise RuntimeError("extract failed")

        def fake_create_task(coroutine):
            scheduled_coroutines.append(coroutine)
            return object()

        with TestClient(app) as client:
            headers = self._register(client, "candidate-failure@example.com")
            with (
                patch(
                    "app.routers.chat.llm_service.stream_chat_completion",
                    fake_stream_chat_completion,
                ),
                patch(
                    "app.routers.chat.memory_extraction_service.extract_memory_candidate",
                    failing_extract_memory_candidate,
                ),
                patch("app.routers.chat.asyncio.create_task", fake_create_task),
            ):
                response = client.post(
                    "/api/chat",
                    json={"message": "这个项目先使用 SQLite 验证"},
                    headers=headers,
                )
                self.assertEqual(len(scheduled_coroutines), 1)
                asyncio.run(scheduled_coroutines[0])

        self.assertEqual(response.status_code, 200)
        self.assertIn("data: [DONE]", response.text)

        db = self.SessionLocal()
        try:
            messages = db.query(Message).order_by(Message.created_at).all()
            self.assertEqual([message.role for message in messages], ["user", "assistant"])
            self.assertEqual(messages[1].content, "助手回复")
            self.assertEqual(db.query(MemoryCandidate).count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
