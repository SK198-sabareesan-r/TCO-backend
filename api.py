"""
api.py
------
Enhanced FastAPI application for Cloud Migration Cost Estimator.
Designed for frontend integration with comprehensive endpoints.

Features:
- CORS enabled for frontend integration
- File upload with validation
- Source provider selection (Azure/GCP)
- Target provider fixed to AWS
- Progress tracking
- Detailed error responses
- JSON and XLSX output formats
"""

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

from agents.orchestrator import run_migration_pipeline, process_all_services
from utils.excel import read_input_xlsx
from utils.db import test_connection
from utils.token_tracker import get_token_stats

load_dotenv()

# Configure logging to terminal only
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App Configuration
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cloud Migration Cost Estimator API",
    description="Estimate AWS migration costs from Azure/GCP services",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tco.shellkode.ai",
        "http://localhost:3000",   # local frontend dev
        "http://localhost:5173",   # Vite dev server
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job storage (use Redis/DB in production)
jobs: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class MigrationRequest(BaseModel):
    """Request model for migration estimation"""
    source_provider: str = Field(..., description="Source cloud provider (Azure or GCP)")
    target_provider: str = Field(default="AWS", description="Target cloud provider (fixed to AWS)")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_provider": "Azure",
                "target_provider": "AWS"
            }
        }
    )


class JobStatus(BaseModel):
    """Job status response model"""
    job_id: str
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    message: str
    created_at: str
    completed_at: Optional[str] = None
    result_url: Optional[str] = None
    error: Optional[str] = None


class MigrationSummary(BaseModel):
    """Summary of migration results"""
    total_services: int
    total_current_cost: float
    total_aws_ondemand_cost: float
    total_aws_optimized_cost: float
    total_savings: float
    savings_percent: float
    processing_time_seconds: float
    token_usage: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Health & Info Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    """API root endpoint with basic information"""
    return {
        "service": "Cloud Migration Cost Estimator API",
        "version": "2.0.0",
        "status": "operational",
        "documentation": "/docs",
        "endpoints": {
            "health": "/health",
            "schema": "/schema",
            "migrate": "/migrate",
            "migrate_async": "/migrate/async",
            "job_status": "/jobs/{job_id}",
            "download": "/download/{job_id}"
        }
    }


@app.get("/health", tags=["Info"])
def health_check():
    """
    Health check endpoint
    Returns system status and database connectivity
    """
    db_ok = test_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "api": "operational",
            "database": "connected" if db_ok else "unreachable",
            "llm": "operational"  # Could add Bedrock health check
        },
        "version": "2.0.0"
    }



@app.get("/schema", tags=["Info"])
def get_input_schema():
    """
    Get expected XLSX input schema
    Returns column definitions and example rows
    """
    return {
        "description": "Expected columns in the input XLSX file",
        "source_providers": ["Azure", "GCP"],
        "target_provider": "AWS (fixed)",
        "required_columns": ["service_type", "current_provider"],
        "optional_columns": {
            "service_name": "Human-readable name (e.g. Web Server, DB Primary)",
            "service_type": "ec2 | rds | s3 | vpc | lambda",
            "current_provider": "Azure | GCP",
            "instance_type": "Source instance type (e.g. n2-standard-4, Standard_D4s_v3)",
            "vcpus": "Number of vCPUs",
            "memory_gib": "Memory in GiB",
            "region": "Source region (Azure/GCP region names)",
            "tenancy": "Shared | Dedicated (default: Shared)",
            "operating_system": "Linux | Windows (default: Linux)",
            "storage_gb": "Storage in GB",
            "number_of_instances": "Count of this instance type (default: 1)",
            "current_monthly_cost_usd": "Current monthly spend for comparison",
            "database_engine": "[RDS only] MySQL | PostgreSQL | MariaDB | Oracle | SQL Server",
            "multi_az": "[RDS only] TRUE | FALSE",
            "workload": "Constant | Variable (informational)",
            "notes": "Any additional notes"
        },
        "example_rows": [
            {
                "service_name": "Web Server",
                "service_type": "ec2",
                "current_provider": "Azure",
                "instance_type": "Standard_D4s_v3",
                "vcpus": 4,
                "memory_gib": 16,
                "region": "Central India",
                "operating_system": "Linux",
                "storage_gb": 100,
                "current_monthly_cost_usd": 450.00
            },
            {
                "service_name": "Database Primary",
                "service_type": "rds",
                "current_provider": "GCP",
                "instance_type": "n1-highmem-4",
                "vcpus": 4,
                "memory_gib": 26,
                "region": "us-east1",
                "database_engine": "MySQL",
                "storage_gb": 500,
                "current_monthly_cost_usd": 320.00
            }
        ],
        "notes": [
            "Auto-detection: Provider can be auto-detected from filename (azure_export.xlsx → Azure)",
            "Multi-sheet: Supports multi-sheet Excel files (Virtual Machines, SQL DBs, Storage Accounts)",
            "Column aliases: Flexible column names (Size → instance_type, Location → region)",
            "Defaults: Missing values use sensible defaults (OS=Linux, tenancy=Shared, storage=100GB for S3)"
        ]
    }



