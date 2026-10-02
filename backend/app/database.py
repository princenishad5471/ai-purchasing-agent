"""Database setup using SQLite"""
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
import json
from datetime import datetime


class Database:
    def __init__(self, db_path: Optional[str] = None):
        # Absolute default so the DB does not depend on the working directory
        self.db_path = db_path or os.getenv("DATABASE_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "purchasing_agent.db"
        )
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    @contextmanager
    def get_cursor(self):
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        """Initialize database schema"""
        with self.get_cursor() as cursor:
            # Recommendations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    recommended_quantity INTEGER NOT NULL,
                    recommended_supplier TEXT NOT NULL,
                    recommendation_source TEXT DEFAULT 'system_auto',
                    status TEXT DEFAULT 'pending_review',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Investigations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS investigations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT NOT NULL,
                    investigation_data TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id)
                )
            """)
            
            # Decisions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    final_quantity INTEGER NOT NULL,
                    final_supplier TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    requires_approval BOOLEAN DEFAULT 0,
                    approval_reason TEXT,
                    llm_model TEXT NOT NULL,
                    llm_prompt TEXT,
                    llm_response TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id)
                )
            """)
            
            # Purchase Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    po_id TEXT PRIMARY KEY,
                    recommendation_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    supplier_id TEXT NOT NULL,
                    supplier_name TEXT NOT NULL,
                    line_items TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    expected_delivery TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    created_by TEXT DEFAULT 'agent',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    validated_at TIMESTAMP,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id)
                )
            """)
            
            # Validations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT NOT NULL,
                    po_id TEXT,
                    validation_type TEXT NOT NULL,
                    validation_data TEXT NOT NULL,
                    all_passed BOOLEAN NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id)
                )
            """)
            
            # Trace logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trace_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    data TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id)
                )
            """)
    
    def save_recommendation(self, rec: Dict[str, Any]) -> str:
        """Save a purchase recommendation"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO recommendations 
                (recommendation_id, product_id, product_name, node_id, node_name, 
                 recommended_quantity, recommended_supplier, recommendation_source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec['recommendation_id'], rec['product_id'], rec['product_name'],
                rec['node_id'], rec['node_name'], rec['recommended_quantity'],
                rec['recommended_supplier'], rec.get('recommendation_source', 'system_auto'),
                rec.get('status', 'pending_review')
            ))
        return rec['recommendation_id']
    
    def get_recommendation(self, recommendation_id: str) -> Optional[Dict[str, Any]]:
        """Get a recommendation by ID"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None
    
    def update_recommendation_status(self, recommendation_id: str, status: str):
        """Move a recommendation to a new status"""
        with self.get_cursor() as cursor:
            cursor.execute(
                "UPDATE recommendations SET status = ? WHERE recommendation_id = ?",
                (status, recommendation_id)
            )
    
    def claim_recommendation(self, recommendation_id: str, from_status: str = "pending_review") -> bool:
        """Atomically move from_status -> investigating. False if not in that status."""
        with self.get_cursor() as cursor:
            cursor.execute(
                "UPDATE recommendations SET status = 'investigating' "
                "WHERE recommendation_id = ? AND status = ?",
                (recommendation_id, from_status)
            )
            return cursor.rowcount == 1
    
    def get_latest_decision(self, recommendation_id: str) -> Optional[Dict[str, Any]]:
        """Most recent agent decision for a recommendation"""
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM decisions WHERE recommendation_id = ? ORDER BY id DESC LIMIT 1",
                (recommendation_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_committed_spend(self, node_id: str, product_ids: Optional[List[str]] = None) -> float:
        """Value of live agent POs for a node this month (not yet in the static budget data).
        With product_ids, only those line items count (category spend)."""
        month_start = datetime.utcnow().strftime("%Y-%m-01")
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT total_amount, line_items FROM purchase_orders
                WHERE node_id = ? AND status NOT IN ('failed', 'cancelled')
                  AND created_at >= ?
            """, (node_id, month_start))
            rows = cursor.fetchall()
        if product_ids is None:
            return float(sum(r['total_amount'] for r in rows))
        wanted = set(product_ids)
        return float(sum(
            item.get('total_price', 0)
            for r in rows for item in json.loads(r['line_items'])
            if item.get('product_id') in wanted
        ))
    
    def get_inbound_quantity(self, node_id: str, product_id: str) -> int:
        """Units on live agent POs for a product that have not been delivered yet"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT line_items FROM purchase_orders
                WHERE node_id = ? AND status IN ('submitted', 'confirmed')
                  AND expected_delivery >= ?
            """, (node_id, today))
            rows = cursor.fetchall()
        return int(sum(
            item.get('quantity', 0)
            for r in rows for item in json.loads(r['line_items'])
            if item.get('product_id') == product_id
        ))
    
    def save_investigation(self, recommendation_id: str, investigation: Dict[str, Any]):
        """Save investigation results"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO investigations (recommendation_id, investigation_data)
                VALUES (?, ?)
            """, (recommendation_id, json.dumps(investigation)))
    
    def save_decision(self, decision: Dict[str, Any]):
        """Save agent decision"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO decisions 
                (recommendation_id, decision, final_quantity, final_supplier, reasoning,
                 evidence, confidence, requires_approval, approval_reason, llm_model,
                 llm_prompt, llm_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision['recommendation_id'], decision['decision'], decision['final_quantity'],
                decision['final_supplier'], decision['reasoning'], json.dumps(decision['evidence']),
                decision['confidence'], decision['requires_approval'], decision.get('approval_reason'),
                decision['llm_model'], decision.get('llm_prompt'), decision.get('llm_response')
            ))
    
    def save_purchase_order(self, po: Dict[str, Any]):
        """Save purchase order"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO purchase_orders
                (po_id, recommendation_id, node_id, supplier_id, supplier_name,
                 line_items, total_amount, expected_delivery, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                po['po_id'], po['recommendation_id'], po['node_id'], po['supplier_id'],
                po['supplier_name'], json.dumps(po['line_items']), po['total_amount'],
                po['expected_delivery'], po['status'], po.get('created_by', 'agent')
            ))
    
    def update_po_status(self, po_id: str, status: str):
        """Update a purchase order's status"""
        with self.get_cursor() as cursor:
            cursor.execute(
                "UPDATE purchase_orders SET status = ? WHERE po_id = ?",
                (status, po_id)
            )
    
    def save_validation(self, validation: Dict[str, Any]):
        """Save validation results"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO validations
                (recommendation_id, po_id, validation_type, validation_data, all_passed)
                VALUES (?, ?, ?, ?, ?)
            """, (
                validation['recommendation_id'], validation.get('po_id'),
                validation['validation_type'], json.dumps(validation['validation_data']),
                validation['all_passed']
            ))
    
    def add_trace(self, recommendation_id: str, step: str, data: Optional[Dict[str, Any]] = None):
        """Add a trace log entry"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO trace_logs (recommendation_id, step, data)
                VALUES (?, ?, ?)
            """, (recommendation_id, step, json.dumps(data) if data else None))
    
    def get_trace(self, recommendation_id: str) -> List[Dict[str, Any]]:
        """Get trace logs for a recommendation"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT step, data, timestamp
                FROM trace_logs
                WHERE recommendation_id = ?
                ORDER BY id
            """, (recommendation_id,))
            rows = cursor.fetchall()
            return [
                {
                    'step': row['step'],
                    'data': json.loads(row['data']) if row['data'] else None,
                    'timestamp': row['timestamp']
                }
                for row in rows
            ]


# Global database instance
db = Database()
