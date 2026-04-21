import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


class AuthRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "auth-test.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
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

    def test_register_login_logout_and_protected_conversations(self) -> None:
        unauthorized = self.client.get("/api/conversations")
        self.assertEqual(unauthorized.status_code, 401)

        register_response = self.client.post(
            "/api/auth/register",
            json={"email": "  Test.User@example.com ", "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 201)
        register_body = register_response.json()
        self.assertEqual(register_body["user"]["email"], "test.user@example.com")

        token = register_body["token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_response = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], "test.user@example.com")

        create_conversation = self.client.post(
            "/api/conversations",
            json={"title": "Private chat"},
            headers=headers,
        )
        self.assertEqual(create_conversation.status_code, 201)

        list_response = self.client.get("/api/conversations", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        logout_response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(logout_response.status_code, 204)

        expired_session = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(expired_session.status_code, 401)

        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "test.user@example.com", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.json()["token"])

    def test_conversations_are_isolated_by_user(self) -> None:
        first_user = self.client.post(
            "/api/auth/register",
            json={"email": "alice@example.com", "password": "password123"},
        ).json()
        second_user = self.client.post(
            "/api/auth/register",
            json={"email": "bob@example.com", "password": "password123"},
        ).json()

        alice_headers = {"Authorization": f"Bearer {first_user['token']}"}
        bob_headers = {"Authorization": f"Bearer {second_user['token']}"}

        create_response = self.client.post(
            "/api/conversations",
            json={"title": "Alice secret"},
            headers=alice_headers,
        )
        self.assertEqual(create_response.status_code, 201)
        conversation_id = create_response.json()["id"]

        bob_list_response = self.client.get("/api/conversations", headers=bob_headers)
        self.assertEqual(bob_list_response.status_code, 200)
        self.assertEqual(bob_list_response.json(), [])

        bob_get_response = self.client.get(
            f"/api/conversations/{conversation_id}",
            headers=bob_headers,
        )
        self.assertEqual(bob_get_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