# ─────────────────────────────────────────────────────────────────────────────
# Synchronous Migration Endpoint (XLSX Output)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/migrate", tags=["Migration"], response_class=FileResponse)
async def migrate_xlsx(
    file: UploadFile = File(..., description="XLSX file with cloud services"),
    source_provider: str = Form(..., description="Source cloud provider (Azure or GCP)")
):
    """
    Synchronous migration endpoint - Upload XLSX and download AWS estimate XLSX
    
    **Parameters:**
    - file: XLSX file containing cloud services
    - source_provider: Source cloud provider (Azure or GCP)
    
    **Returns:**
    - XLSX file with 5 sheets:
      1. Summary: Best match + optimized costs per service
      2. All Matches: All AWS candidates with pricing
      3. CSP Options: All 6 Savings Plans + Spot pricing
      4. Cost Comparison: Current vs AWS
      5. Mapping Details: Parameters used for matching
    
    **Processing Time:** ~25-35 seconds per service
    """
    # Validate file type - support all Excel formats
    allowed_extensions = (".xlsx", ".xls", ".xlsm", ".xlsb", ".csv")
    if not file.filename.endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Supported formats: {', '.join(allowed_extensions)}"
        )
    
    # Validate source provider
    source_provider = source_provider.strip().title()
    if source_provider not in ["Azure", "Gcp", "GCP"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source provider '{source_provider}'. Must be 'Azure' or 'GCP'."
        )
    
    # Normalize GCP
    if source_provider.upper() == "GCP":
        source_provider = "GCP"
    
    logger.info(f"Migration request: {file.filename} from {source_provider} to AWS")
    
    # Create temp directory that won't be auto-deleted
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, f"{source_provider.lower()}_{file.filename}")
    output_path = os.path.join(tmpdir, "aws_estimate.xlsx")
    
    # Save uploaded file
    try:
        contents = await file.read()
        with open(input_path, "wb") as f:
            f.write(contents)
        logger.info(f"Saved upload: {len(contents)} bytes")
    except Exception as e:
        logger.error(f"File save error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
    
    # Run migration pipeline
    try:
        output_file = run_migration_pipeline(input_path, output_path, source_provider=source_provider)
        logger.info(f"Pipeline completed: {output_file}")
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Migration pipeline failed: {str(e)}"
        )
    
    # Return XLSX file
    output_filename = f"aws_estimate_{source_provider.lower()}_{Path(file.filename).stem}.xlsx"
    return FileResponse(
        path=output_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=output_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Source-Provider": source_provider,
            "X-Target-Provider": "AWS"
        }
    )



