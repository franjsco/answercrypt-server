import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import app, get_db
from app.models import ApiKey, Audit


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AnswerCryptApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{database_path}", connect_args={"check_same_thread": False}
        )
        self.session_local = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=self.engine)

        with self.session_local() as session:
            session.add(ApiKey(key="valid-key"))
            session.commit()

        def override_get_db():
            db = self.session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_question_requires_existing_secret(self) -> None:
        response = self.client.get("/question")

        self.assertEqual(response.status_code, 404)

    def test_store_requires_valid_api_key(self) -> None:
        response = self.client.post(
            "/store",
            json={"question": "Q?", "answer": "A", "payload": "secret"},
        )

        self.assertEqual(response.status_code, 401)

        with self.session_local() as session:
            audit_count = session.scalar(select(func.count(Audit.id)).where(Audit.event == "store_failed"))

        self.assertEqual(audit_count, 1)

    def test_store_question_and_retrieve_secret(self) -> None:
        store_response = self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={
                "question": "What is the code?",
                "answer": "1234",
                "payload": "very-secret-value",
            },
        )
        question_response = self.client.get("/question")
        retrieve_response = self.client.post("/retrieve", json={"answer": "1234"})

        self.assertEqual(store_response.status_code, 200)
        self.assertEqual(question_response.status_code, 200)
        self.assertEqual(question_response.json(), {"question": "What is the code?"})
        self.assertEqual(retrieve_response.status_code, 200)
        self.assertEqual(retrieve_response.json(), {"payload": "very-secret-value"})

    def test_retrieve_wrong_answer_is_audited(self) -> None:
        self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={"question": "Q?", "answer": "A", "payload": "secret"},
        )

        response = self.client.post("/retrieve", json={"answer": "wrong"})

        self.assertEqual(response.status_code, 401)

        with self.session_local() as session:
            audit_count = session.scalar(
                select(func.count(Audit.id)).where(Audit.event == "retrieval_failed")
            )

        self.assertEqual(audit_count, 1)

    def test_retrieve_is_rate_limited_after_ten_failures(self) -> None:
        self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={"question": "Q?", "answer": "A", "payload": "secret"},
        )

        for _ in range(10):
            response = self.client.post("/retrieve", json={"answer": "wrong"})
            self.assertEqual(response.status_code, 401)

        blocked_response = self.client.post("/retrieve", json={"answer": "A"})

        self.assertEqual(blocked_response.status_code, 429)

    def test_rate_limit_expires_after_six_hours(self) -> None:
        self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={"question": "Q?", "answer": "A", "payload": "secret"},
        )

        with self.session_local() as session:
            failure_time = utc_now() - timedelta(hours=5, minutes=59)
            store_time = utc_now() - timedelta(hours=6, minutes=2)
            session.query(Audit).filter(Audit.event == "store_succeeded").update({Audit.date: store_time})
            session.add_all(
                [Audit(ip_address="127.0.0.1", event="retrieval_failed", date=failure_time) for _ in range(10)]
            )
            session.commit()

        blocked_response = self.client.post("/retrieve", json={"answer": "A"})
        self.assertEqual(blocked_response.status_code, 429)

        with self.session_local() as session:
            session.query(Audit).filter(Audit.event == "retrieval_failed").update(
                {Audit.date: utc_now() - timedelta(hours=6, minutes=1)}
            )
            session.commit()

        success_response = self.client.post("/retrieve", json={"answer": "A"})
        self.assertEqual(success_response.status_code, 200)

    def test_new_store_resets_current_secret_rate_limit(self) -> None:
        self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={"question": "Q1?", "answer": "A1", "payload": "secret-1"},
        )

        for _ in range(10):
            self.client.post("/retrieve", json={"answer": "wrong"})

        blocked_response = self.client.post("/retrieve", json={"answer": "A1"})
        self.assertEqual(blocked_response.status_code, 429)

        self.client.post(
            "/store",
            headers={"X-API-Key": "valid-key"},
            json={"question": "Q2?", "answer": "A2", "payload": "secret-2"},
        )

        success_response = self.client.post("/retrieve", json={"answer": "A2"})
        self.assertEqual(success_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
