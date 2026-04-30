from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import SkillItemResponse, SkillListResponse
from ainrf.skills import SkillsDiscoveryService

router = APIRouter(prefix="/skills", tags=["skills"])


def _get_skills_discovery_service(request: Request) -> SkillsDiscoveryService:
    service = getattr(request.app.state, "skills_discovery_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="skills discovery service not initialized")
    return service


@router.get("", response_model=SkillListResponse)
async def list_skills(request: Request) -> SkillListResponse:
    service = _get_skills_discovery_service(request)
    skills = service.discover()
    return SkillListResponse(
        items=[
            SkillItemResponse(
                skill_id=s.skill_id,
                label=s.label,
                description=s.description,
            )
            for s in skills
        ]
    )
