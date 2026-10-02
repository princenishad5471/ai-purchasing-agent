"""FastAPI main application"""
import os
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.models import (
    PurchaseRecommendation, ReviewRequest, ReviewResponse,
    RecommendationStatus
)
from app.database import db
from app.agent.orchestrator import PurchasingAgentOrchestrator, AlreadyReviewedError
from app.agent.tools import DataNotFoundError

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="AI Purchasing Agent",
    description="Quick-commerce purchase recommendation review agent",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize orchestrator
orchestrator = PurchasingAgentOrchestrator()


# Request models
class CreateRecommendationRequest(BaseModel):
    product_id: str
    product_name: str
    node_id: str
    node_name: str
    recommended_quantity: int
    recommended_supplier: str


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "ok",
        "service": "AI Purchasing Agent",
        "version": "1.0.0"
    }


@app.post("/api/recommendations", response_model=PurchaseRecommendation)
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


@app.post("/api/recommendations/{recommendation_id}/review")
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.get("/api/recommendations/{recommendation_id}/trace")
async def get_trace(recommendation_id: str):
    """Get decision trace for a recommendation"""
    trace = db.get_trace(recommendation_id)
    return {"recommendation_id": recommendation_id, "trace": trace}


@app.get("/api/health")
async def health_check():
    """Detailed health check"""
    llm_provider = os.getenv("LLM_PROVIDER", "demo")
    llm_model = os.getenv("LLM_MODEL", "gpt-4")
    
    return {
        "status": "healthy",
        "database": "connected",
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "demo_mode": llm_provider == "demo"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
