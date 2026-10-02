"""Agent orchestrator - main decision flow"""
import os
import json
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


APPROVAL_COST_THRESHOLD = 50000.0
MIN_AUTO_CONFIDENCE = 0.7


class AlreadyReviewedError(Exception):
    """Recommendation has already been (or is being) reviewed"""


class NotApprovableError(Exception):
    """Human approval cannot be applied to this recommendation"""


class PurchasingAgentOrchestrator:
    def __init__(self):
        # Determine data directory relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(current_dir, "..", "..", "data")
        self.tools = InvestigationTools(data_dir=data_dir)
        
        # Initialize LLM client
        llm_provider = os.getenv("LLM_PROVIDER", "demo")
        llm_model = os.getenv("LLM_MODEL") or None
        self.llm_client = LLMClient(provider=llm_provider, model=llm_model)
        
        self.validator = PurchaseConstraintValidator(approval_threshold=APPROVAL_COST_THRESHOLD)
    
    def review_recommendation(self, recommendation_id: str) -> Dict[str, Any]:
        """Main orchestration flow"""
        
        # Get recommendation
        rec = db.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        
        # Idempotency: only one review per recommendation, so a repeat call
        # can never create a second PO.
        if not db.claim_recommendation(recommendation_id):
            raise AlreadyReviewedError(
                f"Recommendation {recommendation_id} already reviewed (status: {rec['status']})"
            )
        
        try:
            return self._run_review(recommendation_id, rec)
        except Exception as e:
            db.update_recommendation_status(recommendation_id, "escalated")
            db.add_trace(recommendation_id, "review_failed", {"error": str(e)})
            raise
    
    def _run_review(self, recommendation_id: str, rec: Dict[str, Any]) -> Dict[str, Any]:
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
        requires_approval = (
            total_cost > APPROVAL_COST_THRESHOLD
            or decision_data['confidence'] < MIN_AUTO_CONFIDENCE
        )
        approval_reason = None
        
        if total_cost > APPROVAL_COST_THRESHOLD:
            approval_reason = f"High-value purchase: ₹{total_cost:.2f} exceeds ₹{APPROVAL_COST_THRESHOLD:,.0f} threshold"
        elif decision_data['confidence'] < MIN_AUTO_CONFIDENCE:
            approval_reason = f"Low confidence: {decision_data['confidence']} < {MIN_AUTO_CONFIDENCE}"
        
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
        final_status = "escalated"
        
        if decision.decision in [DecisionType.ACCEPT, DecisionType.MODIFY]:
            if (validation_result.all_passed
                    and not validation_result.requires_escalation
                    and not decision.requires_approval):
                purchase_order, post_validation, final_status = self._create_po(
                    recommendation_id, rec, decision, investigation, trace
                )
            
            else:
                reasons = [r for r in (
                    validation_result.escalation_reason,
                    decision.approval_reason if decision.requires_approval else None,
                    "; ".join(validation_result.failed_rules) or None,
                ) if r]
                reason = "; ".join(dict.fromkeys(reasons)) or "Approval required"
                db.add_trace(recommendation_id, "escalated", {"reason": reason})
                trace.append({
                    "step": "escalated",
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": f"Escalated to human: {reason}"
                })
                final_status = "escalated"
        
        elif decision.decision == DecisionType.REJECT:
            final_status = "rejected"
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
        
        db.update_recommendation_status(recommendation_id, final_status)
        
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
    
    def _create_po(
        self,
        recommendation_id: str,
        rec: Dict[str, Any],
        decision: AgentDecision,
        investigation: InvestigationResult,
        trace: List[Dict[str, Any]]
    ):
        """Create the PO for a validated decision. Returns (po, post_validation, final_status)."""
        final_status = "escalated"
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
        
        if purchase_order and not post_validation.escalated:
            final_status = "accepted" if decision.decision == DecisionType.ACCEPT else "modified"
            db.add_trace(recommendation_id, "po_created", {
                "po_id": purchase_order.po_id,
                "total_amount": purchase_order.total_amount
            })
            trace.append({
                "step": "po_created",
                "timestamp": datetime.utcnow().isoformat(),
                "message": f"Purchase order {purchase_order.po_id} created for ₹{purchase_order.total_amount:.2f}"
            })
        else:
            detail = "; ".join(post_validation.failures)
            db.add_trace(recommendation_id, "po_creation_escalated", {
                "po_id": purchase_order.po_id if purchase_order else None,
                "failures": post_validation.failures
            })
            trace.append({
                "step": "po_creation_failed_escalated",
                "timestamp": datetime.utcnow().isoformat(),
                "message": f"PO creation failed after retry, escalated to human: {detail}"
            })
        
        return purchase_order, post_validation, final_status
    
    def approve_recommendation(self, recommendation_id: str, approved_by: str, notes: str = "") -> Dict[str, Any]:
        """Human approval of an escalated ACCEPT/MODIFY decision.
        
        Approval only waives the approval rules (high value / low confidence).
        Hard constraints are re-validated against fresh data and still block.
        """
        rec = db.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        
        decision_row = db.get_latest_decision(recommendation_id)
        if (not decision_row
                or decision_row['decision'] not in (DecisionType.ACCEPT.value, DecisionType.MODIFY.value)):
            raise NotApprovableError("No ACCEPT/MODIFY decision to approve - reject it or create a new recommendation")
        
        if not db.claim_recommendation(recommendation_id, from_status="escalated"):
            raise AlreadyReviewedError(
                f"Recommendation {recommendation_id} is not awaiting approval (status: {rec['status']})"
            )
        
        try:
            decision = AgentDecision(
                recommendation_id=recommendation_id,
                decision=decision_row['decision'],
                final_quantity=decision_row['final_quantity'],
                final_supplier=decision_row['final_supplier'],
                reasoning=decision_row['reasoning'],
                evidence=json.loads(decision_row['evidence']),
                confidence=decision_row['confidence'],
                requires_approval=bool(decision_row['requires_approval']),
                approval_reason=decision_row['approval_reason'],
                llm_model=decision_row['llm_model'],
            )
            investigation = self._investigate(rec)
            validation_result = self._validate_decision(recommendation_id, decision, investigation)
            
            blocking = [
                key for key, result in validation_result.validations.items()
                if not result.passed and not result.warning and key != "approval_threshold"
            ]
            db.add_trace(recommendation_id, "approval_review", {
                "approved_by": approved_by, "notes": notes, "blocking_rules": blocking
            })
            
            trace: List[Dict[str, Any]] = []
            if blocking:
                db.update_recommendation_status(recommendation_id, "escalated")
                raise NotApprovableError(
                    "Hard constraints still fail, approval cannot override: "
                    + "; ".join(validation_result.failed_rules)
                )
            
            db.add_trace(recommendation_id, "approved_by_human", {
                "approved_by": approved_by, "notes": notes
            })
            purchase_order, post_validation, final_status = self._create_po(
                recommendation_id, rec, decision, investigation, trace
            )
            db.update_recommendation_status(recommendation_id, final_status)
            return {
                "recommendation_id": recommendation_id,
                "status": final_status,
                "approved_by": approved_by,
                "purchase_order": purchase_order,
                "post_validation": post_validation,
                "trace": trace,
            }
        except NotApprovableError:
            raise
        except Exception as e:
            db.update_recommendation_status(recommendation_id, "escalated")
            db.add_trace(recommendation_id, "approval_failed", {"error": str(e)})
            raise
    
    def reject_recommendation(self, recommendation_id: str, rejected_by: str, reason: str) -> Dict[str, Any]:
        """Human rejection of an escalated recommendation. No PO is created."""
        rec = db.get_recommendation(recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        if not db.claim_recommendation(recommendation_id, from_status="escalated"):
            raise AlreadyReviewedError(
                f"Recommendation {recommendation_id} is not awaiting a human decision (status: {rec['status']})"
            )
        db.add_trace(recommendation_id, "rejected_by_human", {
            "rejected_by": rejected_by, "reason": reason
        })
        db.update_recommendation_status(recommendation_id, "rejected")
        return {"recommendation_id": recommendation_id, "status": "rejected", "rejected_by": rejected_by}
    
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
        # Space already spoken for by stock on its way in (open POs + agent POs)
        inbound = sum(o.quantity for o in open_orders) + db.get_inbound_quantity(rec['node_id'], rec['product_id'])
        storage.available = max(0, storage.available - inbound)
        
        category = self.tools.get_product_category(rec['product_id'])
        budget = self.tools.get_budget_info(rec['node_id'], category)
        # Spend the agent already committed this month is not in the static budget data
        committed = db.get_committed_spend(rec['node_id'])
        if committed:
            budget.remaining = max(0.0, budget.remaining - committed)
        committed_category = db.get_committed_spend(
            rec['node_id'], self.tools.get_category_product_ids(category)
        )
        if committed_category:
            budget.product_category_budget = max(0.0, budget.product_category_budget - committed_category)
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
