"""Investigation tools for the purchasing agent"""
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.models import (
    InventoryInfo, DemandForecast, OpenPO, SupplierInfo,
    StorageInfo, BudgetInfo, SalesVelocity
)


class InvestigationTools:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._load_data()
    
    def _load_data(self):
        """Load all mock data files"""
        with open(os.path.join(self.data_dir, "inventory.json")) as f:
            self.inventory_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "demand_forecast.json")) as f:
            self.demand_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "open_pos.json")) as f:
            self.open_pos_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "suppliers.json")) as f:
            self.suppliers_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "storage.json")) as f:
            self.storage_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "budgets.json")) as f:
            self.budgets_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "sales_history.json")) as f:
            self.sales_data = json.load(f)
        
        with open(os.path.join(self.data_dir, "products.json")) as f:
            self.products_data = json.load(f)
    
    def get_current_inventory(self, node_id: str, product_id: str) -> InventoryInfo:
        """Tool 1: Get current inventory levels"""
        inventory = self.inventory_data.get(node_id, {}).get(product_id, {})
        
        if not inventory:
            # Return default if not found
            return InventoryInfo(
                current_stock=0,
                reserved_stock=0,
                available_stock=0,
                reorder_point=100,
                safety_stock=50
            )
        
        return InventoryInfo(**inventory)
    
    def get_demand_forecast(self, node_id: str, product_id: str) -> DemandForecast:
        """Tool 2: Get demand forecast"""
        forecast = self.demand_data.get(node_id, {}).get(product_id, {})
        
        if not forecast:
            # Return default if not found
            return DemandForecast(
                daily_avg=50.0,
                forecast_7d=350.0,
                forecast_14d=700.0,
                forecast_30d=1500.0
            )
        
        return DemandForecast(**forecast)
    
    def get_open_purchase_orders(self, node_id: str, product_id: str) -> List[OpenPO]:
        """Tool 3: Get open purchase orders"""
        orders = self.open_pos_data.get(node_id, [])
        
        # Filter by product
        relevant_orders = [
            OpenPO(**order) 
            for order in orders 
            if order.get('product_id') == product_id
        ]
        
        return relevant_orders
    
    def get_supplier_info(self, supplier_id: str, product_id: str) -> Optional[SupplierInfo]:
        """Tool 4: Get supplier information"""
        supplier = self.suppliers_data.get(supplier_id)
        
        if not supplier:
            return None
        
        product_info = supplier.get('products', {}).get(product_id)
        
        if not product_info:
            return None
        
        return SupplierInfo(
            supplier_id=supplier_id,
            name=supplier['name'],
            **product_info
        )
    
    def get_storage_capacity(self, node_id: str, product_id: str) -> StorageInfo:
        """Tool 5: Get storage capacity information"""
        storage = self.storage_data.get(node_id, {})
        
        if not storage:
            return StorageInfo(
                capacity=5000,
                current_usage=2000,
                available=3000,
                product_allocation=500
            )
        
        return StorageInfo(
            capacity=storage.get('capacity', 5000),
            current_usage=storage.get('current_usage', 0),
            available=storage.get('available', 5000),
            product_allocation=storage.get('allocations', {}).get(product_id, 500)
        )
    
    def get_budget_info(self, node_id: str, category: str) -> BudgetInfo:
        """Tool 6: Get budget information"""
        budget = self.budgets_data.get(node_id, {})
        
        if not budget:
            return BudgetInfo(
                node_budget=500000.0,
                spent_this_month=200000.0,
                remaining=300000.0,
                product_category_budget=50000.0
            )
        
        return BudgetInfo(
            node_budget=budget.get('node_budget', 500000.0),
            spent_this_month=budget.get('spent_this_month', 0.0),
            remaining=budget.get('remaining', 500000.0),
            product_category_budget=budget.get('categories', {}).get(category, 50000.0)
        )
    
    def get_sales_velocity(self, node_id: str, product_id: str) -> SalesVelocity:
        """Tool 7: Get sales velocity and trends"""
        velocity = self.sales_data.get(node_id, {}).get(product_id, {})
        
        if not velocity:
            return SalesVelocity(
                last_7d_daily_avg=50.0,
                last_30d_daily_avg=48.0,
                trend="stable"
            )
        
        return SalesVelocity(**velocity)
    
    def calculate_inventory_coverage(
        self, 
        current_stock: int,
        reserved_stock: int,
        daily_avg: float,
        open_orders: List[OpenPO]
    ) -> float:
        """Tool 8: Calculate days of inventory coverage"""
        if daily_avg <= 0:
            return 999.0  # Effectively infinite if no demand
        
        # Available stock
        available = current_stock - reserved_stock
        
        # Add incoming orders (within next 7 days)
        today = datetime.now()
        for order in open_orders:
            try:
                delivery_date = datetime.strptime(order.expected_delivery, "%Y-%m-%d")
                days_until_delivery = (delivery_date - today).days
                
                if 0 <= days_until_delivery <= 7:
                    # Count orders arriving soon
                    available += order.quantity
            except:
                pass
        
        # Calculate coverage
        coverage_days = available / daily_avg
        
        return round(coverage_days, 1)
    
    def get_product_category(self, product_id: str) -> str:
        """Helper: Get product category"""
        product = self.products_data.get(product_id, {})
        return product.get('category', 'general')
