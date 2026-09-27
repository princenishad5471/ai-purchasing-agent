# AI Purchasing Agent - Design Document

## Executive Summary

The AI Purchasing Agent automates the review of purchase recommendations for quick-commerce dark stores. It investigates inventory, demand, and supplier data; uses an LLM to make informed decisions; enforces deterministic business constraints; and creates purchase orders with full traceability.

## Problem Context

### Business Scenario

Quick-commerce companies operate "dark stores" (micro-fulfillment centers) that serve customers with 10-15 minute delivery times. These stores must maintain optimal inventory levels:

- **Too little stock** → Stockouts → Lost sales
- **Too much stock** → Expired products → High holding costs

### Current Process

1. Inventory management system generates purchase recommendations
2. Category managers manually review each recommendation
3. Managers check inventory, demand, supplier constraints, budget
4. Managers create purchase orders if approved
5. Process is slow, error-prone, and doesn't scale

### Solution

AI agent that automates the review process while maintaining strict business guardrails.

## Architecture

### High-Level Flow

```
Recommendation → Investigation → LLM Decision → Validation → Action → Post-Validation
```

### Components

#### 1. Investigation Tools (8 tools)

**Purpose**: Gather all relevant data before making a decision.

**Tools**:
1. `get_current_inventory()` - Current stock, reserved stock, reorder point, safety stock
2. `get_demand_forecast()` - Predicted demand for next 7/14/30 days
3. `get_open_purchase_orders()` - Orders already in-flight
4. `get_supplier_info()` - MOQ, pricing, lead time, availability
5. `get_storage_capacity()` - Space constraints per product
6. `get_budget_info()` - Available budget per category
7. `get_sales_velocity()` - Historical sales trends
8. `calculate_inventory_coverage()` - Days until stockout

**Implementation**: Python functions that read from mock JSON files (easily replaceable with real API calls).

#### 2. LLM Decision Engine

**Purpose**: Analyze investigation results and recommend action.

**Input**:
```python
{
  "recommendation": {
    "product": "Coca-Cola 500ml",
    "node": "Delhi-NCR Dark Store A",
    "quantity": 800,
    "supplier": "supplier_x"
  },
  "investigation": {
    "inventory": {...},
    "demand": {...},
    "supplier": {...},
    # ... all tool results
  }
}
```

**Output**:
```python
{
  "decision": "ACCEPT|MODIFY|REJECT|INVESTIGATE_FURTHER",
  "final_quantity": 800,
  "reasoning": "Stock level below reorder point, incoming order covers 5 days, recommended quantity appropriate for 14-day coverage...",
  "evidence": [
    "Current stock (90) below reorder point (200)",
    "Existing PO (500 units) arriving in 2 days",
    # ... supporting facts
  ],
  "confidence": 0.85
}
```

**Modes**:
- **Demo Mode**: Deterministic business logic (no API key needed)
- **LLM Mode**: OpenAI GPT-4 or Anthropic Claude with structured JSON output

**Design Decision**: Demo mode allows the system to run without API keys while demonstrating full functionality.

#### 3. Deterministic Validators

**Purpose**: Enforce hard business constraints that LLM cannot bypass.

**Critical Design Principle**: AI suggests, code enforces.

**Validators**:

```python
class PurchaseConstraintValidator:
    def validate_supplier_moq(quantity, moq):
        """Quantity must meet minimum order quantity"""
        return quantity >= moq
    
    def validate_storage_capacity(quantity, available):
        """Must fit in available storage"""
        return quantity <= available
    
    def validate_budget(cost, remaining):
        """Must be within budget"""
        return cost <= remaining
    
    # ... 7 validators total
```

**Validation Flow**:
```
LLM suggests 300 units
  ↓
Validator checks: 300 >= 500 (MOQ)?
  ↓
❌ FAIL → Override LLM decision
  ↓
Log violation → Escalate to human
  ↓
NO PO CREATED
```

**Why This Matters**: Prevents AI hallucinations from violating business rules. The LLM can suggest anything, but validators have final say.

#### 4. Purchase Order Manager

**Purpose**: Create POs and handle failures gracefully.

**Features**:
- Generates unique PO IDs
- Calculates line items and totals
- Implements retry logic with exponential backoff
- Escalates after max retries
- Post-validates creation

**Retry Flow**:
```python
try:
    create_po()
except POCreationError:
    wait(0.1s)
    retry create_po()
    if still fails:
        escalate_to_human()
```

**Simulated Failures**: Can inject failure rate for testing retry logic.

#### 5. Trace Logger

**Purpose**: Complete audit trail for compliance and debugging.

**Logged Events**:
- Investigation started
- Each tool call with results
- LLM prompt and response
- Decision made
- Validation results (pass/fail for each rule)
- PO creation attempts
- Escalations
- Final outcome

