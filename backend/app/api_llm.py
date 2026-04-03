from fastapi import APIRouter

from app.services.llm_provider import get_available_providers

router = APIRouter(prefix="/api", tags=["llm"])


@router.get("/llm-providers")
def list_llm_providers():
    return {"providers": get_available_providers()}
