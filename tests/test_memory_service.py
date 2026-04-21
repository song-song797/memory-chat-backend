import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Conversation, Message
from app.services import memory_service


class MemoryContextModelIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def test_cross_model_assistant_messages_are_demoted_to_reference_context(self) -> None:
        db = self.SessionLocal()
        try:
            conversation = Conversation(title="model identity isolation")
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

            db.add_all(
                [
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="你是什么模型",
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="我是通义千问（Qwen）。",
                        model="qwen3.5-plus",
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="那你记住我的偏好",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_context_messages(db, conversation.id, current_model="MiniMax-M2.5")

            self.assertEqual(
                context,
                [
                    {"role": "user", "content": "你是什么模型"},
                    {
                        "role": "system",
                        "content": (
                            "以下是历史对话中另一模型的回答记录（模型：Qwen 3.5 Plus）。"
                            "这些内容仅供上下文参考，不代表你自己的身份、经历或上一轮回答：\n"
                            "我是通义千问（Qwen）。"
                        ),
                    },
                    {"role": "user", "content": "那你记住我的偏好"},
                ],
            )
        finally:
            db.close()

    def test_same_model_assistant_messages_remain_assistant_history(self) -> None:
        db = self.SessionLocal()
        try:
            conversation = Conversation(title="same model continuity")
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

            db.add_all(
                [
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="记住我喜欢简洁回答",
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="记住了，我会尽量简洁回答。",
                        model="MiniMax-M2.5",
                    ),
                ]
            )
            db.commit()

            context = memory_service.get_context_messages(db, conversation.id, current_model="MiniMax-M2.5")

            self.assertEqual(
                context,
                [
                    {"role": "user", "content": "记住我喜欢简洁回答"},
                    {"role": "assistant", "content": "记住了，我会尽量简洁回答。"},
                ],
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