**Storage**: SQLite database with timestamps.

**Benefits**:
- Compliance: "Why was this PO created?"
- Debugging: "Why did this recommendation get rejected?"
- Analytics: "How often does the agent escalate?"

### Data Flow

```
┌─────────────────────────────────────────────────┐
│ 1. Recommendation Received                      │
│    - Product: Coca-Cola 500ml                   │
│    - Node: Delhi-NCR Dark Store A               │
│    - Quantity: 800                              │
│    - Supplier: supplier_x                       │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│ 2. Investigation (Parallel Tool Calls)          │
│    ✓ Inventory: 90 available, 200 reorder point│
│    ✓ Demand: 85/day, 595 in 7 days             │
│    ✓ Open POs: 500 units arriving in 2 days    │
│    ✓ Supplier: MOQ 500, Max 2000, Price ₹18.50 │
│    ✓ Storage: 1800 units available              │
│    ✓ Budget: ₹180,000 remaining                 │
│    ✓ Velocity: 88/day trending stable          │
│    ✓ Coverage: 7.1 days with incoming orders   │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│ 3. LLM Decision                                 │
│    Decision: ACCEPT                             │
│    Final Quantity: 800                          │
│    Reasoning: "Stock below reorder point,       │
│               incoming order covers 5 days,     │
│               800 units provides 14-day buffer" │
│    Confidence: 0.85                             │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│ 4. Deterministic Validation                     │
│    ✓ MOQ check: 800 >= 500 ✅                   │
│    ✓ Max check: 800 <= 2000 ✅                  │
│    ✓ Storage: 800 <= 1800 ✅                    │
│    ✓ Budget: ₹14,800 <= ₹180,000 ✅             │
│    ✓ Availability: 800 <= 5000 ✅               │
│    ✓ Safety stock: 1420 >= 150 ✅               │
│    ✓ Approval: ₹14,800 <= ₹50,000 ✅            │
│    Result: ALL PASSED                           │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│ 5. Create Purchase Order                        │
│    PO ID: PO-ABC12345                           │
│    Line Item: 800 × ₹18.50 = ₹14,800           │
│    Expected Delivery: 2026-09-29                │
│    Status: SUBMITTED                            │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│ 6. Post-Action Validation                       │
│    ✓ PO created ✅                              │
│    ✓ PO ID generated ✅                         │
│    ✓ Line items valid ✅                        │
│    ✓ Supplier notified ✅                       │
│    ✓ Inventory reserved ✅                      │
│    ✓ Budget allocated ✅                        │
│    Result: SUCCESS                              │
└─────────────────────────────────────────────────┘
```

## Design Decisions

### 1. Why SQLite?

**Decision**: Use SQLite instead of PostgreSQL/MySQL.

**Rationale**:
- Zero configuration (file-based)
- Perfect for demo/MVP
- Sufficient for single-instance deployment
- Easy to inspect (just open the .db file)
- Production can swap to Postgres without changing code

**Trade-off**: Not suitable for high concurrency or distributed systems.

### 2. Why Mock Data?

**Decision**: Use JSON files instead of real APIs.

**Rationale**:
- No external dependencies
- Consistent test data
- Fast execution
- Easy to modify scenarios
- Real APIs can be swapped in later (interface remains the same)

**Trade-off**: Doesn't test integration issues.

### 3. Why Demo Mode?

**Decision**: Allow running without LLM API keys.

**Rationale**:
- Demonstrates full system without requiring API keys
- Useful for testing and CI/CD
- Clearly labeled so users know it's not real LLM
- Falls back gracefully if API call fails

**Implementation**:
```python
if llm_provider == "demo":
    return deterministic_decision()
else:
    try:
        return llm_api_call()
    except:
        return deterministic_decision()  # Graceful fallback
```

### 4. Why Validators After LLM?

**Decision**: Run validators after LLM decision, not before.

**Rationale**:
- LLM sees full picture (can suggest modifications)
- Validators enforce hard constraints
- Clear separation: AI advises, code enforces
- Can log when LLM violates constraints (useful for training)

**Alternative Considered**: Run validators first, pass only valid options to LLM.
**Rejected Because**: Limits LLM's ability to reason about trade-offs.

### 5. Why Retry Logic?

**Decision**: Retry PO creation once before escalating.

**Rationale**:
- Handles transient failures (network issues, timeouts)
- Reduces false escalations
- Exponential backoff prevents thundering herd

**Trade-off**: Adds latency. Acceptable for async workflows.

### 6. Why React (not Vue/Svelte)?

**Decision**: Use React + Vite.

**Rationale**:
- Most widely known framework
- Excellent for interviews (hiring managers know React)
- Vite provides fast dev experience
- Minimal setup required

**Trade-off**: Heavier than Svelte, but more familiar.

