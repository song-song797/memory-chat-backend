import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


class ProjectRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "project-routes.db"
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

    def test_project_crud_and_archive_filtering(self) -> None:
        headers = self._register("projects@example.com")

        create_response = self.client.post(
            "/api/projects",
            json={
                "name": "Memory App",
                "description": "Project workspace test",
                "default_model": "MiniMax-M2.5",
                "default_reasoning_level": "standard",
            },
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["name"], "Memory App")
        self.assertFalse(created["is_default"])
        self.assertIsNone(created["archived_at"])

        list_response = self.client.get("/api/projects", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["id"] for item in list_response.json()], [created["id"]])

        archive_response = self.client.put(
            f"/api/projects/{created['id']}",
            json={"archived": True},
            headers=headers,
        )
        self.assertEqual(archive_response.status_code, 200)
        self.assertIsNotNone(archive_response.json()["archived_at"])

        active_list = self.client.get("/api/projects", headers=headers)
        self.assertEqual(active_list.json(), [])

        all_list = self.client.get("/api/projects?include_archived=true", headers=headers)
        self.assertEqual(len(all_list.json()), 1)

    def test_projects_are_isolated_by_user(self) -> None:
        alice_headers = self._register("alice-project@example.com")
        bob_headers = self._register("bob-project@example.com")

        create_response = self.client.post(
            "/api/projects",
            json={"name": "Alice Project"},
            headers=alice_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        project_id = create_response.json()["id"]

        bob_list = self.client.get("/api/projects", headers=bob_headers)
        self.assertEqual(bob_list.status_code, 200)
        self.assertEqual(bob_list.json(), [])

        bob_update = self.client.put(
            f"/api/projects/{project_id}",
            json={"name": "Stolen"},
            headers=bob_headers,
        )
        self.assertEqual(bob_update.status_code, 404)

    def test_project_name_cannot_be_blank(self) -> None:
        headers = self._register("blank-project@example.com")
        response = self.client.post("/api/projects", json={"name": "   "}, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Project name cannot be empty")

    def test_default_reasoning_level_must_be_supported(self) -> None:
        headers = self._register("bad-reasoning-project@example.com")
        response = self.client.post(
            "/api/projects",
            json={"name": "Reasoning", "default_reasoning_level": "extra"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
