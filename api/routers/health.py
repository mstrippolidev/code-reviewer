"""
    Route for health check of the API.
"""

from fastapi import APIRouter
router = APIRouter(prefix="/health", tags=["Health Check"])

@router.get("/")
async def health_check():
    """
    Health check endpoint to verify if the API is running.
    Returns a JSON response indicating the status of the API.
    """
    return {"status": "API is running"}