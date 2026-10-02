"""FastAPI main application"""
import hmac
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.models import (
    PurchaseRecommendation, ReviewRequest, ReviewResponse,
    RecommendationStatus
)
from app.database import db
from app.agent.orchestrator import (
    PurchasingAgentOrchestrator, AlreadyReviewedError, NotApprovableError
)
from app.agent.tools import DataNotFoundError
from app.agent.llm_client import default_model

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="AI Purchasing Agent",
    description="Quick-commerce purchase recommendation review agent",
    version="1.0.0"
)

logger = logging.getLogger(__name__)

# CORS: explicit origins only (CORS_ORIGINS, comma separated). The dev frontend uses
# the Vite proxy, so same-origin requests need no CORS at all. No credentials/cookies.
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def _api_key_ok(provided: Optional[str]) -> bool:
    expected = os.getenv("API_KEY", "")
    return bool(expected) and provided is not None and hmac.compare_digest(provided, expected)


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Writes need the API key when API_KEY is set (unset = open demo mode)"""
    if os.getenv("API_KEY") and not _api_key_ok(x_api_key):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")


def require_approver_key(x_api_key: Optional[str] = Header(default=None)):
    """Human approvals ALWAYS need a configured key - never available in open mode"""
    if not os.getenv("API_KEY"):
        raise HTTPException(status_code=503, detail="Approvals disabled: set API_KEY to enable them")
    if not _api_key_ok(x_api_key):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

# Initialize orchestrator
orchestrator = PurchasingAgentOrchestrator()


# Request models
class CreateRecommendationRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=200)
    node_id: str = Field(min_length=1, max_length=100)
    node_name: str = Field(min_length=1, max_length=200)
    recommended_quantity: int = Field(gt=0, le=1_000_000)
    recommended_supplier: str = Field(min_length=1, max_length=100)


class ApproveRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=1000)


class RejectRequest(BaseModel):
    rejected_by: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "ok",
        "service": "AI Purchasing Agent",
        "version": "1.0.0"
    }


@app.post("/api/recommendations", response_model=PurchaseRecommendation, dependencies=[Depends(require_api_key)])
async def create_recommendation(req: CreateRecommendationRequest):
    """Create a new purchase recommendation"""
    
    recommendation_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
    
    rec_data = {
        "recommendation_id": recommendation_id,
        "product_id": req.product_id,
        "product_name": req.product_name,
        "node_id": req.node_id,
        "node_name": req.node_name,
        "recommended_quantity": req.recommended_quantity,
        "recommended_supplier": req.recommended_supplier,
        "recommendation_source": "system_auto",
        "status": "pending_review"
    }
    
    db.save_recommendation(rec_data)
    
    return PurchaseRecommendation(**rec_data, created_at=datetime.utcnow())


@app.get("/api/recommendations", response_model=List[dict])
async def list_recommendations():
    """List all recommendations"""
    # Simple query to get all recommendations
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT * FROM recommendations 
            ORDER BY created_at DESC 
            LIMIT 50
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


@app.get("/api/recommendations/{recommendation_id}")
async def get_recommendation(recommendation_id: str):
    """Get a specific recommendation"""
    rec = db.get_recommendation(recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec


@app.post("/api/recommendations/{recommendation_id}/review", dependencies=[Depends(require_api_key)])
async def review_recommendation(recommendation_id: str):
    """Review a purchase recommendation using the agent"""
    
    try:
        result = orchestrator.review_recommendation(recommendation_id)
        
        # Convert to response model (Pydantic models serialize to JSON properly)
        return {
            "recommendation_id": result["recommendation_id"],
            "investigation": result["investigation"].model_dump(mode='json'),
            "decision": result["decision"].model_dump(mode='json'),
            "constraint_validation": result["constraint_validation"].model_dump(mode='json'),
            "purchase_order": result["purchase_order"].model_dump(mode='json') if result["purchase_order"] else None,
            "post_validation": result["post_validation"].model_dump(mode='json') if result["post_validation"] else None,
            "trace": result["trace"]
        }
    
    except AlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DataNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"Escalated - missing data: {e}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Agent error reviewing %s", recommendation_id)
        raise HTTPException(status_code=500, detail="Agent error - recommendation escalated; see server logs")


def _po_response(result):
    return {
        "recommendation_id": result["recommendation_id"],
        "status": result["status"],
        "approved_by": result["approved_by"],
        "purchase_order": result["purchase_order"].model_dump(mode='json') if result["purchase_order"] else None,
        "post_validation": result["post_validation"].model_dump(mode='json') if result["post_validation"] else None,
        "trace": result["trace"],
    }


@app.post("/api/recommendations/{recommendation_id}/approve", dependencies=[Depends(require_approver_key)])
async def approve_recommendation(recommendation_id: str, req: ApproveRequest):
    """Human approval of an escalated ACCEPT/MODIFY decision (hard constraints still enforced)"""
    try:
        return _po_response(
            orchestrator.approve_recommendation(recommendation_id, req.approved_by, req.notes)
        )
    except (AlreadyReviewedError, NotApprovableError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DataNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"Escalated - missing data: {e}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Error approving %s", recommendation_id)
        raise HTTPException(status_code=500, detail="Approval error - recommendation left escalated; see server logs")


@app.post("/api/recommendations/{recommendation_id}/reject", dependencies=[Depends(require_approver_key)])
async def reject_recommendation(recommendation_id: str, req: RejectRequest):
    """Human rejection of an escalated recommendation"""
    try:
        return orchestrator.reject_recommendation(recommendation_id, req.rejected_by, req.reason)
    except AlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/recommendations/{recommendation_id}/trace")
async def get_trace(recommendation_id: str):
    """Get decision trace for a recommendation"""
    trace = db.get_trace(recommendation_id)
    return {"recommendation_id": recommendation_id, "trace": trace}


@app.get("/api/health")
async def health_check():
    """Detailed health check"""
    llm_provider = os.getenv("LLM_PROVIDER", "demo")
    llm_model = os.getenv("LLM_MODEL") or default_model(llm_provider)
    
    return {
        "status": "healthy",
        "database": "connected",
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "demo_mode": llm_provider == "demo",
        "auth_enabled": bool(os.getenv("API_KEY"))
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=8000)
