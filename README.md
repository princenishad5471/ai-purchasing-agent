# AI Purchasing Agent

A full-stack AI agent for quick-commerce inventory replenishment. Reviews purchase recommendations, investigates using multiple data sources, makes intelligent decisions with deterministic business constraint validation, and takes appropriate actions.

## 🎯 Problem Statement

Quick-commerce dark stores receive automated purchase recommendations from inventory management systems. These recommendations need human review to ensure they align with:
- Current inventory levels and demand forecasts
- Supplier constraints (MOQ, availability, lead times)
- Storage capacity and budget limits
- Business rules and approval thresholds

This AI agent automates the review process while maintaining strict deterministic guardrails that the LLM cannot bypass.

## 🏗️ Architecture

```
┌─────────────┐
│   React UI  │  ← Buyer-facing dashboard
└──────┬──────┘
       │ REST API
       ▼
┌──────────────────────────────────────┐
│     FastAPI Backend                  │
│                                      │
│  ┌────────────────────────────────┐ │
│  │  Purchasing Agent Orchestrator │ │
│  │  - Investigation (8 tools)     │ │
│  │  - LLM decision                │ │
│  │  - Constraint validation       │ │
│  │  - PO creation                 │ │
│  │  - Post-validation             │ │
│  └────────────────────────────────┘ │
│                                      │
│  ┌────────────────────────────────┐ │
│  │  Deterministic Validators      │ │
│  │  - MOQ, storage, budget        │ │
│  │  - Cannot be bypassed by LLM   │ │
│  └────────────────────────────────┘ │
└───────────┬──────────────────────────┘
            │
            ▼
     ┌─────────────┐
     │   SQLite    │  ← Auditable trace
     └─────────────┘
```

### Key Design Principles

1. **Investigation First**: Agent always calls 8 tools before deciding
2. **LLM as Advisor**: Makes recommendations based on evidence
3. **Validators as Gatekeepers**: Hard business rules enforced in code
4. **Traceability**: Every step logged to database
5. **Failure Handling**: Retry logic with escalation

## 🚀 Setup

### Prerequisites
- Python 3.9+
- Node.js 18+
- Optional: OpenAI or Anthropic API key (works in demo mode without)

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Set up environment (optional - works without API keys)
cp ../.env.example .env
# Edit .env to add API keys if you have them

# Run backend
cd app
python main.py
```

Backend will start on `http://localhost:8000`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run frontend
npm run dev
```

Frontend will start on `http://localhost:3000`

## 🎮 How to Use

### Quick Demo

1. Start backend: `cd backend/app && python main.py`
2. Start frontend: `cd frontend && npm run dev`
3. Open `http://localhost:3000`
4. Click "Review with Agent" button
5. Watch the agent investigate, decide, validate, and create a PO

### Default Test Case

**Product**: Coca-Cola 500ml
**Node**: Delhi-NCR Dark Store A
**Recommendation**: 800 units from Supplier X

The agent will:
- ✅ Check current inventory (90 units available, below reorder point of 200)
- ✅ Review demand forecast (85 units/day, 595 units needed in 7 days)
- ✅ Analyze open orders (500 units arriving in 2 days)
- ✅ Verify supplier constraints (MOQ 500, Max 2000, has 5000 available)
- ✅ Check storage (1800 units available)
- ✅ Validate budget (₹180,000 remaining, cost ₹14,800)
- ✅ Make decision (likely ACCEPT 800 units)
- ✅ Run constraint validation (all pass)
- ✅ Create purchase order
- ✅ Post-validate creation

## 🔒 Deterministic Guardrails

The agent **cannot** bypass these business rules:

| Constraint | Rule | Action if Violated |
|------------|------|-------------------|
| **Supplier MOQ** | Quantity >= MOQ | Reject + Escalate |
| **Supplier Max** | Quantity <= Max | Reject + Escalate |
| **Storage Capacity** | Quantity <= Available Space | Reject + Escalate |
| **Budget Limit** | Cost <= Remaining Budget | Reject + Escalate |
| **Supplier Availability** | Quantity <= Supplier Stock | Reject + Escalate |
| **Safety Stock** | Projected Stock >= Safety Stock | Warning only |
| **Approval Threshold** | Cost <= ₹50,000 | Escalate for approval |

