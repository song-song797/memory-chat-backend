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

    def _create_project(self, headers: dict[str, str], name: str = "Memory Project") -> str:
        response = self.client.post("/api/projects", json={"name": name}, headers=headers)
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

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

    def test_list_memories_requires_authentication(self) -> None:
        response = self.client.get("/api/memories")
        self.assertEqual(response.status_code, 401)

    def test_memory_update_requires_changes(self) -> None:
        headers = self._register("empty-update@example.com")
        create_response = self.client.post(
            "/api/memories",
            json={"content": "Memory to update", "kind": "fact"},
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)

        update_response = self.client.put(
            f"/api/memories/{create_response.json()['id']}",
            json={},
            headers=headers,
        )
        self.assertEqual(update_response.status_code, 400)
        self.assertEqual(update_response.json()["detail"], "No memory changes provided")

    def test_memory_content_and_kind_cannot_be_blank_after_trimming(self) -> None:
        headers = self._register("blank-memory@example.com")

        blank_content = self.client.post(
            "/api/memories",
            json={"content": "   ", "kind": "fact"},
            headers=headers,
        )
        self.assertEqual(blank_content.status_code, 400)
        self.assertEqual(blank_content.json()["detail"], "Memory content cannot be empty")

        empty_content = self.client.post(
            "/api/memories",
            json={"content": "", "kind": "fact"},
            headers=headers,
        )
        self.assertEqual(empty_content.status_code, 400)
        self.assertEqual(empty_content.json()["detail"], "Memory content cannot be empty")

        blank_kind = self.client.post(
            "/api/memories",
            json={"content": "Valid content", "kind": "   "},
            headers=headers,
        )
        self.assertEqual(blank_kind.status_code, 400)
        self.assertEqual(blank_kind.json()["detail"], "Memory kind cannot be empty")

        empty_kind = self.client.post(
            "/api/memories",
            json={"content": "Valid content", "kind": ""},
            headers=headers,
        )
        self.assertEqual(empty_kind.status_code, 400)
        self.assertEqual(empty_kind.json()["detail"], "Memory kind cannot be empty")

        create_response = self.client.post(
            "/api/memories",
            json={"content": "Valid content", "kind": "fact"},
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        memory_id = create_response.json()["id"]

        blank_content_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"content": "   "},
            headers=headers,
        )
        self.assertEqual(blank_content_update.status_code, 400)
        self.assertEqual(blank_content_update.json()["detail"], "Memory content cannot be empty")

        empty_content_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"content": ""},
            headers=headers,
        )
        self.assertEqual(empty_content_update.status_code, 400)
        self.assertEqual(empty_content_update.json()["detail"], "Memory content cannot be empty")

        blank_kind_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"kind": "   "},
            headers=headers,
        )
        self.assertEqual(blank_kind_update.status_code, 400)
        self.assertEqual(blank_kind_update.json()["detail"], "Memory kind cannot be empty")

    def test_missing_memory_update_and_delete_return_404(self) -> None:
        headers = self._register("missing-memory@example.com")

        update_response = self.client.put(
            "/api/memories/missing-memory-id",
            json={"enabled": False},
            headers=headers,
        )
        self.assertEqual(update_response.status_code, 404)

        delete_response = self.client.delete("/api/memories/missing-memory-id", headers=headers)
        self.assertEqual(delete_response.status_code, 404)

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

        bob_list_response = self.client.get("/api/memories", headers=bob_headers)
        self.assertEqual(bob_list_response.status_code, 200)
        self.assertEqual(bob_list_response.json(), [])

        bob_update = self.client.put(
            f"/api/memories/{memory_id}",
            json={"enabled": False},
            headers=bob_headers,
        )
        self.assertEqual(bob_update.status_code, 404)

        bob_delete = self.client.delete(f"/api/memories/{memory_id}", headers=bob_headers)
        self.assertEqual(bob_delete.status_code, 404)

    def test_memory_scope_fields_and_project_filtering(self) -> None:
        headers = self._register("scoped-memory@example.com")
        project_id = self._create_project(headers)

        global_response = self.client.post(
            "/api/memories",
            json={"content": "Global preference", "kind": "fact", "scope": "global"},
            headers=headers,
        )
        self.assertEqual(global_response.status_code, 201)
        global_memory = global_response.json()
        self.assertEqual(global_memory["scope"], "global")
        self.assertIsNone(global_memory["project_id"])
        self.assertEqual(global_memory["status"], "active")
        self.assertEqual(global_memory["importance"], 0)
        self.assertIsNone(global_memory["superseded_by_id"])
        self.assertIsNone(global_memory["archived_at"])
        self.assertTrue(global_memory["enabled"])

        project_response = self.client.post(
            "/api/memories",
            json={
                "content": "Project fact",
                "kind": "fact",
                "scope": "project",
                "project_id": project_id,
                "importance": 4,
            },
            headers=headers,
        )
        self.assertEqual(project_response.status_code, 201)
        project_memory = project_response.json()
        self.assertEqual(project_memory["scope"], "project")
        self.assertEqual(project_memory["project_id"], project_id)
        self.assertEqual(project_memory["importance"], 4)

        project_list = self.client.get(
            f"/api/memories?scope=project&project_id={project_id}",
            headers=headers,
        )
        self.assertEqual(project_list.status_code, 200)
        self.assertEqual([item["id"] for item in project_list.json()], [project_memory["id"]])

        global_list = self.client.get("/api/memories?scope=global", headers=headers)
        self.assertEqual(global_list.status_code, 200)
        self.assertEqual([item["id"] for item in global_list.json()], [global_memory["id"]])

    def test_memory_scope_validation_and_project_ownership(self) -> None:
        alice_headers = self._register("alice-scoped-memory@example.com")
        bob_headers = self._register("bob-scoped-memory@example.com")
        alice_project_id = self._create_project(alice_headers, "Alice Project")

        invalid_scope = self.client.get("/api/memories?scope=workspace", headers=alice_headers)
        self.assertEqual(invalid_scope.status_code, 400)
        self.assertEqual(invalid_scope.json()["detail"], "Invalid memory scope")

        global_with_project = self.client.post(
            "/api/memories",
            json={
                "content": "Bad global memory",
                "kind": "fact",
                "scope": "global",
                "project_id": alice_project_id,
            },
            headers=alice_headers,
        )
        self.assertEqual(global_with_project.status_code, 400)
        self.assertEqual(global_with_project.json()["detail"], "Global memories cannot set project_id")

        project_without_project_id = self.client.post(
            "/api/memories",
            json={"content": "Bad project memory", "kind": "fact", "scope": "project"},
            headers=alice_headers,
        )
        self.assertEqual(project_without_project_id.status_code, 400)
        self.assertEqual(
            project_without_project_id.json()["detail"],
            "Project memories require project_id",
        )

        bob_project_memory = self.client.post(
            "/api/memories",
            json={
                "content": "Wrong owner project memory",
                "kind": "fact",
                "scope": "project",
                "project_id": alice_project_id,
            },
            headers=bob_headers,
        )
        self.assertEqual(bob_project_memory.status_code, 404)

        bob_project_filter = self.client.get(
            f"/api/memories?project_id={alice_project_id}",
            headers=bob_headers,
        )
        self.assertEqual(bob_project_filter.status_code, 404)

    def test_memory_status_archiving_filter_and_enabled_toggle(self) -> None:
        headers = self._register("archive-memory@example.com")
        create_response = self.client.post(
            "/api/memories",
            json={"content": "Memory to archive", "kind": "fact"},
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        memory_id = create_response.json()["id"]

        archive_response = self.client.put(
            f"/api/memories/{memory_id}",
            json={"status": "archived", "enabled": False},
            headers=headers,
        )
        self.assertEqual(archive_response.status_code, 200)
        archived = archive_response.json()
        self.assertEqual(archived["status"], "archived")
        self.assertIsNotNone(archived["archived_at"])
        self.assertFalse(archived["enabled"])

        active_list = self.client.get("/api/memories", headers=headers)
        self.assertEqual(active_list.status_code, 200)
        self.assertEqual(active_list.json(), [])

        archived_list = self.client.get("/api/memories?include_archived=true", headers=headers)
        self.assertEqual(archived_list.status_code, 200)
        self.assertEqual([item["id"] for item in archived_list.json()], [memory_id])

        reactivate_response = self.client.put(
            f"/api/memories/{memory_id}",
            json={"status": "active"},
            headers=headers,
        )
        self.assertEqual(reactivate_response.status_code, 200)
        reactivated = reactivate_response.json()
        self.assertEqual(reactivated["status"], "active")
        self.assertIsNone(reactivated["archived_at"])
        self.assertFalse(reactivated["enabled"])

        invalid_status = self.client.put(
            f"/api/memories/{memory_id}",
            json={"status": "deleted"},
            headers=headers,
        )
        self.assertEqual(invalid_status.status_code, 400)
        self.assertEqual(invalid_status.json()["detail"], "Invalid memory status")


if __name__ == "__main__":
    unittest.main()
