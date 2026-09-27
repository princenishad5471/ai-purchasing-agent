#!/usr/bin/env python3
"""Quick end-to-end test of the agent"""
import urllib.request
import json

print("🚀 Testing AI Purchasing Agent\n")

# Create recommendation
print("1. Creating purchase recommendation...")
rec_data = {
    "product_id": "coca-cola-500ml",
    "product_name": "Coca-Cola 500ml",
    "node_id": "delhi-ncr-dark-store-a",
    "node_name": "Delhi-NCR Dark Store A",
    "recommended_quantity": 800,
    "recommended_supplier": "supplier_x"
}

req = urllib.request.Request(
    "http://localhost:8000/api/recommendations",
    data=json.dumps(rec_data).encode(),
    headers={'Content-Type': 'application/json'}
)
response = urllib.request.urlopen(req)
rec = json.loads(response.read())
rec_id = rec['recommendation_id']
print(f"✅ Created: {rec_id}\n")

# Review recommendation
print("2. Reviewing with agent...")
req = urllib.request.Request(
    f"http://localhost:8000/api/recommendations/{rec_id}/review",
    method='POST'
)

try:
    response = urllib.request.urlopen(req)
    result = json.loads(response.read())
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# Display results
print("=" * 60)
print("🤖 AGENT REVIEW RESULT")
print("=" * 60)

print(f"\n📊 Decision: {result['decision']['decision']}")
print(f"   Final Quantity: {result['decision']['final_quantity']} units")
print(f"   Confidence: {result['decision']['confidence']}")
print(f"   Model: {result['decision']['llm_model']}")

print(f"\n💡 Reasoning:")
print(f"   {result['decision']['reasoning']}")

print(f"\n📋 Evidence:")
for evidence in result['decision']['evidence'][:5]:
    print(f"   • {evidence}")

print(f"\n✅ Constraint Validation:")
all_passed = result['constraint_validation']['all_passed']
print(f"   Status: {'✅ ALL PASSED' if all_passed else '❌ FAILED'}")

for name, validation in result['constraint_validation']['validations'].items():
    icon = '✓' if validation['passed'] else '✗'
    print(f"   {icon} {name}: {validation['message']}")

if result['purchase_order']:
    po = result['purchase_order']
    print(f"\n📄 Purchase Order:")
    print(f"   PO ID: {po['po_id']}")
    print(f"   Supplier: {po['supplier_name']}")
    print(f"   Total Amount: ₹{po['total_amount']:.2f}")
    print(f"   Status: {po['status']}")
    print(f"   Expected Delivery: {po['expected_delivery']}")

if result['post_validation']:
    pv = result['post_validation']
    print(f"\n✔️  Post-Action Validation:")
    for check, passed in pv['checks'].items():
        icon = '✓' if passed else '✗'
        print(f"   {icon} {check}")

print(f"\n📝 Trace: {len(result['trace'])} steps")
print(f"   {' → '.join([t['step'] for t in result['trace'][:5]])}")

print("\n" + "=" * 60)
print("✅ TEST COMPLETE")
print("=" * 60)
