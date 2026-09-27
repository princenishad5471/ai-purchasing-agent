"""LLM client for agent decision-making"""
import os
import json
from typing import Dict, Any, Optional
from app.models import DecisionType, InvestigationResult


class LLMClient:
    def __init__(self, provider: str = "demo", model: str = "gpt-4"):
        self.provider = provider
        self.model = model
        
        if provider == "openai":
            try:
                import openai
                self.openai = openai
                self.openai.api_key = os.getenv("OPENAI_API_KEY")
            except ImportError:
                print("Warning: openai not installed, falling back to demo mode")
                self.provider = "demo"
        
        elif provider == "anthropic":
            try:
                import anthropic
                self.anthropic = anthropic
                self.anthropic_client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY")
                )
            except ImportError:
                print("Warning: anthropic not installed, falling back to demo mode")
                self.provider = "demo"
    
    def make_decision(
        self,
        recommendation: Dict[str, Any],
        investigation: InvestigationResult
    ) -> Dict[str, Any]:
        """Make purchasing decision based on investigation"""
        
        if self.provider == "demo":
            return self._demo_decision(recommendation, investigation)
        
        elif self.provider == "openai":
            return self._openai_decision(recommendation, investigation)
        
        elif self.provider == "anthropic":
            return self._anthropic_decision(recommendation, investigation)
        
        else:
            return self._demo_decision(recommendation, investigation)
    
    def _demo_decision(
        self,
        recommendation: Dict[str, Any],
        investigation: InvestigationResult
    ) -> Dict[str, Any]:
        """Deterministic demo mode decision (clearly marked)"""
        
        rec_qty = recommendation['recommended_quantity']
        inventory = investigation.inventory
        demand = investigation.demand
        storage = investigation.storage
        supplier = investigation.supplier_info
        open_orders = investigation.open_orders
        
        # Calculate projected stock
        incoming_qty = sum(order.quantity for order in open_orders)
        projected_stock = inventory.current_stock + incoming_qty + rec_qty
        
        # Decision logic
        decision = DecisionType.ACCEPT
        final_quantity = rec_qty
        reasoning_parts = []
        evidence = []
        
        # Evidence gathering
        evidence.append(f"Current stock: {inventory.current_stock} units (available: {inventory.available_stock})")
        evidence.append(f"Reorder point: {inventory.reorder_point}, Safety stock: {inventory.safety_stock}")
        evidence.append(f"Daily demand: {demand.daily_avg} units, 7-day forecast: {demand.forecast_7d} units")
        evidence.append(f"Inventory coverage: {investigation.inventory_coverage_days} days")
        
        if open_orders:
            evidence.append(f"Open orders: {len(open_orders)} order(s) totaling {incoming_qty} units")
        else:
            evidence.append("No open orders in transit")
        
        evidence.append(f"Supplier: {supplier.name} (MOQ: {supplier.moq}, Max: {supplier.max_order_qty}, Price: ₹{supplier.unit_price})")
        evidence.append(f"Storage available: {storage.available} units (product allocation: {storage.product_allocation})")
        evidence.append(f"Budget remaining: ₹{investigation.budget.remaining}")
        
        # Decision logic
        if inventory.available_stock < inventory.reorder_point:
            reasoning_parts.append(f"Stock level ({inventory.available_stock}) is below reorder point ({inventory.reorder_point})")
        
        if investigation.inventory_coverage_days < 7:
            reasoning_parts.append(f"Low inventory coverage: {investigation.inventory_coverage_days} days (target: 7+ days)")
        
        # Check if recommendation exceeds storage
        if rec_qty > storage.available:
            decision = DecisionType.MODIFY
            final_quantity = min(storage.available, storage.product_allocation)
            reasoning_parts.append(f"Recommended quantity ({rec_qty}) exceeds available storage ({storage.available})")
            reasoning_parts.append(f"Modified to {final_quantity} units to fit storage constraints")
        
        # Check if we're over-ordering given incoming stock
        if incoming_qty > 0:
            days_covered_with_incoming = (inventory.available_stock + incoming_qty) / demand.daily_avg
            if days_covered_with_incoming > 10:
                decision = DecisionType.INVESTIGATE_FURTHER
                reasoning_parts.append(f"Existing open orders provide {days_covered_with_incoming:.1f} days of coverage")
                reasoning_parts.append("High overstocking risk - recommend human review")
        
        # Check if quantity meets MOQ
        if final_quantity < supplier.moq:
            if rec_qty < supplier.moq:
                decision = DecisionType.REJECT
                reasoning_parts.append(f"Recommended quantity ({rec_qty}) below supplier MOQ ({supplier.moq})")
        
        # Build reasoning
        if decision == DecisionType.ACCEPT:
            reasoning_parts.append(f"Recommendation of {rec_qty} units is appropriate to maintain inventory levels")
            reasoning_parts.append(f"Projected stock after order: {projected_stock} units (above safety stock: {inventory.safety_stock})")
        
        reasoning = ". ".join(reasoning_parts) + "."
        
        # Confidence calculation
        confidence = 0.85
        if decision == DecisionType.MODIFY:
            confidence = 0.75
        elif decision == DecisionType.INVESTIGATE_FURTHER:
            confidence = 0.60
        elif decision == DecisionType.REJECT:
            confidence = 0.90
        
        return {
            "decision": decision.value,
            "final_quantity": final_quantity,
            "final_supplier": recommendation['recommended_supplier'],
            "reasoning": reasoning,
            "evidence": evidence,
            "confidence": confidence,
            "llm_model": "demo_mode",
            "llm_prompt": "DEMO MODE: Decision made using deterministic business logic (no LLM API called)",
            "llm_response": None
        }
    
    def _build_prompt(
        self,
        recommendation: Dict[str, Any],
        investigation: InvestigationResult
    ) -> str:
        """Build prompt for LLM"""
        
        prompt = f"""You are a purchasing analyst for a quick-commerce dark store. Review this purchase recommendation and make a decision.

RECOMMENDATION:
- Product: {recommendation['product_name']}
- Node: {recommendation['node_name']}
- Recommended Quantity: {recommendation['recommended_quantity']} units
- Supplier: {recommendation['recommended_supplier']}

INVESTIGATION RESULTS:

Current Inventory:
- Current stock: {investigation.inventory.current_stock} units
- Available stock: {investigation.inventory.available_stock} units
- Reorder point: {investigation.inventory.reorder_point} units
- Safety stock: {investigation.inventory.safety_stock} units

Demand Forecast:
- Daily average: {investigation.demand.daily_avg} units
- 7-day forecast: {investigation.demand.forecast_7d} units
- 14-day forecast: {investigation.demand.forecast_14d} units
- Inventory coverage: {investigation.inventory_coverage_days} days

Open Purchase Orders:
{self._format_open_orders(investigation.open_orders)}

Supplier Information:
- Name: {investigation.supplier_info.name}
- MOQ: {investigation.supplier_info.moq} units
- Max order quantity: {investigation.supplier_info.max_order_qty} units
- Lead time: {investigation.supplier_info.lead_time_days} days
- Available quantity: {investigation.supplier_info.available_quantity} units
- Unit price: ₹{investigation.supplier_info.unit_price}
- Reliability score: {investigation.supplier_info.reliability_score}

Storage:
- Capacity: {investigation.storage.capacity} units
- Available: {investigation.storage.available} units
- Product allocation: {investigation.storage.product_allocation} units

Budget:
- Remaining: ₹{investigation.budget.remaining}
- Category budget: ₹{investigation.budget.product_category_budget}

Sales Velocity:
- Last 7 days: {investigation.sales_velocity.last_7d_daily_avg} units/day
- Last 30 days: {investigation.sales_velocity.last_30d_daily_avg} units/day
- Trend: {investigation.sales_velocity.trend}

INSTRUCTIONS:
Decide: ACCEPT, MODIFY, REJECT, or INVESTIGATE_FURTHER

If MODIFY, provide the final quantity.
Provide detailed reasoning with specific evidence from the investigation.
Rate your confidence (0.0 to 1.0).

Respond in JSON format:
{{
    "decision": "ACCEPT|MODIFY|REJECT|INVESTIGATE_FURTHER",
    "final_quantity": <number>,
    "reasoning": "<detailed reasoning>",
    "evidence": ["<fact1>", "<fact2>", ...],
    "confidence": <0.0-1.0>
}}
"""
        return prompt
    
    def _format_open_orders(self, orders) -> str:
        """Format open orders for prompt"""
        if not orders:
            return "- No open orders"
        
        lines = []
        for order in orders:
            lines.append(f"- PO {order.po_id}: {order.quantity} units, arriving {order.expected_delivery} ({order.status})")
        return "\n".join(lines)
    
    def _openai_decision(
        self,
        recommendation: Dict[str, Any],
        investigation: InvestigationResult
    ) -> Dict[str, Any]:
        """Make decision using OpenAI"""
        prompt = self._build_prompt(recommendation, investigation)
        
        try:
            response = self.openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert purchasing analyst."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            return {
                "decision": result.get("decision", "INVESTIGATE_FURTHER"),
                "final_quantity": result.get("final_quantity", recommendation['recommended_quantity']),
                "final_supplier": recommendation['recommended_supplier'],
                "reasoning": result.get("reasoning", ""),
                "evidence": result.get("evidence", []),
                "confidence": result.get("confidence", 0.7),
                "llm_model": self.model,
                "llm_prompt": prompt,
                "llm_response": response.choices[0].message.content
            }
        
        except Exception as e:
            print(f"OpenAI API error: {e}, falling back to demo mode")
            return self._demo_decision(recommendation, investigation)
    
    def _anthropic_decision(
        self,
        recommendation: Dict[str, Any],
        investigation: InvestigationResult
    ) -> Dict[str, Any]:
        """Make decision using Anthropic"""
        prompt = self._build_prompt(recommendation, investigation)
        
        try:
            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            result = json.loads(response.content[0].text)
            
            return {
                "decision": result.get("decision", "INVESTIGATE_FURTHER"),
                "final_quantity": result.get("final_quantity", recommendation['recommended_quantity']),
                "final_supplier": recommendation['recommended_supplier'],
                "reasoning": result.get("reasoning", ""),
                "evidence": result.get("evidence", []),
                "confidence": result.get("confidence", 0.7),
                "llm_model": self.model,
                "llm_prompt": prompt,
                "llm_response": response.content[0].text
            }
        
        except Exception as e:
            print(f"Anthropic API error: {e}, falling back to demo mode")
            return self._demo_decision(recommendation, investigation)
