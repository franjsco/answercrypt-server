from datetime import UTC, datetime, timedelta
from typing import Generator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import ApiKey, Audit, Secret
from app.schemas import (
    QuestionResponse,
    RetrieveSecretRequest,
    RetrieveSecretResponse,
    StoreSecretRequest,
)



MAX_FAILED_ATTEMPTS = 10
RATE_LIMIT_WINDOW = timedelta(hours=6)

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins="*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_audit(db: Session, ip_address: str, event: str) -> None:
    db.add(Audit(ip_address=ip_address, event=event, date=utc_now()))
    db.commit()


def get_active_secret(db: Session) -> Secret | None:
    return db.scalar(select(Secret).order_by(desc(Secret.id)).limit(1))


def is_rate_limited(db: Session) -> bool:
    threshold = utc_now() - RATE_LIMIT_WINDOW
    last_store_at = db.scalar(
        select(Audit.date).where(Audit.event == "store_succeeded").order_by(desc(Audit.date)).limit(1)
    )

    filters = [
        Audit.event == "retrieval_failed",
        Audit.date >= threshold,
    ]
    if last_store_at is not None:
        filters.append(Audit.date >= last_store_at)

    failed_attempts = db.scalar(
        select(func.count(Audit.id)).where(*filters)
    )
    return bool(failed_attempts and failed_attempts >= MAX_FAILED_ATTEMPTS)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "answercrypt server"}


@app.get("/question", response_model=QuestionResponse)
def read_question(db: Session = Depends(get_db)) -> QuestionResponse:
    secret = get_active_secret(db)
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")

    return QuestionResponse(question=secret.question)


@app.post("/retrieve", response_model=RetrieveSecretResponse)
def retrieve_secret(
    payload: RetrieveSecretRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RetrieveSecretResponse:
    secret = get_active_secret(db)
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")

    if is_rate_limited(db):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Retry later.",
        )

    if payload.answer != secret.answer:
        create_audit(db, get_client_ip(request), "retrieval_failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid answer")

    create_audit(db, get_client_ip(request), "retrieval_succeeded")
    return RetrieveSecretResponse(payload=secret.payload)


@app.post("/store")
def store_secret(
    payload: StoreSecretRequest,
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    ip_address = get_client_ip(request)

    if x_api_key is None or db.scalar(select(ApiKey).where(ApiKey.key == x_api_key)) is None:
        create_audit(db, ip_address, "store_failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    secret = get_active_secret(db)
    if secret is None:
        db.add(Secret(question=payload.question, answer=payload.answer, payload=payload.payload))
    else:
        secret.question = payload.question
        secret.answer = payload.answer
        secret.payload = payload.payload

    db.commit()
    create_audit(db, ip_address, "store_succeeded")
    return {"status": "stored"}