# ─────────────────────────────────────────────────────────────────────────────
# Synchronous Migration Endpoint (JSON Output)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/migrate/json", tags=["Migration"])
async def migrate_json(
    file: UploadFile = File(..., description="XLSX file with cloud services"),
    source_provider: str = Form(..., description="Source cloud provider (Azure or GCP)")
):
    """
    Synchronous migration endpoint - Upload XLSX and receive JSON results
    
    **Parameters:**
    - file: XLSX file containing cloud services
    - source_provider: Source cloud provider (Azure or GCP)
    
    **Returns:**
    - JSON with detailed results for each service including:
      - AWS matches with pricing
      - Best match and optimized recommendation
      - Cost comparison and savings
      - Token usage statistics
    
    **Use Case:** Programmatic consumption, frontend display
    """
    # Validate file type - support all Excel formats
    allowed_extensions = (".xlsx", ".xls", ".xlsm", ".xlsb", ".csv")
    if not file.filename.endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Supported formats: {', '.join(allowed_extensions)}"
        )
    
    # Validate source provider
    source_provider = source_provider.strip().title()
    if source_provider not in ["Azure", "Gcp", "GCP"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source provider '{source_provider}'. Must be 'Azure' or 'GCP'."
        )
    
    if source_provider.upper() == "GCP":
        source_provider = "GCP"
    
    logger.info(f"JSON migration request: {file.filename} from {source_provider} to AWS")
    
    # Create temp directory
    tmpdir = tempfile.mkdtemp()
    input_path = os.path.join(tmpdir, f"{source_provider.lower()}_{file.filename}")
    
    # Save uploaded file
    try:
        contents = await file.read()
        with open(input_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        logger.error(f"File save error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")
    
    # Read and process services
    try:
        start_time = datetime.utcnow()
        services = read_input_xlsx(input_path, source_provider=source_provider)
        results = process_all_services(services, output_path=None)
        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        
        logger.info(f"Processed {len(results)} services in {processing_time:.2f}s")
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process services: {str(e)}"
        )
    finally:
        # Cleanup temp directory
        try:
            import shutil
            shutil.rmtree(tmpdir)
        except:
            pass
    
    # Calculate summary
    summary = calculate_summary(results, processing_time)
    
    # Serialize results (remove non-serializable objects)
    safe_results = safe_serialize(results)
    
    return {
        "success": True,
        "source_provider": source_provider,
        "target_provider": "AWS",
        "summary": summary,
        "results": safe_results,
        "timestamp": datetime.utcnow().isoformat()
    }



# ─────────────────────────────────────────────────────────────────────────────
# Asynchronous Migration Endpoint (Background Processing)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/migrate/async", tags=["Migration"], response_model=JobStatus)
async def migrate_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="XLSX file with cloud services"),
    source_provider: str = Form(..., description="Source cloud provider (Azure or GCP)")
):
    """
    Asynchronous migration endpoint - Upload XLSX and get job ID for tracking

    **Parameters:**
    - file: XLSX file containing cloud services
    - source_provider: Source cloud provider (Azure or GCP)

    **Returns:**
    - Job ID for tracking progress

    **Workflow:**
    1. Upload file → Get job_id
    2. Poll /jobs/{job_id} for status
    3. Download result from /download/{job_id} when completed

    **Use Case:** Large files, long-running migrations, progress tracking
    """
    logger.info(f"📥 [UPLOAD] Received file: {file.filename}, Provider: {source_provider}")

    # Validate file type
    if not file.filename.endswith((".xlsx", ".xls")):
        logger.error(f"❌ [UPLOAD] Invalid file type: {file.filename}")
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only .xlsx and .xls files are supported."
        )

    # Validate source provider
    source_provider = source_provider.strip().title()
    if source_provider not in ["Azure", "Gcp", "GCP"]:
        logger.error(f"❌ [UPLOAD] Invalid provider: {source_provider}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source provider '{source_provider}'. Must be 'Azure' or 'GCP'."
        )

    if source_provider.upper() == "GCP":
        source_provider = "GCP"

    logger.info(f"✅ [UPLOAD] Validated - Provider: {source_provider}")

    # Generate job ID
    job_id = str(uuid.uuid4())
    logger.info(f"🆔 [JOB] Created job ID: {job_id}")

    # Save file to temp location
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, f"{source_provider.lower()}_{file.filename}")
    output_path = os.path.join(temp_dir, f"aws_estimate_{job_id}.xlsx")

    try:
        contents = await file.read()
        file_size = len(contents)
        logger.info(f"💾 [FILE] Saving {file_size} bytes to {input_path}")
        with open(input_path, "wb") as f:
            f.write(contents)
        logger.info(f"✅ [FILE] Saved successfully")
    except Exception as e:
        logger.error(f"❌ [FILE] Failed to save: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Create job record
    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "message": "Job queued for processing",
        "created_at": datetime.utcnow().isoformat(),
        "source_provider": source_provider,
        "target_provider": "AWS",
        "input_path": input_path,
        "output_path": output_path,
        "temp_dir": temp_dir,
        "filename": file.filename
    }

    logger.info(f"📋 [JOB] Job record created: {job_id}")

    # Add background task
    background_tasks.add_task(process_migration_job, job_id)
    logger.info(f"🚀 [JOB] Background task queued: {job_id}")

    logger.info(f"✅ [UPLOAD] Complete - Job {job_id} ready for processing")

    return JobStatus(
        job_id=job_id,
        status="pending",
        progress=0,
        message="Job queued for processing",
        created_at=jobs[job_id]["created_at"]
    )


