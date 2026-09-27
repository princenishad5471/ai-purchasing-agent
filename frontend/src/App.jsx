import React, { useState, useEffect } from 'react';
import { api } from './api';
import './App.css';

function App() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Default recommendation data
  const defaultRec = {
    product_id: 'coca-cola-500ml',
    product_name: 'Coca-Cola 500ml',
    node_id: 'delhi-ncr-dark-store-a',
    node_name: 'Delhi-NCR Dark Store A',
    recommended_quantity: 800,
    recommended_supplier: 'supplier_x',
  };

  useEffect(() => {
    api.healthCheck().then(setHealth).catch(console.error);
  }, []);

  const handleReview = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      // Create recommendation
      const rec = await api.createRecommendation(defaultRec);
      
      // Review it
      const reviewResult = await api.reviewRecommendation(rec.recommendation_id);
      setResult(reviewResult);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <h1>🤖 AI Purchasing Agent</h1>
        <p>Quick-commerce Purchase Recommendation Review</p>
        {health && (
          <div className="health-badge">
            {health.demo_mode ? '🔵 DEMO MODE' : '🟢 LLM ACTIVE'} | {health.llm_provider}
          </div>
        )}
      </header>

      <main className="main">
        <div className="demo-section">
          <h2>Demo: Review Purchase Recommendation</h2>
          <div className="recommendation-card">
            <h3>System Recommendation</h3>
            <div className="rec-details">
              <div className="detail-row">
                <span className="label">Product:</span>
                <span className="value">{defaultRec.product_name}</span>
              </div>
              <div className="detail-row">
                <span className="label">Node:</span>
                <span className="value">{defaultRec.node_name}</span>
              </div>
              <div className="detail-row">
                <span className="label">Quantity:</span>
                <span className="value">{defaultRec.recommended_quantity} units</span>
              </div>
              <div className="detail-row">
                <span className="label">Supplier:</span>
                <span className="value">{defaultRec.recommended_supplier}</span>
              </div>
            </div>
            <button 
              className="primary-button" 
              onClick={handleReview}
              disabled={loading}
            >
              {loading ? '⏳ Agent Reviewing...' : '🚀 Review with Agent'}
            </button>
          </div>
        </div>

        {error && (
          <div className="error-box">
            <h3>❌ Error</h3>
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="results">
            <Investigation data={result.investigation} />
            <Decision data={result.decision} />
            <Validation data={result.constraint_validation} />
            {result.purchase_order && <PurchaseOrder data={result.purchase_order} />}
            {result.post_validation && <PostValidation data={result.post_validation} />}
            <Trace data={result.trace} />
          </div>
        )}
      </main>
    </div>
  );
}

