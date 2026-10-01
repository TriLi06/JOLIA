from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import rag_service

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    n_context: int = 6


class ChatSource(BaseModel):
    file_id: str
    file_name: str
    source_path: str
    content_type: str
    score: float


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: list[ChatSource]


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.question.strip():
        return ChatResponse(question=request.question, answer="Bitte eine Frage eingeben.", sources=[])

    result = rag_service.chat(request.question, n_context=request.n_context)
    sources = [ChatSource(**s) for s in result.get("sources", [])]
    return ChatResponse(
        question=request.question,
        answer=result.get("answer", ""),
        sources=sources,
    )