### Validation Flow

```
LLM Decision → Validators Run → Override if Failed → Log Violation → Escalate
```

**Example**: LLM suggests 300 units, but supplier MOQ is 500 → Validator **rejects** → No PO created → Human notified

## 🤖 How the Agent Works

### 1. Investigation Phase

Calls 8 tools in parallel:
- `get_current_inventory()` - Stock levels, reorder point, safety stock
- `get_demand_forecast()` - 7/14/30 day forecasts
- `get_open_purchase_orders()` - Incoming inventory
- `get_supplier_info()` - MOQ, pricing, lead times, availability
- `get_storage_capacity()` - Space constraints
- `get_budget_info()` - Available budget
- `get_sales_velocity()` - Trends
- `calculate_inventory_coverage()` - Days until stockout

### 2. Decision Phase

**Demo Mode** (no API key):
- Uses deterministic business logic
- Clearly labeled as "DEMO MODE"
- Still demonstrates full flow

**LLM Mode** (with API key):
- Sends investigation results to OpenAI/Anthropic
- Receives structured JSON decision:
  ```json
  {
    "decision": "ACCEPT|MODIFY|REJECT|INVESTIGATE_FURTHER",
    "final_quantity": 800,
    "reasoning": "...",
    "evidence": ["fact1", "fact2"],
    "confidence": 0.85
  }
  ```

### 3. Validation Phase

Runs 7 deterministic checks:
```python
✓ supplier_moq_met: 800 >= 500
✓ supplier_max_qty: 800 <= 2000
✓ storage_capacity: 800 <= 1800
✓ budget_available: ₹14,800 <= ₹180,000
✓ supplier_availability: 800 <= 5000
✓ safety_stock: 1420 >= 150
✓ approval_threshold: ₹14,800 <= ₹50,000
```

**All must pass** (except warnings) or decision is overridden.

### 4. Action Phase

If validation passes:
- `create_purchase_order()` with retry logic
- Generates unique PO ID
- Calculates line items and totals
- Saves to database
- Mock notifications (supplier, inventory system, budget)

### 5. Post-Validation

Verifies PO creation:
```python
✓ po_created
✓ po_id_generated
✓ line_items_valid
✓ supplier_notified
✓ inventory_reserved
✓ budget_allocated
```

If any check fails → Retry once → Escalate to human

### 6. Escalation

Agent escalates when:
- Constraint validation fails
- High-value purchase (>₹50,000)
- Low confidence (<0.7)
- PO creation fails after retry
- Decision is INVESTIGATE_FURTHER

## 🧪 Testing

### Run Test Scenarios

```bash
cd tests
python test_scenarios.py
```

### Test Cases

| Scenario | Input | Expected Outcome |
|----------|-------|------------------|
| **1. Accept** | 800 units, all conditions favorable | ✅ ACCEPT → PO created |
| **2. Modify** | 2000 units, exceeds storage (1800) | ⚠️ MODIFY to 800 → PO created |
| **3. Reject** | 300 units, below MOQ (500) | ❌ REJECT → No PO |
| **4. Escalate** | 3000 units, cost ₹55,500 (>₹50K) | 🔼 ESCALATE for approval |

### Data Consistency

Test data is internally consistent:
- Current inventory: 120 units (90 available)
- Reorder point: 200 units → **Reorder needed**
- Open PO: 500 units arriving in 2 days
- Daily demand: 85 units
- Projected stock after 800-unit order: 1420 units ✅ Above safety stock (150)

## 📊 Evaluation

The system demonstrates:

