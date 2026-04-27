import tempfile
import unittest
import warnings
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Conversation, Memory, Message, User
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

    def test_attachment_failure_does_not_create_explicit_memory(self) -> None:
        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        chat_router.SessionLocal = self.SessionLocal

        with TestClient(app) as client:
            register_response = client.post(
                "/api/auth/register",
                json={"email": "orphan-memory@example.com", "password": "password123"},
            )
            self.assertEqual(register_response.status_code, 201)
            headers = {"Authorization": f"Bearer {register_response.json()['token']}"}

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


if __name__ == "__main__":
    unittest.main()
