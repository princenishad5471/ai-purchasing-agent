"""Test scenarios for the AI Purchasing Agent"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.agent.tools import InvestigationTools
from app.validators.constraints import PurchaseConstraintValidator
from app.models import SupplierInfo, StorageInfo, BudgetInfo


def test_investigation_tools():
    """Test that investigation tools return correct data"""
    tools = InvestigationTools(data_dir="backend/data")
    
    # Test inventory lookup
    inventory = tools.get_current_inventory("delhi-ncr-dark-store-a", "coca-cola-500ml")
    assert inventory.current_stock == 120
    assert inventory.available_stock == 90
    assert inventory.reorder_point == 200
    
    # Test demand forecast
    demand = tools.get_demand_forecast("delhi-ncr-dark-store-a", "coca-cola-500ml")
    assert demand.daily_avg == 85
    assert demand.forecast_7d == 595
    
    # Test supplier info
    supplier = tools.get_supplier_info("supplier_x", "coca-cola-500ml")
    assert supplier is not None
    assert supplier.moq == 500
    assert supplier.unit_price == 18.50
    
    # Test open orders
    orders = tools.get_open_purchase_orders("delhi-ncr-dark-store-a", "coca-cola-500ml")
    assert len(orders) == 1
    assert orders[0].quantity == 500
    
    # Test storage
    storage = tools.get_storage_capacity("delhi-ncr-dark-store-a", "coca-cola-500ml")
    assert storage.available == 1800
    
    # Test budget
    budget = tools.get_budget_info("delhi-ncr-dark-store-a", "beverages")
    assert budget.remaining == 180000
    
    # Test inventory coverage calculation
    coverage = tools.calculate_inventory_coverage(120, 30, 85, orders)
    assert coverage > 0
    
    print("✓ All investigation tools working correctly")


def test_validators():
    """Test deterministic validators"""
    validator = PurchaseConstraintValidator()
    
    # Test MOQ validation - PASS
    result = validator.validate_supplier_moq(600, 500)
    assert result.passed is True
    
    # Test MOQ validation - FAIL
    result = validator.validate_supplier_moq(300, 500)
    assert result.passed is False
    assert result.requires_escalation is True
    
    # Test storage validation - PASS
    result = validator.validate_storage_capacity(800, 1800)
    assert result.passed is True
    
    # Test storage validation - FAIL
    result = validator.validate_storage_capacity(2000, 1800)
    assert result.passed is False
    
    # Test budget validation - PASS
    result = validator.validate_budget(10000, 180000)
    assert result.passed is True
    
    # Test budget validation - FAIL
    result = validator.validate_budget(200000, 180000)
    assert result.passed is False
    
    # Test approval threshold
    result = validator.validate_approval_threshold(45000)
    assert result.passed is True
    
    result = validator.validate_approval_threshold(55000)
    assert result.passed is False
    assert result.requires_escalation is True
    
    print("✓ All validators working correctly")


def test_scenario_1_accept():
    """Scenario 1: ACCEPT - Happy path (800 units)"""
    print("\n=== Scenario 1: ACCEPT - Happy Path ===")
    
    tools = InvestigationTools(data_dir="backend/data")
    validator = PurchaseConstraintValidator()
    
    # Investigation
    inventory = tools.get_current_inventory("delhi-ncr-dark-store-a", "coca-cola-500ml")
    supplier = tools.get_supplier_info("supplier_x", "coca-cola-500ml")
    storage = tools.get_storage_capacity("delhi-ncr-dark-store-a", "coca-cola-500ml")
    budget = tools.get_budget_info("delhi-ncr-dark-store-a", "beverages")
    
    # Proposed quantity
    quantity = 800
    projected_stock = inventory.current_stock + 500 + quantity  # 500 from open PO
    
    # Validate
    validations = validator.validate_all(
        quantity=quantity,
        supplier_info=supplier,
        storage_info=storage,
        budget_info=budget,
        projected_stock=projected_stock,
        safety_stock=inventory.safety_stock
    )
    
    all_passed = validator.check_all_passed(validations)
    
    print(f"Quantity: {quantity}")
    print(f"All validations passed: {all_passed}")
    for key, result in validations.items():
        status = "✓" if result.passed else "✗"
        print(f"  {status} {key}: {result.message}")
    
    assert all_passed is True
    print("\n✓ Scenario 1 PASSED")


def test_scenario_2_modify():
    """Scenario 2: MODIFY - Exceeds storage, modify to fit"""
    print("\n=== Scenario 2: MODIFY - Storage Constraint ===")
    
    tools = InvestigationTools(data_dir="backend/data")
    validator = PurchaseConstraintValidator()
    
    # Investigation
    inventory = tools.get_current_inventory("delhi-ncr-dark-store-a", "coca-cola-500ml")
    supplier = tools.get_supplier_info("supplier_x", "coca-cola-500ml")
    storage = tools.get_storage_capacity("delhi-ncr-dark-store-a", "coca-cola-500ml")
    budget = tools.get_budget_info("delhi-ncr-dark-store-a", "beverages")
    
    # Original recommendation exceeds storage
    original_quantity = 2000
    print(f"Original recommendation: {original_quantity} units")
    print(f"Available storage: {storage.available} units")
    
    # Validate original - should fail storage check
    validations_original = validator.validate_all(
        quantity=original_quantity,
        supplier_info=supplier,
        storage_info=storage,
        budget_info=budget,
        projected_stock=inventory.current_stock + original_quantity,
        safety_stock=inventory.safety_stock
    )
    
    storage_check = validations_original['storage_capacity']
    print(f"Original storage check: {'PASS' if storage_check.passed else 'FAIL'} - {storage_check.message}")
    assert storage_check.passed is False
    
    # Modify to fit storage
    modified_quantity = min(storage.available, storage.product_allocation)
    print(f"\nModified quantity: {modified_quantity} units")
    
    # Validate modified
    validations_modified = validator.validate_all(
        quantity=modified_quantity,
        supplier_info=supplier,
        storage_info=storage,
        budget_info=budget,
        projected_stock=inventory.current_stock + modified_quantity,
        safety_stock=inventory.safety_stock
    )
    
    all_passed = validator.check_all_passed(validations_modified)
    print(f"Modified validations passed: {all_passed}")
    
    for key, result in validations_modified.items():
        status = "✓" if result.passed else "✗"
        print(f"  {status} {key}: {result.message}")
    
    assert all_passed is True
    print("\n✓ Scenario 2 PASSED")


def test_scenario_3_reject():
    """Scenario 3: REJECT - Below MOQ"""
    print("\n=== Scenario 3: REJECT - Below MOQ ===")
    
    tools = InvestigationTools(data_dir="backend/data")
    validator = PurchaseConstraintValidator()
    
    supplier = tools.get_supplier_info("supplier_x", "coca-cola-500ml")
    
    # Quantity below MOQ
    quantity = 300
    print(f"Requested quantity: {quantity} units")
    print(f"Supplier MOQ: {supplier.moq} units")
    
    # Validate
    result = validator.validate_supplier_moq(quantity, supplier.moq)
    
    print(f"MOQ validation: {'PASS' if result.passed else 'FAIL'} - {result.message}")
    print(f"Requires escalation: {result.requires_escalation}")
    
    assert result.passed is False
    assert result.requires_escalation is True
    
    print("\n✓ Scenario 3 PASSED")


def test_scenario_4_escalate_high_value():
    """Scenario 4: ESCALATE - High value purchase"""
    print("\n=== Scenario 4: ESCALATE - High Value Purchase ===")
    
    tools = InvestigationTools(data_dir="backend/data")
    validator = PurchaseConstraintValidator(approval_threshold=50000)
    
    supplier = tools.get_supplier_info("supplier_x", "coca-cola-500ml")
    
    # High quantity = high cost
    quantity = 3000
    total_cost = quantity * supplier.unit_price
    
    print(f"Quantity: {quantity} units")
    print(f"Unit price: ₹{supplier.unit_price}")
    print(f"Total cost: ₹{total_cost:.2f}")
    print(f"Approval threshold: ₹50,000")
    
    # Validate
    result = validator.validate_approval_threshold(total_cost)
    
    print(f"Approval check: {'PASS' if result.passed else 'FAIL'} - {result.message}")
    print(f"Requires escalation: {result.requires_escalation}")
    
    assert result.passed is False
    assert result.requires_escalation is True
    
    print("\n✓ Scenario 4 PASSED")


if __name__ == "__main__":
    print("Running AI Purchasing Agent Tests\n")
    print("=" * 60)
    
    test_investigation_tools()
    test_validators()
    test_scenario_1_accept()
    test_scenario_2_modify()
    test_scenario_3_reject()
    test_scenario_4_escalate_high_value()
    
    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED")
