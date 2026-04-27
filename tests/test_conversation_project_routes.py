import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


class ConversationProjectRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "conversation-project-routes.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _register(self, email: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        self.assertEqual(response.status_code, 201)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_create_ordinary_and_project_conversations(self) -> None:
        headers = self._register("conversation-project@example.com")
        project = self.client.post("/api/projects", json={"name": "App"}, headers=headers).json()

        ordinary = self.client.post(
            "/api/conversations",
            json={"title": "Ordinary"},
            headers=headers,
        )
        self.assertEqual(ordinary.status_code, 201)
        self.assertIsNone(ordinary.json()["project_id"])

        project_chat = self.client.post(
            "/api/conversations",
            json={"title": "Project chat", "project_id": project["id"]},
            headers=headers,
        )
        self.assertEqual(project_chat.status_code, 201)
        self.assertEqual(project_chat.json()["project_id"], project["id"])

    def test_list_all_and_filter_by_project(self) -> None:
        headers = self._register("list-project-conversations@example.com")
        project = self.client.post("/api/projects", json={"name": "Scoped"}, headers=headers).json()

        self.client.post("/api/conversations", json={"title": "Ordinary"}, headers=headers)
        self.client.post(
            "/api/conversations",
            json={"title": "Scoped", "project_id": project["id"]},
            headers=headers,
        )

        all_response = self.client.get("/api/conversations", headers=headers)
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(len(all_response.json()), 2)

        filtered = self.client.get(
            f"/api/conversations?project_id={project['id']}",
            headers=headers,
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered.json()), 1)
        self.assertEqual(filtered.json()[0]["project_id"], project["id"])

    def test_cross_user_project_cannot_be_used_for_conversation(self) -> None:
        alice_headers = self._register("alice-conv-project@example.com")
        bob_headers = self._register("bob-conv-project@example.com")
        project = self.client.post(
            "/api/projects",
            json={"name": "Alice"},
            headers=alice_headers,
        ).json()

        response = self.client.post(
            "/api/conversations",
            json={"title": "Wrong", "project_id": project["id"]},
            headers=bob_headers,
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
