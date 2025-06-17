# mcp_service/app/api/endpoints/files.py

import uuid
import os
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from app.core.settings import settings
from app.utils.logger import logger

router = APIRouter()

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more CIF files for processing"
)
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Receives one or more CIF files, saves them to a unique session directory
    on the server, and returns the session ID.

    Args:
        files: A list of files uploaded by the client.

    Returns:
        A dictionary containing the unique upload_session_id.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    # Create a unique session ID for this batch of uploads
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(settings.FILE_STORAGE_PATH, session_id)

    try:
        os.makedirs(session_dir, exist_ok=True)
        logger.info(f"Created new upload session directory: {session_dir}")

        for file in files:
            if not file.filename.endswith('.cif'):
                logger.warning(f"Skipping non-CIF file: {file.filename}")
                continue
            
            file_path = os.path.join(session_dir, file.filename)
            
            with open(file_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
            logger.success(f"Successfully saved uploaded file: {file_path}")

    except Exception as e:
        logger.error(f"Failed to save uploaded files for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not save uploaded files.")

    return {"upload_session_id": session_id}
