"""Deterministic business constraint validators"""
from typing import Dict, List
from app.models import ValidationResult, SupplierInfo, StorageInfo, BudgetInfo


class PurchaseConstraintValidator:
    """Hard business rules that LLM cannot bypass"""
    
    def __init__(self, approval_threshold: float = 50000.0):
        self.approval_threshold = approval_threshold
    
    def validate_supplier_moq(self, quantity: int, moq: int) -> ValidationResult:
        """Quantity must meet supplier minimum order quantity"""
        passed = quantity >= moq
        
        return ValidationResult(
            passed=passed,
            rule="supplier_moq",
            message=f"Quantity {quantity} {'meets' if passed else 'below'} MOQ {moq}",
            value=quantity,
            threshold=moq,
            requires_escalation=not passed
        )
    
    def validate_supplier_max_qty(self, quantity: int, max_qty: int) -> ValidationResult:
        """Quantity cannot exceed supplier max order limit"""
        passed = quantity <= max_qty
        
        return ValidationResult(
            passed=passed,
            rule="supplier_max_qty",
            message=f"Quantity {quantity} {'within' if passed else 'exceeds'} max limit {max_qty}",
            value=quantity,
            threshold=max_qty,
            requires_escalation=not passed
        )
    
    def validate_storage_capacity(self, quantity: int, available_space: int) -> ValidationResult:
        """Ordered quantity must fit in available storage"""
        passed = quantity <= available_space
        
        return ValidationResult(
            passed=passed,
            rule="storage_capacity",
            message=f"Storage: need {quantity}, available {available_space} - {'OK' if passed else 'INSUFFICIENT'}",
            value=quantity,
            threshold=available_space,
            requires_escalation=not passed
        )
    
    def validate_budget(self, total_cost: float, available_budget: float) -> ValidationResult:
        """Total cost must be within available budget"""
        passed = total_cost <= available_budget
        
        return ValidationResult(
            passed=passed,
            rule="budget_limit",
            message=f"Cost ₹{total_cost:.2f} {'within' if passed else 'exceeds'} budget ₹{available_budget:.2f}",
            value=total_cost,
            threshold=available_budget,
            requires_escalation=not passed
        )
    
    def validate_category_budget(self, total_cost: float, category_budget: float) -> ValidationResult:
        """Cost must fit the remaining budget for the product category"""
        passed = total_cost <= category_budget
        
        return ValidationResult(
            passed=passed,
            rule="category_budget",
            message=f"Cost ₹{total_cost:.2f} {'within' if passed else 'exceeds'} category budget ₹{category_budget:.2f}",
            value=total_cost,
            threshold=category_budget,
            requires_escalation=not passed
        )
    
    def validate_product_allocation(self, quantity: int, allocation: int) -> ValidationResult:
        """Quantity cannot exceed the storage allocated to this product"""
        passed = quantity <= allocation
        
        return ValidationResult(
            passed=passed,
            rule="product_allocation",
            message=f"Quantity {quantity} {'within' if passed else 'exceeds'} product storage allocation {allocation}",
            value=quantity,
            threshold=allocation,
            requires_escalation=not passed
        )
    
    def validate_supplier_availability(self, requested: int, available: int) -> ValidationResult:
        """Supplier must have sufficient stock"""
        passed = requested <= available
        
        return ValidationResult(
            passed=passed,
            rule="supplier_availability",
            message=f"Supplier has {available} units, requested {requested} - {'OK' if passed else 'INSUFFICIENT'}",
            value=requested,
            threshold=available,
            requires_escalation=not passed
        )
    
    def validate_safety_stock(self, projected_stock: int, safety_stock: int) -> ValidationResult:
        """Inventory after order should maintain safety stock (warning only)"""
        passed = projected_stock >= safety_stock
        
        return ValidationResult(
            passed=passed,
            rule="safety_stock",
            message=f"Projected stock {projected_stock} {'meets' if passed else 'below'} safety stock {safety_stock}",
            value=projected_stock,
            threshold=safety_stock,
            warning=True,  # Warning, not hard block
            requires_escalation=False
        )
    
    def validate_approval_threshold(self, total_cost: float) -> ValidationResult:
        """High-value purchases require human approval"""
        passed = total_cost <= self.approval_threshold
        
        return ValidationResult(
            passed=passed,
            rule="approval_required",
            message=f"Cost ₹{total_cost:.2f} {'within' if passed else 'exceeds'} approval threshold ₹{self.approval_threshold:.2f}",
            value=total_cost,
            threshold=self.approval_threshold,
            requires_escalation=not passed
        )
    
    def validate_all(
        self,
        quantity: int,
        supplier_info: SupplierInfo,
        storage_info: StorageInfo,
        budget_info: BudgetInfo,
        projected_stock: int,
        safety_stock: int
    ) -> Dict[str, ValidationResult]:
        """Run all validations"""
        total_cost = quantity * supplier_info.unit_price
        
        validations = {
            "supplier_moq_met": self.validate_supplier_moq(quantity, supplier_info.moq),
            "supplier_max_qty": self.validate_supplier_max_qty(quantity, supplier_info.max_order_qty),
            "storage_capacity": self.validate_storage_capacity(quantity, storage_info.available),
            "product_allocation": self.validate_product_allocation(quantity, storage_info.product_allocation),
            "budget_available": self.validate_budget(total_cost, budget_info.remaining),
            "category_budget": self.validate_category_budget(total_cost, budget_info.product_category_budget),
            "supplier_availability": self.validate_supplier_availability(quantity, supplier_info.available_quantity),
            "safety_stock": self.validate_safety_stock(projected_stock, safety_stock),
            "approval_threshold": self.validate_approval_threshold(total_cost)
        }
        
        return validations
    
    def check_all_passed(self, validations: Dict[str, ValidationResult]) -> bool:
        """Check if all critical validations passed (warnings don't count as failures)"""
        for key, result in validations.items():
            if not result.passed and not result.warning:
                return False
        return True
    
    def get_failed_rules(self, validations: Dict[str, ValidationResult]) -> List[str]:
        """Get list of failed validation rules"""
        failed = []
        for key, result in validations.items():
            if not result.passed and not result.warning:
                failed.append(f"{key}: {result.message}")
        return failed
    
    def requires_escalation(self, validations: Dict[str, ValidationResult]) -> bool:
        """Check if any validation requires escalation"""
        for result in validations.values():
            if result.requires_escalation:
                return True
        return False
