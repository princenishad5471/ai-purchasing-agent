"""Purchase Order creation and management"""
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
import random

from app.models import (
    PurchaseOrder, POLineItem, POStatus, PostActionValidation, SupplierInfo
)
from app.database import db


class PurchaseOrderManager:
    def __init__(self, failure_rate: float = 0.0):
        """
        Args:
            failure_rate: Probability of PO creation failure (for testing)
        """
        self.failure_rate = failure_rate
    
    def create_purchase_order(
        self,
        recommendation_id: str,
        product_id: str,
        product_name: str,
        node_id: str,
        supplier_info: SupplierInfo,
        quantity: int,
        max_retries: int = 1
    ) -> Tuple[Optional[PurchaseOrder], PostActionValidation]:
        """Create a purchase order with retry logic"""
        
        retry_count = 0
        last_error = None
        
        # Build the PO once: the same po_id is reused on every retry, so a retry
        # after a partial failure can never create a second PO.
        po = self._create_po(
            recommendation_id,
            product_id,
            product_name,
            node_id,
            supplier_info,
            quantity
        )
        saved = False
        
        for attempt in range(max_retries + 1):
            try:
                # Simulate potential failure
                if random.random() < self.failure_rate:
                    raise Exception("Simulated PO creation failure")
                
                # Save to database (once)
                if not saved:
                    db.save_purchase_order(po.model_dump(mode='json'))
                    saved = True
                
                # Post-action validation
                validation = self._validate_po_creation(po)
                
                if validation.failures:
                    # A failed post-check means the PO is not safely in flight
                    validation.escalated = True
                    po.status = POStatus.FAILED
                    db.update_po_status(po.po_id, po.status.value)
                    db.add_trace(recommendation_id, "po_post_validation_failed", {
                        "po_id": po.po_id,
                        "failures": validation.failures
                    })
                
                db.save_validation({
                    "recommendation_id": recommendation_id,
                    "po_id": po.po_id,
                    "validation_type": "post_action_validation",
                    "validation_data": validation.model_dump(mode='json'),
                    "all_passed": len(validation.failures) == 0
                })
                
                # Success
                validation.retry_count = retry_count
                return po, validation
            
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                
                if attempt < max_retries:
                    # Exponential backoff
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                else:
                    # Max retries exceeded - escalate
                    if saved:
                        po.status = POStatus.FAILED
                        db.update_po_status(po.po_id, po.status.value)
                    
                    validation = PostActionValidation(
                        po_id=po.po_id if saved else "",
                        checks={
                            "po_created": False,
                            "po_id_generated": False,
                            "line_items_valid": False,
                            "supplier_notified": False,
                            "inventory_reserved": False,
                            "budget_allocated": False
                        },
                        failures=[f"PO creation failed: {last_error}"],
                        retry_count=retry_count,
                        escalated=True
                    )
                    
                    db.save_validation({
                        "recommendation_id": recommendation_id,
                        "po_id": None,
                        "validation_type": "post_action_validation",
                        "validation_data": validation.model_dump(mode='json'),
                        "all_passed": False
                    })
                    
                    db.add_trace(recommendation_id, "po_creation_failed", {
                        "error": last_error,
                        "retry_count": retry_count,
                        "escalated": True
                    })
                    
                    return None, validation
    
    def _create_po(
        self,
        recommendation_id: str,
        product_id: str,
        product_name: str,
        node_id: str,
        supplier_info: SupplierInfo,
        quantity: int
    ) -> PurchaseOrder:
        """Internal PO creation logic"""
        
        po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
        
        line_item = POLineItem(
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price=supplier_info.unit_price,
            total_price=quantity * supplier_info.unit_price
        )
        
        expected_delivery = (datetime.utcnow() + timedelta(days=supplier_info.lead_time_days)).strftime("%Y-%m-%d")
        
        po = PurchaseOrder(
            po_id=po_id,
            recommendation_id=recommendation_id,
            node_id=node_id,
            supplier_id=supplier_info.supplier_id,
            supplier_name=supplier_info.name,
            line_items=[line_item],
            total_amount=line_item.total_price,
            expected_delivery=expected_delivery,
            status=POStatus.SUBMITTED,
            created_by="agent"
        )
        
        return po
    
    def _validate_po_creation(self, po: PurchaseOrder) -> PostActionValidation:
        """Post-action validation of PO"""
        
        checks = {
            "po_created": True,
            "po_id_generated": bool(po.po_id),
            "line_items_valid": len(po.line_items) > 0 and all(
                item.quantity > 0 and item.unit_price > 0 
                for item in po.line_items
            ),
            "supplier_notified": self._mock_notify_supplier(po),
            "inventory_reserved": self._mock_reserve_inventory(po),
            "budget_allocated": self._mock_allocate_budget(po)
        }
        
        failures = [
            key for key, passed in checks.items() 
            if not passed
        ]
        
        return PostActionValidation(
            po_id=po.po_id,
            checks=checks,
            failures=failures,
            retry_count=0,
            escalated=False
        )
    
    def _mock_notify_supplier(self, po: PurchaseOrder) -> bool:
        """Mock: Notify supplier of PO"""
        # In real system, this would call supplier API
        return True
    
    def _mock_reserve_inventory(self, po: PurchaseOrder) -> bool:
        """Mock: Reserve inventory in system"""
        # In real system, this would update inventory system
        return True
    
    def _mock_allocate_budget(self, po: PurchaseOrder) -> bool:
        """Mock: Allocate budget"""
        # In real system, this would update budget tracking
        return True
