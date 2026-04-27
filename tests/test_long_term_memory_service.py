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
from app.models import Conversation, Memory, Message, Project, User
from app.routers import chat as chat_router
from app.services import memory_service


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

    def test_ordinary_explicit_memory_remains_global(self) -> None:
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
            self.assertEqual(memory.scope, "global")
            self.assertIsNone(memory.project_id)
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
            self.assertIn("项目记忆与全局记忆冲突时，优先遵循当前项目长期记忆", project_context["content"])
            self.assertIn("全局偏好：中文简洁回答", project_context["content"])
            self.assertIn("当前项目：API 使用 FastAPI", project_context["content"])
            self.assertNotIn("其他项目：API 使用 Flask", project_context["content"])
            self.assertNotIn("已归档：不要注入", project_context["content"])
            self.assertNotIn("已禁用：不要注入", project_context["content"])
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

        with TestClient(app) as client:
            headers = self._register(client, "new-project-chat@example.com")
            project_id = self._create_project(client, headers, "Chat Project")

            with patch(
                "app.routers.chat.llm_service.stream_chat_completion",
                fake_stream_chat_completion,
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

            with patch(
                "app.routers.chat.llm_service.stream_chat_completion",
                fake_stream_chat_completion,
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

        with TestClient(app) as client:
            headers = self._register(client, "multipart-project-chat@example.com")
            project_id = self._create_project(client, headers, "Multipart")

            with patch(
                "app.routers.chat.llm_service.stream_chat_completion",
                fake_stream_chat_completion,
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


if __name__ == "__main__":
    unittest.main()
