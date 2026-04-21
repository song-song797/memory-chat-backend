import unittest

from app.services.llm_service import _build_system_prompt


class SystemPromptTests(unittest.TestCase):
    def test_system_prompt_expands_complex_technical_topics(self) -> None:
        prompt = _build_system_prompt("MiniMax-M2.5")

        self.assertIn("概念简单时请保持简洁", prompt)
        self.assertIn("涉及框架、架构或复杂技术主题时", prompt)
        self.assertIn("主动分层展开", prompt)


if __name__ == "__main__":
    unittest.main()
