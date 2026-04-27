import unittest

from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401
from app.database import Base


class ProjectWorkspaceModelTests(unittest.TestCase):
    def test_workspace_columns_exist_in_metadata(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        self.assertIn("projects", inspector.get_table_names())
        conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
        memory_columns = {column["name"] for column in inspector.get_columns("memories")}

        self.assertIn("project_id", conversation_columns)
        self.assertIn("project_id", memory_columns)
        self.assertIn("scope", memory_columns)
        self.assertIn("status", memory_columns)
        self.assertIn("importance", memory_columns)
        self.assertIn("superseded_by_id", memory_columns)
        self.assertIn("archived_at", memory_columns)


if __name__ == "__main__":
    unittest.main()