1. ✅ **Multi-tool investigation** (8 tools called per review)
2. ✅ **AI decision-making** (with structured reasoning)
3. ✅ **Deterministic validation** (LLM cannot bypass)
4. ✅ **Appropriate actions** (PO creation with retry)
5. ✅ **Post-action validation** (6 checks)
6. ✅ **Failure handling** (retry → escalate)
7. ✅ **Complete traceability** (every step logged)
8. ✅ **Clean UI** (investigation → decision → validation → PO → trace)
9. ✅ **Automated tests** (4 scenarios pass)

## 🗂️ Project Structure

```
ai-purchasing-agent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── models.py            # Pydantic models
│   │   ├── database.py          # SQLite
│   │   ├── agent/
│   │   │   ├── orchestrator.py # Main agent logic
│   │   │   ├── tools.py        # Investigation tools
│   │   │   └── llm_client.py   # LLM with demo fallback
│   │   ├── validators/
│   │   │   └── constraints.py  # Business rules
│   │   └── actions/
│   │       └── purchase_order.py # PO creation
│   └── data/                    # Mock JSON data
├── frontend/
│   └── src/
│       ├── App.jsx              # Main UI
│       └── api.js               # API client
├── tests/
│   └── test_scenarios.py        # Test cases
└── docs/
    └── DESIGN.md                # Architecture
```

## 🔐 Environment Variables

```bash
# Optional - application works without these
LLM_PROVIDER=openai  # openai | anthropic | demo
LLM_MODEL=gpt-4
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Database (default: sqlite:///./purchasing_agent.db)
DATABASE_URL=sqlite:///./purchasing_agent.db

# Debug mode
DEBUG=true
```

## ⚡ Demo Mode

When no API keys are configured:
- Agent uses deterministic business logic
- All flows work end-to-end
- Clearly labeled as "DEMO MODE" in UI
- Perfect for testing and demonstration

## 🚨 Limitations & Future Improvements

### Current Limitations
- Mock data only (no real supplier APIs)
- Single product type per recommendation
- No user authentication
- No real-time inventory updates
- Limited to one fulfillment network

### Future Improvements
1. **Real Integrations**: Connect to actual supplier, inventory, and budget systems
2. **Multi-Product Orders**: Bundle multiple products in one PO
3. **Advanced Forecasting**: ML-based demand prediction
4. **Approval Workflow**: Manager dashboard for approvals
5. **Performance Metrics**: Track agent accuracy, cost savings, stockout prevention
6. **A/B Testing**: Compare agent vs human decisions
7. **Batch Processing**: Review multiple recommendations in one session
8. **Alert System**: Proactive notifications for critical inventory levels

## 📝 API Reference

### Create Recommendation
```http
POST /api/recommendations
Content-Type: application/json

{
  "product_id": "coca-cola-500ml",
  "product_name": "Coca-Cola 500ml",
  "node_id": "delhi-ncr-dark-store-a",
  "node_name": "Delhi-NCR Dark Store A",
  "recommended_quantity": 800,
  "recommended_supplier": "supplier_x"
}
```

### Review Recommendation
```http
POST /api/recommendations/{recommendation_id}/review
```

Returns:
```json
{
  "recommendation_id": "REC-ABC123",
  "investigation": {...},
  "decision": {...},
  "constraint_validation": {...},
  "purchase_order": {...},
  "post_validation": {...},
  "trace": [...]
}
```

### Get Trace
```http
GET /api/recommendations/{recommendation_id}/trace
```

### Health Check
```http
GET /api/health
```

## 🛠️ Development

### Add New Validator

1. Edit `backend/app/validators/constraints.py`
2. Add method to `PurchaseConstraintValidator`
3. Return `ValidationResult` object
4. Add to `validate_all()` method

### Add New Investigation Tool

1. Edit `backend/app/agent/tools.py`
2. Add method to `InvestigationTools`
3. Load necessary mock data
4. Call from orchestrator

### Modify Mock Data

Edit JSON files in `backend/data/`:
- Keep data internally consistent
- Update related files together
- Test after changes

## 📄 License

This project is for demonstration purposes.

## 👥 Authors

Built as an interview assignment for an AI Purchasing Agent role.

---

**Built with**: Python, FastAPI, React, SQLite, OpenAI/Anthropic APIs (optional)
