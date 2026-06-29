"""
main.py – FastAPI Application Entry Point
==========================================
## Changes (Feature Update)
- Feature 1: Added JWT auth via auth.py router; history endpoints (GET/DELETE /history, GET /history/{id})
             Auto-save to ReportHistory when user is authenticated on /analyze
             init_db() called at startup via database.py
- Feature 2: Added `language` field to AnalyseRequest and AskRequest; passed to LLM agent
- Feature 7: Replaced list[dict] with typed TestInput Pydantic model
             CORS origins now configurable via ALLOWED_ORIGINS env variable
             Added database.py and models.py for clean separation

Architecture Role: Layer 1 – PDF Upload Layer / API Gateway
Responsibility:
    - Expose REST API endpoints for the frontend
    - Orchestrate parser → risk engine → LLM agent pipeline
    - Handle errors gracefully with informative responses
    - JWT-protected history management

Endpoints:
    GET  /health                → Health check
    POST /upload                → Parse PDF, return extracted table
    POST /analyze               → Full analysis: risk score + AI summary (saves to history if authed)
    POST /ask                   → Q&A agent for interactive questions
    POST /auth/register         → Create account, return token
    POST /auth/login            → Login, return token
    GET  /auth/me               → Get current user profile
    GET  /history               → Get user's report history (auth required)
    GET  /history/{report_id}   → Get a specific saved report (auth required)
    DELETE /history/{report_id} → Delete a saved report (auth required)
"""

import os
import io
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional, List
from dotenv import load_dotenv

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Load environment variables from .env file (if present)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-loaded singletons (initialised at startup to avoid cold-start delay)
# ---------------------------------------------------------------------------
_rag_pipeline = None
_llm_agent = None
_risk_engine = None


def get_rag():
    global _rag_pipeline
    if _rag_pipeline is None:
        from rag_pipeline import RAGPipeline
        logger.info("Initialising RAG pipeline…")
        _rag_pipeline = RAGPipeline()
    return _rag_pipeline


def get_llm():
    global _llm_agent
    if _llm_agent is None:
        from llm_agent import LLMAgent
        logger.info("Initialising LLM agent…")
        _llm_agent = LLMAgent(get_rag())
    return _llm_agent


def get_risk_engine():
    global _risk_engine
    if _risk_engine is None:
        from risk_engine import RiskEngine
        logger.info("Initialising Risk Engine…")
        _risk_engine = RiskEngine()
    return _risk_engine


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm singletons at startup and initialise database."""
    logger.info("Starting Lab Report Intelligence Agent API…")
    try:
        from database import init_db
        init_db()
        logger.info("Database initialised.")
        get_risk_engine()
        get_rag()
        get_llm()
        logger.info("All components initialised successfully.")
    except Exception as exc:
        logger.warning("Startup pre-warming failed (non-fatal): %s", exc)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Lab Report Intelligence Agent API",
    description="AI-Powered Patient Report Simplifier – MediExplain AI",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS – configurable via ALLOWED_ORIGINS env var
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
if _raw_origins.strip() == "*":
    _cors_origins = ["*"]
else:
    _cors_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register auth router
from auth import router as auth_router, get_current_user, require_current_user
from database import get_db
app.include_router(auth_router)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class TestInput(BaseModel):
    """Typed representation of a single lab test (replaces list[dict])."""
    test_name: str
    measured_value: float
    unit: str = ""
    reference_range: str = ""


class AskRequest(BaseModel):
    question: str
    report_context: str = ""
    language: str = "en"


class AnalyseRequest(BaseModel):
    """Body includes the previously uploaded and extracted lab data."""
    tests: List[TestInput]
    historical_tests: Optional[List[TestInput]] = None
    language: str = "en"
    filename: str = "uploaded_report.pdf"


# ---------------------------------------------------------------------------
# Helper: Convert TestResult dataclass to dict for JSON serialisation
# ---------------------------------------------------------------------------

def _result_to_dict(r) -> dict:
    return {
        "test_name": r.test_name,
        "measured_value": r.measured_value,
        "unit": r.unit,
        "reference_range": r.reference_range,
        "status": r.status,
        "normal_min": r.normal_min,
        "normal_max": r.normal_max,
        "description": r.description,
        "status_description": r.status_description,
        "in_benchmark": r.in_benchmark,
        "is_critical": getattr(r, "is_critical", False),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "Lab Report Intelligence Agent", "version": "2.0.0"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Layer 1 + Layer 2: Accept a PDF upload and extract lab values.
    Returns extracted lab test rows as a JSON array.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted. Please upload a .pdf file.",
        )

    try:
        contents = await file.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        from parser import parse_pdf
        df = parse_pdf(io.BytesIO(contents))

        if df.empty:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": (
                        "The PDF was read, but no lab test values could be extracted. "
                        "The report may use a format that requires manual review."
                    ),
                    "tests": [],
                    "count": 0,
                },
            )

        tests = df.to_dict(orient="records")
        logger.info("Extracted %d tests from uploaded PDF '%s'.", len(tests), file.filename)

        return {
            "success": True,
            "message": f"Successfully extracted {len(tests)} lab test(s).",
            "tests": tests,
            "count": len(tests),
            "filename": file.filename,
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("PDF upload failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the PDF. Please try again.",
        )


@app.post("/analyze")
async def analyze_report(
    request: AnalyseRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Layers 3–6: Full analysis pipeline.
    Accepts extracted test data, runs risk engine, and generates AI summary.
    Returns: risk score, risk category, full results, patterns, AI summary.
    If authenticated, auto-saves to ReportHistory.
    """
    if not request.tests:
        raise HTTPException(
            status_code=400,
            detail="No test data provided. Please upload a PDF or add tests manually.",
        )

    try:
        import pandas as pd
        tests_dicts = [t.model_dump() for t in request.tests]
        df = pd.DataFrame(tests_dicts)

        historical_df = None
        if request.historical_tests:
            hist_dicts = [t.model_dump() for t in request.historical_tests]
            historical_df = pd.DataFrame(hist_dicts)

        # Layer 3 + 4: Risk engine
        engine = get_risk_engine()
        report = engine.analyse(df, historical_df=historical_df)

        # Prepare structured results
        results_list = [_result_to_dict(r) for r in report.results]

        # Layer 6: AI Summary (with language)
        agent = get_llm()
        summary = agent.generate_summary(
            results=report.results,
            risk_score=report.risk_score,
            risk_category=report.risk_category,
            patterns=report.patterns,
            trends=report.trends,
            language=request.language,
        )

        response_data = {
            "success": True,
            "risk_score": report.risk_score,
            "risk_category": report.risk_category,
            "abnormal_count": report.abnormal_count,
            "total_count": len(results_list),
            "results": results_list,
            "patterns": report.patterns,
            "trends": report.trends,
            "ai_summary": summary,
        }

        # Auto-save to history if authenticated
        if current_user is not None:
            try:
                import models
                history_entry = models.ReportHistory(
                    user_id=current_user.id,
                    filename=request.filename,
                    risk_category=report.risk_category,
                    risk_score=report.risk_score,
                    ai_summary=summary,
                    results_json=json.dumps(results_list),
                )
                db.add(history_entry)
                db.commit()
                db.refresh(history_entry)
                response_data["history_id"] = history_entry.id
                logger.info("Saved report to history for user %s (id=%d)", current_user.email, history_entry.id)
            except Exception as exc:
                logger.warning("Failed to save history entry: %s", exc)

        return response_data

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(exc)}",
        )


