from fastapi import APIRouter
from app.api.v1.endpoints import auth, health, artworks, sessions, generation, gallery

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(artworks.router, prefix="/artworks", tags=["Artworks"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["Sessions"])
api_router.include_router(generation.router, prefix="/sessions", tags=["Generation"])
api_router.include_router(gallery.router, prefix="/gallery", tags=["Gallery"])
