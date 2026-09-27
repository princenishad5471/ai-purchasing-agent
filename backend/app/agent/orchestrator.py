"""Agent orchestrator - main decision flow"""
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List
import uuid

from app.models import (
    InvestigationResult, AgentDecision, ConstraintValidationResult,
    DecisionType, ValidationResult
)
from app.agent.tools import InvestigationTools
from app.agent.llm_client import LLMClient
from app.validators.constraints import PurchaseConstraintValidator
from app.database import db


class PurchasingAgentOrchestrator:
    def __init__(self):
        # Determine data directory relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, "..", "..", "data")
        self.tools = InvestigationTools(data_dir=data_dir)
        
        # Initialize LLM client
        llm_provider = os.getenv("LLM_PROVIDER", "demo")
        llm_model = os.getenv("LLM_MODEL", "gpt-4")
        self.llm_client = LLMClient(provider=llm_provider, model=llm_model)
        
        self.validator = PurchaseConstraintValidator()
    
    def review_recommendation(self, recommendation_id: str) -> Dict[str, Any]:
        """Main orchestration flow"""
        
        # Get recommendation
        rec = db.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        
        trace = []
        
        # Step 1: Investigation
        db.add_trace(recommendation_id, "investigation_started", {"timestamp": datetime.utcnow().isoformat()})
        trace.append({
            "step": "investigation_started",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Starting investigation with 8 tools"
        })
        
        investigation = self._investigate(rec)
        db.save_investigation(recommendation_id, investigation.model_dump(mode='json'))
        
        db.add_trace(recommendation_id, "investigation_completed", {
            "tools_called": 8,
            "inventory_coverage_days": investigation.inventory_coverage_days
        })
        trace.append({
            "step": "investigation_completed",
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Investigation complete. Inventory coverage: {investigation.inventory_coverage_days} days"
        })
        
        # Step 2: LLM Decision
        db.add_trace(recommendation_id, "llm_decision_started", {})
        trace.append({
            "step": "llm_decision_started",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Requesting LLM decision"
        })
        
        decision_data = self.llm_client.make_decision(rec, investigation)
        
        # Determine if approval needed based on cost or confidence
        total_cost = decision_data['final_quantity'] * investigation.supplier_info.unit_price
        requires_approval = total_cost > 50000 or decision_data['confidence'] < 0.7
        approval_reason = None
        
        if total_cost > 50000:
            approval_reason = f"High-value purchase: ₹{total_cost:.2f} exceeds ₹50,000 threshold"
        elif decision_data['confidence'] < 0.7:
            approval_reason = f"Low confidence: {decision_data['confidence']} < 0.7"
        
        decision_data['requires_approval'] = requires_approval
        decision_data['approval_reason'] = approval_reason
        
        decision = AgentDecision(
            recommendation_id=recommendation_id,
            **decision_data
        )
        
        db.save_decision(decision.model_dump(mode='json'))
        
        db.add_trace(recommendation_id, "llm_decision_completed", {
            "decision": decision.decision.value,
            "final_quantity": decision.final_quantity,
            "confidence": decision.confidence
        })
        trace.append({
            "step": "llm_decision_completed",
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"LLM decision: {decision.decision.value} ({decision.final_quantity} units, confidence: {decision.confidence})"
        })
        
        # Step 3: Constraint Validation
        db.add_trace(recommendation_id, "validation_started", {})
        trace.append({
            "step": "validation_started",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Running deterministic constraint validation"
        })
        
        validation_result = self._validate_decision(
            recommendation_id,
            decision,
            investigation
        )
        
        db.save_validation({
            "recommendation_id": recommendation_id,
            "po_id": None,
            "validation_type": "constraint_validation",
            "validation_data": validation_result.model_dump(mode='json'),
            "all_passed": validation_result.all_passed
        })
        
        db.add_trace(recommendation_id, "validation_completed", {
            "all_passed": validation_result.all_passed,
            "failed_rules": validation_result.failed_rules
        })
        trace.append({
            "step": "validation_completed",
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Validation {'PASSED' if validation_result.all_passed else 'FAILED'}. Failed rules: {len(validation_result.failed_rules)}"
        })
        
        # Step 4: Take Action (if applicable)
        purchase_order = None
        post_validation = None
        
        if decision.decision in [DecisionType.ACCEPT, DecisionType.MODIFY]:
            if validation_result.all_passed and not validation_result.requires_escalation:
                db.add_trace(recommendation_id, "po_creation_started", {})
                trace.append({
                    "step": "po_creation_started",
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": "Creating purchase order"
                })
                
                # Import here to avoid circular dependency
                from app.actions.purchase_order import PurchaseOrderManager
                po_manager = PurchaseOrderManager()
                
                purchase_order, post_validation = po_manager.create_purchase_order(
                    recommendation_id=recommendation_id,
                    product_id=rec['product_id'],
                    product_name=rec['product_name'],
                    node_id=rec['node_id'],
                    supplier_info=investigation.supplier_info,
                    quantity=decision.final_quantity
                )
                
                if purchase_order:
                    db.add_trace(recommendation_id, "po_created", {
                        "po_id": purchase_order.po_id,
                        "total_amount": purchase_order.total_amount
                    })
                    trace.append({
                        "step": "po_created",
                        "timestamp": datetime.utcnow().isoformat(),
                        "message": f"Purchase order {purchase_order.po_id} created for ₹{purchase_order.total_amount:.2f}"
                    })
                    
                    if post_validation.escalated:
                        trace.append({
                            "step": "po_creation_failed_escalated",
                            "timestamp": datetime.utcnow().isoformat(),
                            "message": "PO creation failed after retry, escalated to human"
                        })
                else:
                    trace.append({
                        "step": "po_creation_failed",
                        "timestamp": datetime.utcnow().isoformat(),
                        "message": "PO creation failed"
                    })
            
            elif validation_result.requires_escalation:
                db.add_trace(recommendation_id, "escalated", {
                    "reason": validation_result.escalation_reason
                })
                trace.append({
                    "step": "escalated",
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": f"Escalated to human: {validation_result.escalation_reason}"
                })
        
        elif decision.decision == DecisionType.REJECT:
            db.add_trace(recommendation_id, "recommendation_rejected", {
                "reasoning": decision.reasoning
            })
            trace.append({
                "step": "recommendation_rejected",
                "timestamp": datetime.utcnow().isoformat(),
                "message": f"Recommendation rejected: {decision.reasoning}"
            })
        
        elif decision.decision == DecisionType.INVESTIGATE_FURTHER:
            db.add_trace(recommendation_id, "escalated_for_investigation", {
                "reasoning": decision.reasoning
            })
            trace.append({
                "step": "escalated_for_investigation",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Requires further human investigation"
            })
        
        # Return complete result
        return {
            "recommendation_id": recommendation_id,
            "investigation": investigation,
            "decision": decision,
            "constraint_validation": validation_result,
            "purchase_order": purchase_order,
            "post_validation": post_validation,
            "trace": trace
        }
    
    def _investigate(self, rec: Dict[str, Any]) -> InvestigationResult:
        """Run all investigation tools"""
        
        # Tool calls
        inventory = self.tools.get_current_inventory(rec['node_id'], rec['product_id'])
        demand = self.tools.get_demand_forecast(rec['node_id'], rec['product_id'])
        open_orders = self.tools.get_open_purchase_orders(rec['node_id'], rec['product_id'])
        supplier_info = self.tools.get_supplier_info(rec['recommended_supplier'], rec['product_id'])
        
        if not supplier_info:
            raise ValueError(f"Supplier {rec['recommended_supplier']} not found for product {rec['product_id']}")
        
        storage = self.tools.get_storage_capacity(rec['node_id'], rec['product_id'])
        category = self.tools.get_product_category(rec['product_id'])
        budget = self.tools.get_budget_info(rec['node_id'], category)
        sales_velocity = self.tools.get_sales_velocity(rec['node_id'], rec['product_id'])
        
        # Calculate inventory coverage
        coverage = self.tools.calculate_inventory_coverage(
            inventory.current_stock,
            inventory.reserved_stock,
            demand.daily_avg,
            open_orders
        )
        
        return InvestigationResult(
            recommendation_id=rec['recommendation_id'],
            inventory=inventory,
            demand=demand,
            open_orders=open_orders,
            supplier_info=supplier_info,
            storage=storage,
            budget=budget,
            sales_velocity=sales_velocity,
            inventory_coverage_days=coverage
        )
    
    def _validate_decision(
        self,
        recommendation_id: str,
        decision: AgentDecision,
        investigation: InvestigationResult
    ) -> ConstraintValidationResult:
        """Validate decision against business constraints"""
        
        # Calculate projected stock
        incoming = sum(order.quantity for order in investigation.open_orders)
        projected_stock = investigation.inventory.current_stock + incoming + decision.final_quantity
        
        # Run all validations
        validations = self.validator.validate_all(
            quantity=decision.final_quantity,
            supplier_info=investigation.supplier_info,
            storage_info=investigation.storage,
            budget_info=investigation.budget,
            projected_stock=projected_stock,
            safety_stock=investigation.inventory.safety_stock
        )
        
        # Check results
        all_passed = self.validator.check_all_passed(validations)
        failed_rules = self.validator.get_failed_rules(validations)
        requires_escalation = self.validator.requires_escalation(validations)
        
        escalation_reason = None
        if requires_escalation:
            escalation_reason = "; ".join(failed_rules) if failed_rules else "Approval required"
        
        return ConstraintValidationResult(
            recommendation_id=recommendation_id,
            validations=validations,
            all_passed=all_passed,
            failed_rules=failed_rules,
            requires_escalation=requires_escalation,
            escalation_reason=escalation_reason
        )