@app.post("/ask")
async def ask_question(request: AskRequest):
    """
    Layer 7: Interactive Q&A Agent.
    Answers patient questions about their lab report using RAG.
    Strictly limited to knowledge base — no hallucinations.
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(request.question) > 500:
        raise HTTPException(
            status_code=400,
            detail="Question is too long. Please keep it under 500 characters.",
        )

    try:
        agent = get_llm()
        answer = agent.answer_question(
            question=request.question.strip(),
            report_context=request.report_context,
            language=request.language,
        )
        return {
            "success": True,
            "question": request.question,
            "answer": answer,
        }
    except Exception as exc:
        logger.error("Q&A failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Could not generate an answer. Please try again.",
        )


# ---------------------------------------------------------------------------
# History Endpoints (auth required)
# ---------------------------------------------------------------------------

@app.get("/history")
async def get_history(current_user=Depends(require_current_user)):
    """Return the authenticated user's past report summaries."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    try:
        reports = (
            db.query(models.ReportHistory)
            .filter(models.ReportHistory.user_id == current_user.id)
            .order_by(models.ReportHistory.uploaded_at.desc())
            .all()
        )
        return {
            "success": True,
            "history": [
                {
                    "id": r.id,
                    "filename": r.filename,
                    "uploaded_at": r.uploaded_at.isoformat(),
                    "risk_category": r.risk_category,
                    "risk_score": r.risk_score,
                }
                for r in reports
            ],
        }
    finally:
        db.close()


@app.get("/history/{report_id}")
async def get_history_report(report_id: int, current_user=Depends(require_current_user)):
    """Return a full saved report for reloading into the UI."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    try:
        report = db.query(models.ReportHistory).filter(
            models.ReportHistory.id == report_id,
            models.ReportHistory.user_id == current_user.id,
        ).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found.")

        results = json.loads(report.results_json) if report.results_json else []
        return {
            "success": True,
            "id": report.id,
            "filename": report.filename,
            "uploaded_at": report.uploaded_at.isoformat(),
            "risk_category": report.risk_category,
            "risk_score": report.risk_score,
            "ai_summary": report.ai_summary,
            "results": results,
        }
    finally:
        db.close()


@app.delete("/history/{report_id}")
async def delete_history_report(report_id: int, current_user=Depends(require_current_user)):
    """Delete a saved report from the user's history."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    try:
        report = db.query(models.ReportHistory).filter(
            models.ReportHistory.id == report_id,
            models.ReportHistory.user_id == current_user.id,
        ).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found.")

        db.delete(report)
        db.commit()
        logger.info("Deleted history report %d for user %s", report_id, current_user.email)
        return {"success": True, "message": "Report deleted successfully."}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Mount frontend static files last
# ---------------------------------------------------------------------------
frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