def process_migration_job(job_id: str):
    """Background task to process migration job with progress updates"""
    try:
        logger.info(f"⚙️ [PROCESSING] Starting job {job_id}")

        job = jobs[job_id]
        job["status"] = "processing"
        job["message"] = "📤 File uploaded successfully"
        job["progress"] = 5

        logger.info(f"📂 [PROCESSING] Input: {job['input_path']}")
        logger.info(f"📂 [PROCESSING] Output: {job['output_path']}")
        logger.info(f"🏢 [PROCESSING] Provider: {job['source_provider']} → {job['target_provider']}")

        # Update: Validating file
        job["message"] = "✅ Validating file format..."
        job["progress"] = 10

        # Update: Starting pipeline
        job["message"] = "⚙️ Starting analysis pipeline..."
        job["progress"] = 15
        logger.info(f"🚀 [PIPELINE] Starting migration pipeline...")

        # PRODUCTION MODE: Process all services
        # To limit for local debugging, set TEST_MODE = True and limit = 5
        TEST_MODE = False
        limit = None  # process every row in the uploaded file

        # Run pipeline with progress callback
        job["message"] = "🔄 Loading services from Excel..."
        job["progress"] = 20

        output_file = run_migration_pipeline(
            job["input_path"],
            job["output_path"],
            source_provider=job["source_provider"],
            limit=limit,
            progress_callback=lambda msg, pct: _update_job_progress(job_id, msg, pct)
        )
        logger.info(f"✅ [PIPELINE] Pipeline completed - Output: {output_file}")

        # Update job status
        job["status"] = "completed"
        job["progress"] = 100
        job["message"] = "✅ Analysis complete! Preparing download..."
        job["completed_at"] = datetime.utcnow().isoformat()
        job["result_url"] = f"/download/{job_id}"

        logger.info(f"✅ [PROCESSING] Job {job_id} completed successfully")

    except Exception as e:
        logger.error(f"❌ [PROCESSING] Job {job_id} failed: {e}", exc_info=True)
        job = jobs.get(job_id, {})
        job["status"] = "failed"
        job["progress"] = 0
        job["message"] = f"❌ Migration failed: {str(e)}"
        job["error"] = str(e)
        job["completed_at"] = datetime.utcnow().isoformat()


def _update_job_progress(job_id: str, message: str, progress: int):
    """Helper to update job progress from pipeline"""
    if job_id in jobs:
        jobs[job_id]["message"] = message
        jobs[job_id]["progress"] = progress
        logger.debug(f"📊 Job {job_id}: {progress}% - {message}")



