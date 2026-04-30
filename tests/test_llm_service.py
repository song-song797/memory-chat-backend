import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.llm_service import _build_system_prompt, create_chat_completion, stream_chat_completion


class SystemPromptTests(unittest.TestCase):
    def test_system_prompt_expands_complex_technical_topics(self) -> None:
        prompt = _build_system_prompt("MiniMax-M2.5")

        self.assertIn("请保持简洁", prompt)
        self.assertIn("涉及框架、架构或复杂技术主题时", prompt)
        self.assertIn("主动分层展开", prompt)


class ChatCompletionParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chat_completion_skips_chunks_without_choices(self) -> None:
        class FakeStream:
            def __aiter__(self):
                async def iterator():
                    yield SimpleNamespace(choices=[])
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))]
                    )
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]
                    )

                return iterator()

        with patch(
            "app.services.llm_service._client.chat.completions.create",
            AsyncMock(return_value=FakeStream()),
        ):
            chunks = [
                chunk
                async for chunk in stream_chat_completion([{"role": "user", "content": "hi"}])
            ]

        self.assertEqual(chunks, ["hello"])

    async def test_create_chat_completion_returns_empty_string_when_choices_are_missing(self) -> None:
        with patch(
            "app.services.llm_service._client.chat.completions.create",
            AsyncMock(return_value=SimpleNamespace(choices=[])),
        ):
            content = await create_chat_completion([{"role": "user", "content": "hi"}])

        self.assertEqual(content, "")


if __name__ == "__main__":
    unittest.main()