function Investigation({ data }) {
  return (
    <div className="section">
      <h2>📊 Investigation Results</h2>
      <div className="grid">
        <div className="card">
          <h3>Inventory</h3>
          <p>Current: {data.inventory.current_stock} units</p>
          <p>Available: {data.inventory.available_stock} units</p>
          <p>Reorder Point: {data.inventory.reorder_point} units</p>
          <p>Safety Stock: {data.inventory.safety_stock} units</p>
          <p className="highlight">Coverage: {data.inventory_coverage_days} days</p>
        </div>
        <div className="card">
          <h3>Demand Forecast</h3>
          <p>Daily Avg: {data.demand.daily_avg} units</p>
          <p>7-day: {data.demand.forecast_7d} units</p>
          <p>14-day: {data.demand.forecast_14d} units</p>
          <p>30-day: {data.demand.forecast_30d} units</p>
        </div>
        <div className="card">
          <h3>Supplier</h3>
          <p>{data.supplier_info.name}</p>
          <p>MOQ: {data.supplier_info.moq} units</p>
          <p>Max: {data.supplier_info.max_order_qty} units</p>
          <p>Available: {data.supplier_info.available_quantity} units</p>
          <p>Price: ₹{data.supplier_info.unit_price}</p>
          <p>Lead Time: {data.supplier_info.lead_time_days} days</p>
        </div>
        <div className="card">
          <h3>Storage & Budget</h3>
          <p>Storage Available: {data.storage.available} units</p>
          <p>Allocation: {data.storage.product_allocation} units</p>
          <p>Budget Remaining: ₹{data.budget.remaining.toLocaleString()}</p>
          <p>Category Budget: ₹{data.budget.product_category_budget.toLocaleString()}</p>
        </div>
      </div>
      {data.open_orders.length > 0 && (
        <div className="card">
          <h3>Open Purchase Orders</h3>
          {data.open_orders.map((order, i) => (
            <p key={i}>
              {order.po_id}: {order.quantity} units, arriving {order.expected_delivery} ({order.status})
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function Decision({ data }) {
  const decisionColor = {
    ACCEPT: '#10b981',
    MODIFY: '#f59e0b',
    REJECT: '#ef4444',
    INVESTIGATE_FURTHER: '#6366f1',
  };

  return (
    <div className="section">
      <h2>🧠 Agent Decision</h2>
      <div className="decision-card" style={{ borderLeftColor: decisionColor[data.decision] }}>
        <div className="decision-header">
          <h3 style={{ color: decisionColor[data.decision] }}>{data.decision}</h3>
          <span className="confidence">Confidence: {(data.confidence * 100).toFixed(0)}%</span>
        </div>
        <p><strong>Final Quantity:</strong> {data.final_quantity} units</p>
        <p><strong>Supplier:</strong> {data.final_supplier}</p>
        <p><strong>Reasoning:</strong> {data.reasoning}</p>
        
        <div className="evidence">
          <h4>Evidence:</h4>
          <ul>
            {data.evidence.map((ev, i) => (
              <li key={i}>{ev}</li>
            ))}
          </ul>
        </div>

        {data.requires_approval && (
          <div className="approval-required">
            ⚠️ <strong>Approval Required:</strong> {data.approval_reason}
          </div>
        )}

        <p className="llm-model">Model: {data.llm_model}</p>
      </div>
    </div>
  );
}

function Validation({ data }) {
  return (
    <div className="section">
      <h2>✅ Constraint Validation</h2>
      <div className={`validation-summary ${data.all_passed ? 'passed' : 'failed'}`}>
        {data.all_passed ? '✅ All Validations Passed' : '❌ Validation Failed'}
      </div>
      <div className="validation-checks">
        {Object.entries(data.validations).map(([key, result]) => (
          <div key={key} className={`check-item ${result.passed ? 'pass' : 'fail'}`}>
            <span className="check-icon">{result.passed ? '✓' : '✗'}</span>
            <div className="check-details">
              <div className="check-name">{key}</div>
              <div className="check-message">{result.message}</div>
            </div>
          </div>
        ))}
      </div>
      {data.requires_escalation && (
        <div className="escalation-notice">
          🚨 <strong>Escalation Required:</strong> {data.escalation_reason}
        </div>
      )}
    </div>
  );
}

function PurchaseOrder({ data }) {
  return (
    <div className="section">
      <h2>📄 Purchase Order Created</h2>
      <div className="po-card">
        <h3>{data.po_id}</h3>
        <p><strong>Supplier:</strong> {data.supplier_name}</p>
        <p><strong>Node:</strong> {data.node_id}</p>
        <p><strong>Expected Delivery:</strong> {data.expected_delivery}</p>
        <p><strong>Status:</strong> <span className="status">{data.status}</span></p>
        
        <div className="line-items">
          <h4>Line Items:</h4>
          {data.line_items.map((item, i) => (
            <div key={i} className="line-item">
              <span>{item.product_name}</span>
              <span>{item.quantity} × ₹{item.unit_price} = ₹{item.total_price.toFixed(2)}</span>
            </div>
          ))}
        </div>
        
        <div className="total">
          <strong>Total Amount:</strong> ₹{data.total_amount.toFixed(2)}
        </div>
      </div>
    </div>
  );
}

function PostValidation({ data }) {
  return (
    <div className="section">
      <h2>✔️ Post-Action Validation</h2>
      <div className="post-validation">
        {Object.entries(data.checks).map(([key, passed]) => (
          <div key={key} className={`check-item ${passed ? 'pass' : 'fail'}`}>
            <span className="check-icon">{passed ? '✓' : '✗'}</span>
            <span>{key}</span>
          </div>
        ))}
        {data.retry_count > 0 && (
          <p className="retry-info">Retries: {data.retry_count}</p>
        )}
        {data.escalated && (
          <div className="escalation-notice">
            🚨 <strong>Escalated to human after retry failure</strong>
          </div>
        )}
      </div>
    </div>
  );
}

function Trace({ data }) {
  return (
    <div className="section">
      <h2>📋 Decision Trace</h2>
      <div className="trace-timeline">
        {data.map((entry, i) => (
          <div key={i} className="trace-entry">
            <div className="trace-time">{entry.timestamp}</div>
            <div className="trace-step">{entry.step}</div>
            <div className="trace-message">{entry.message}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
