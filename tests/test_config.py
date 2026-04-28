import unittest

from app.config import Settings, get_database_url, get_memory_model


class ConfigTests(unittest.TestCase):
    def test_database_url_is_built_from_structured_postgres_settings(self) -> None:
        config = Settings(
            _env_file=None,
            DATABASE_URL="",
            DB_DRIVER="postgresql+psycopg",
            DB_HOST="127.0.0.1",
            DB_PORT="5432",
            DB_NAME="llm_memory_chat",
            DB_USER="root",
            DB_PASSWORD="",
        )

        self.assertEqual(
            get_database_url(config),
            "postgresql+psycopg://root@127.0.0.1:5432/llm_memory_chat",
        )

    def test_database_url_override_takes_precedence(self) -> None:
        config = Settings(
            _env_file=None,
            DATABASE_URL="sqlite:///:memory:",
            DB_DRIVER="postgresql+psycopg",
            DB_HOST="127.0.0.1",
            DB_PORT="5432",
            DB_NAME="llm_memory_chat",
            DB_USER="root",
            DB_PASSWORD="",
        )

        self.assertEqual(get_database_url(config), "sqlite:///:memory:")

    def test_memory_model_uses_dedicated_memory_setting(self) -> None:
        config = Settings(
            _env_file=None,
            OPENAI_MODEL="qwen3-coder-next",
            MEMORY_MODEL="qwen3.5-plus",
        )

        self.assertEqual(get_memory_model(config), "qwen3.5-plus")

    def test_memory_model_falls_back_to_default_chat_model_when_unset(self) -> None:
        config = Settings(
            _env_file=None,
            OPENAI_MODEL="qwen3-coder-next",
            MEMORY_MODEL="",
        )

        self.assertEqual(get_memory_model(config), "qwen3-coder-next")


if __name__ == "__main__":
    unittest.main()
