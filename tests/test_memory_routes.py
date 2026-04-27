import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


class MemoryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "memory-routes.db"
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

    def test_memory_crud(self) -> None:
        headers = self._register("owner@example.com")

        create_response = self.client.post(
            "/api/memories",
            json={"content": "用户使用 PyCharm 开发 Python 项目", "kind": "tool"},
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["content"], "用户使用 PyCharm 开发 Python 项目")
        self.assertTrue(created["enabled"])

        list_response = self.client.get("/api/memories", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        update_response = self.client.put(
            f"/api/memories/{created['id']}",
            json={"enabled": False},
            headers=headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertFalse(update_response.json()["enabled"])

        delete_response = self.client.delete(f"/api/memories/{created['id']}", headers=headers)
        self.assertEqual(delete_response.status_code, 204)

        final_list = self.client.get("/api/memories", headers=headers)
        self.assertEqual(final_list.json(), [])

    def test_memories_are_isolated_by_user(self) -> None:
        alice_headers = self._register("alice-memory@example.com")
        bob_headers = self._register("bob-memory@example.com")

        create_response = self.client.post(
            "/api/memories",
            json={"content": "Alice memory", "kind": "fact"},
            headers=alice_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        memory_id = create_response.json()["id"]

        bob_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"enabled": False},
            headers=bob_headers,
        )
        self.assertEqual(bob_update.status_code, 404)

        bob_delete = self.client.delete(f"/api/memories/{memory_id}", headers=bob_headers)
        self.assertEqual(bob_delete.status_code, 404)


if __name__ == "__main__":
    unittest.main()
