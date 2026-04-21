import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


async def _fake_stream_chat_completion(
    messages,
    model=None,
    reasoning_level=None,
    legacy_mode=None,
    system_prompt=None,
):
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "这个网站能做什么？"
    assert reasoning_level == "off"
    assert system_prompt is not None

    yield "你可以在这个网站里注册登录，"
    yield "上传附件并保存对话。"


class LandingChatRouteTests(unittest.TestCase):
    def test_landing_chat_streams_reply(self) -> None:
        with TestClient(app) as client:
            with patch(
                "app.routers.chat.llm_service.stream_chat_completion",
                _fake_stream_chat_completion,
            ):
                response = client.post(
                    "/api/landing-chat",
                    json={
                        "message": "这个网站能做什么？",
                        "history": [
                            {
                                "role": "assistant",
                                "content": "你好，我是导览助手。",
                            }
                        ],
                    },
                )

        self.assertEqual(response.status_code, 200)
        payloads = []
        for line in response.text.splitlines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            payloads.append(json.loads(line[6:]))

        joined_content = "".join(item.get("content", "") for item in payloads)
        self.assertIn("你可以在这个网站里注册登录", joined_content)
        self.assertIn("上传附件并保存对话", joined_content)
        self.assertIn("[DONE]", response.text)


if __name__ == "__main__":
    unittest.main()
