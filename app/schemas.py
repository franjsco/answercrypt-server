from pydantic import BaseModel


class QuestionResponse(BaseModel):
    question: str


class RetrieveSecretRequest(BaseModel):
    answer: str


class RetrieveSecretResponse(BaseModel):
    payload: str


class StoreSecretRequest(BaseModel):
    question: str
    answer: str
    payload: str
