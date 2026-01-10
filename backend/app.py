"""
FastAPI application for Podcast Language Converter
Provides REST API and WebSocket for job management
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from fastapi import Request
from dotenv import load_dotenv

from backend.models import (
    Job, JobStatus, JobProgress, CreateJobRequest,
    JobResponse, JobListResponse
)
from backend.services.storage import get_storage
from backend.services.youtube import YouTubeService
from backend.workers.tasks import process_podcast_task

# Load environment variables
load_dotenv()

# Initialize FastAPI
app = FastAPI(
    title="Podcast Language Converter",
    description="Convert German YouTube podcasts to Polish with AI",
    version="1.0.0"
)

# Setup templates and static files
templates = Jinja2Templates(directory="frontend/templates")
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for live log streaming"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


# ===== ROUTES =====

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/jobs", response_model=JobListResponse)
async def create_jobs(request: CreateJobRequest):
    """
    Create new processing jobs from YouTube URLs

    Body:
        {
            "urls": ["https://youtube.com/watch?v=xxx", ...]
        }

    Returns:
        List of created jobs
    """
    storage = get_storage()
    yt_service = YouTubeService()
    created_jobs = []

    for url in request.urls:
        # Validate URL
        video_id = yt_service.extract_video_id(url)
        if not video_id:
            raise HTTPException(status_code=400, detail=f"Invalid YouTube URL: {url}")

        # Create job
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            url=url,
            status=JobStatus.QUEUED,
            video_id=video_id
        )

        # Save job state
        storage.save_job_state(job)
        storage.add_log(job_id, f"Job created for URL: {url}", "INFO")

        # Queue Celery task
        process_podcast_task.delay(job_id=job_id, url=url)

        created_jobs.append(job)

    return JobListResponse(jobs=created_jobs, total=len(created_jobs))


@app.get("/api/jobs", response_model=JobListResponse)
async def list_jobs():
    """Get all jobs"""
    storage = get_storage()
    jobs = storage.get_all_jobs()
    return JobListResponse(jobs=jobs, total=len(jobs))


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """Get specific job details"""
    storage = get_storage()
    job = storage.load_job_state(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(job=job)


@app.get("/api/jobs/{job_id}/logs")
async def get_job_logs(job_id: str):
    """Get job logs"""
    storage = get_storage()
    job = storage.load_job_state(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"job_id": job_id, "logs": job.logs}


@app.get("/api/jobs/{job_id}/download")
async def download_final_video(job_id: str):
    """Download final rendered video"""
    storage = get_storage()
    job = storage.load_job_state(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=400, detail="Job not completed yet")

    final_video_path = Path(job.artifacts.final_video)

    if not final_video_path.exists():
        raise HTTPException(status_code=404, detail="Final video file not found")

    return FileResponse(
        path=str(final_video_path),
        media_type="video/mp4",
        filename=f"{job.video_id}_polish.mp4"
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete job and all its artifacts"""
    storage = get_storage()
    job = storage.load_job_state(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    storage.cleanup_job(job_id)

    return {"status": "deleted", "job_id": job_id}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time log streaming

    Clients can connect to receive live updates for all jobs
    """
    await manager.connect(websocket)

    try:
        while True:
            # Keep connection alive and receive any client messages
            data = await websocket.receive_text()

            # Echo back for testing
            await websocket.send_json({
                "type": "ping",
                "message": "pong"
            })

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


# Run with: uvicorn backend.app:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