## Data Model

### Core Entities

#### Recommendation
```python
{
    "recommendation_id": "REC-ABC123",
    "product_id": "coca-cola-500ml",
    "node_id": "delhi-ncr-dark-store-a",
    "recommended_quantity": 800,
    "recommended_supplier": "supplier_x",
    "status": "pending_review|investigating|accepted|rejected",
    "created_at": "2026-09-27T13:00:00Z"
}
```

#### Investigation
```python
{
    "inventory": {
        "current_stock": 120,
        "available_stock": 90,
        "reorder_point": 200,
        "safety_stock": 150
    },
    "demand": {
        "daily_avg": 85,
        "forecast_7d": 595
    },
    # ... all tool results
}
```

#### Decision
```python
{
    "decision": "ACCEPT",
    "final_quantity": 800,
    "reasoning": "...",
    "evidence": ["fact1", "fact2"],
    "confidence": 0.85
}
```

#### Purchase Order
```python
{
    "po_id": "PO-ABC123",
    "line_items": [
        {
            "product": "Coca-Cola 500ml",
            "quantity": 800,
            "unit_price": 18.50,
            "total": 14800.00
        }
    ],
    "total_amount": 14800.00,
    "status": "submitted"
}
```

### Database Schema

```sql
CREATE TABLE recommendations (
    recommendation_id TEXT PRIMARY KEY,
    product_id TEXT,
    node_id TEXT,
    recommended_quantity INTEGER,
    recommended_supplier TEXT,
    status TEXT,
    created_at TIMESTAMP
);

CREATE TABLE investigations (...);
CREATE TABLE decisions (...);
CREATE TABLE purchase_orders (...);
CREATE TABLE validations (...);
CREATE TABLE trace_logs (...);
```

## Test Scenarios

### Scenario 1: Accept (Happy Path)
- **Input**: 800 units of Coca-Cola for Delhi store
- **Investigation**: Stock low, demand steady, supplier available
- **Decision**: ACCEPT 800 units
- **Validation**: All pass
- **Outcome**: PO created for ₹14,800

### Scenario 2: Modify (Storage Constraint)
- **Input**: 2000 units recommended
- **Investigation**: Only 1800 units storage available
- **Decision**: MODIFY to 800 units (within allocation)
- **Validation**: All pass after modification
- **Outcome**: PO created for 800 units

### Scenario 3: Reject (Below MOQ)
- **Input**: 300 units recommended
- **Investigation**: Supplier MOQ is 500 units
- **Decision**: LLM may accept, but validator rejects
- **Validation**: MOQ check fails
- **Outcome**: No PO created, escalated

### Scenario 4: Escalate (High Value)
- **Input**: 3000 units (₹55,500)
- **Investigation**: All conditions met
- **Decision**: ACCEPT
- **Validation**: Approval threshold exceeded
- **Outcome**: Escalated for manager approval

## Failure Handling

### Failure Types

1. **Constraint Violation**: Validator fails → Override decision → Log → Escalate
2. **PO Creation Failure**: Retry once → If fails → Escalate
3. **LLM API Failure**: Fall back to demo mode → Continue
4. **Data Missing**: Return safe defaults → Log warning

### Escalation Triggers

- Constraint validation fails
- High-value purchase (>₹50,000)
- Low confidence (<0.7)
- PO creation fails after retry
- Decision is INVESTIGATE_FURTHER

### Retry Strategy

```python
max_retries = 1
backoff = 0.1  # seconds

for attempt in range(max_retries + 1):
    try:
        create_po()
        break
    except:
        if attempt < max_retries:
            time.sleep(backoff * (2 ** attempt))
        else:
            escalate()
```

## Future Enhancements

### Phase 2: Advanced Features
- Multi-product bundling
- Supplier negotiation simulation
- ML-based demand forecasting
- Real-time inventory sync

### Phase 3: Scale
- PostgreSQL for production
- Redis for caching
- Message queues for async processing
- Multi-region support

### Phase 4: Intelligence
- Fine-tune LLM on historical decisions
- A/B test agent vs human decisions
- Reinforcement learning from outcomes
- Anomaly detection

## Metrics & KPIs

### Agent Performance
- Decision accuracy (vs human baseline)
- Processing time per recommendation
- Escalation rate
- PO creation success rate

### Business Impact
- Stockout reduction
- Inventory holding cost reduction
- Purchase order cycle time
- Budget variance

## Conclusion

This architecture prioritizes:
1. **Simplicity**: Easy to understand and explain
2. **Reliability**: Deterministic guardrails prevent AI errors
3. **Traceability**: Every decision is auditable
4. **Extensibility**: Easy to add new tools, validators, or actions

The system demonstrates production-ready patterns while remaining demo-friendly and interview-appropriate.
