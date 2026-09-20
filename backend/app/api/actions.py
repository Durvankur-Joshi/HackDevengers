import logging
from fastapi import APIRouter, HTTPException, status

from app.pipeline.types import ActionItem, ActionStatusUpdateRequest
from app.services.supabase import supabase_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["Actions"])


@router.patch("/{action_id}", response_model=ActionItem)
async def update_action_status_endpoint(
    action_id: str,
    payload: ActionStatusUpdateRequest,
) -> ActionItem:
    """
    Update the status of an existing action item ('pending', 'in_progress', 'completed', 'dismissed').
    """
    if not supabase_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not configured."
        )

    try:
        updated = supabase_service.update_action_status(action_id, payload.status.value)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Action item with ID '{action_id}' not found."
            )
        return ActionItem.model_validate(updated)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update action status for {action_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update action status: {str(e)}"
        )
