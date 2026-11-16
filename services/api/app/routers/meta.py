"""Static catalogs for the web app (avatars, characters, interest chips).

Open without a token: it is versioned content from the repository, the same for everyone,
and both the parent wizard and the child picture picker need it. It carries no voice or
model ids, which are admin-only (docs/CLAUDE.md §2).
"""

from __future__ import annotations

from fastapi import APIRouter

from app import content
from app.config import settings
from app.schemas.children import AvatarOut, CatalogLimits, CatalogOut

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/catalog", response_model=CatalogOut)
async def catalog() -> CatalogOut:
    return CatalogOut(
        avatars=[
            AvatarOut(
                id=str(item["id"]),
                asset=str(item.get("asset", "")),
                color=item.get("color"),
                label=dict(item.get("label", {})),
            )
            for item in content.avatars()
        ],
        characters=[CatalogOut.character_from_content(item) for item in content.characters()],
        interest_suggestions=list(content.INTEREST_SUGGESTIONS),
        languages=["sr", "en"],
        limits=CatalogLimits(),
        consent_version=settings.consent_version,
    )