@app.get("/jobs/{job_id}", tags=["Jobs"], response_model=JobStatus)
def get_job_status(job_id: str):
    """
    Get status of an async migration job

    **Parameters:**
    - job_id: Job ID returned from /migrate/async

    **Returns:**
    - Job status with progress (0-100)
    - Result URL when completed
    - Error message if failed
    """
    logger.debug(f"📊 [STATUS] Checking job {job_id}")

    if job_id not in jobs:
        logger.warning(f"⚠️ [STATUS] Job {job_id} not found")
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs[job_id]
    logger.debug(f"📊 [STATUS] Job {job_id}: {job['status']} - {job['progress']}%")

    return JobStatus(
        job_id=job["job_id"],
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        result_url=job.get("result_url"),
        error=job.get("error")
    )


@app.get("/download/{job_id}", tags=["Jobs"], response_class=FileResponse)
def download_result(job_id: str):
    """
    Download result XLSX for completed job

    **Parameters:**
    - job_id: Job ID returned from /migrate/async

    **Returns:**
    - XLSX file with migration results
    """
    logger.info(f"⬇️ [DOWNLOAD] Request for job {job_id}")

    if job_id not in jobs:
        logger.warning(f"⚠️ [DOWNLOAD] Job {job_id} not found")
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = jobs[job_id]

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job['status']}"
        )
    
    if not os.path.exists(job["output_path"]):
        raise HTTPException(status_code=404, detail="Result file not found")
    
    output_filename = f"aws_estimate_{job['source_provider'].lower()}_{Path(job['filename']).stem}.xlsx"
    
    return FileResponse(
        path=job["output_path"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=output_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Job-ID": job_id,
            "X-Source-Provider": job["source_provider"],
            "X-Target-Provider": "AWS"
        }
    )


@app.delete("/jobs/{job_id}", tags=["Jobs"])
def delete_job(job_id: str):
    """
    Delete job and cleanup temporary files
    
    **Parameters:**
    - job_id: Job ID to delete
    
    **Returns:**
    - Success message
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    
    # Cleanup temp files
    try:
        if os.path.exists(job["temp_dir"]):
            import shutil
            shutil.rmtree(job["temp_dir"])
    except Exception as e:
        logger.warning(f"Failed to cleanup temp dir for job {job_id}: {e}")
    
    # Remove job record
    del jobs[job_id]
    
    logger.info(f"Deleted job {job_id}")
    
    return {"message": f"Job {job_id} deleted successfully"}



# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def calculate_summary(results: list, processing_time: float) -> dict:
    """Calculate summary statistics from results"""
    total_current = 0
    total_ondemand = 0
    total_optimized = 0
    
    for result in results:
        inp = result.get("input", {})
        costs = result.get("costs", {})
        opt = result.get("optimised", {})
        
        current = inp.get("current_monthly_cost_usd")
        if current:
            total_current += float(current)
        
        ondemand = costs.get("ondemand", {}).get("monthly_usd")
        if ondemand:
            total_ondemand += float(ondemand)
        
        optimized = opt.get("monthly_usd")
        if optimized:
            total_optimized += float(optimized)
    
    total_savings = total_current - total_optimized if total_current > 0 else 0
    savings_percent = (total_savings / total_current * 100) if total_current > 0 else 0
    
    # Get token usage
    token_stats = get_token_stats()
    
    return {
        "total_services": len(results),
        "total_current_cost": round(total_current, 2),
        "total_aws_ondemand_cost": round(total_ondemand, 2),
        "total_aws_optimized_cost": round(total_optimized, 2),
        "total_savings": round(total_savings, 2),
        "savings_percent": round(savings_percent, 2),
        "processing_time_seconds": round(processing_time, 2),
        "token_usage": token_stats
    }


def safe_serialize(obj):
    """Recursively serialize objects to JSON-safe types"""
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [safe_serialize(i) for i in obj]
    elif isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    elif hasattr(obj, '__dict__'):
        return safe_serialize(obj.__dict__)
    else:
        return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc),
            "status_code": 500,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Run Server
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "api:app",
        host="localhost",
        port=8000,
        reload=True,
        log_level="info"
    )
