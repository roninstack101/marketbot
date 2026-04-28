"""
REST API for browsing and managing brand voice profiles.
Brand voices are created/updated via the agent (save_brand_voice tool).
These endpoints are read-only plus a direct-delete for admin use.
"""
from fastapi import APIRouter, HTTPException

from app.brand.store import get_brand_voice_data, list_all_brands, remove_brand_voice

router = APIRouter(prefix="/brands", tags=["Brand Voices"])


@router.get("", summary="List all brand voice profiles")
async def list_brands():
    brands = await list_all_brands()
    return {"count": len(brands), "brands": brands}


@router.get("/{brand_name}", summary="Get a single brand voice profile")
async def get_brand(brand_name: str):
    data = await get_brand_voice_data(brand_name)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Brand '{brand_name}' not found. Create it by submitting a task with save_brand_voice.",
        )
    return data


@router.delete("/{brand_name}", summary="Delete a brand voice profile")
async def delete_brand(brand_name: str):
    deleted = await remove_brand_voice(brand_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Brand '{brand_name}' not found.")
    return {"status": "deleted", "brand_name": brand_name}
