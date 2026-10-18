"""
TrustMed: Blockchain-Secured Medical Management
=================================================
Flask backend implementing:
  - A lightweight SQLite-backed inventory & order management system
  - A from-scratch SHA-256 blockchain ledger that records every
    inventory seed, order placement and order-status change as an
    immutable transaction block
  - REST API endpoints consumed by the Patient / Admin / Auditor UI

All monetary values across the application are in Indian Rupees (INR / ₹).

Run with:
    python app.py
Then open http://localhost:5000
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request
from flask_cors import CORS

# --------------------------------------------------------------------------- #
# App & DB configuration
# --------------------------------------------------------------------------- #

app = Flask(__name__)
CORS(app)

DATABASE = "trustmed.db"


def get_db():
    """Return a SQLite connection for the current app context."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------- #
# Blockchain implementation (SHA-256, from scratch)
# --------------------------------------------------------------------------- #

class Block:
    """A single immutable block in the TrustMed ledger."""

    def __init__(self, index, timestamp, event_type, payload, previous_hash, nonce=0):
        self.index = index
        self.timestamp = timestamp
        self.event_type = event_type          # e.g. GENESIS, INVENTORY_SEED, ORDER_PLACED, ORDER_STATUS_UPDATE, STOCK_UPDATE
        self.payload = payload                # dict -> transaction details (amounts in INR)
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.compute_hash()

    def compute_hash(self):
        """SHA-256 hash of the block's canonical JSON representation."""
        block_string = json.dumps(
            {
                "index": self.index,
                "timestamp": self.timestamp,
                "event_type": self.event_type,
                "payload": self.payload,
                "previous_hash": self.previous_hash,
                "nonce": self.nonce,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(block_string.encode("utf-8")).hexdigest()

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
            "nonce": self.nonce,
        }


class Blockchain:
    """In-memory hash-chained ledger. Genesis block is mined on boot."""

    DIFFICULTY_PREFIX = ""  # kept simple (no PoW mining delay) for a snappy demo

    def __init__(self):
        self.chain = []
        self._create_genesis_block()

    def _create_genesis_block(self):
        genesis = Block(
            index=0,
            timestamp=self._now(),
            event_type="GENESIS",
            payload={
                "message": "TrustMed Ledger Genesis Block",
                "currency": "INR",
                "organization": "TrustMed Pharmacy Network",
            },
            previous_hash="0" * 64,
        )
        self.chain.append(genesis)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def get_latest_block(self):
        return self.chain[-1]

    def add_block(self, event_type, payload):
        previous_block = self.get_latest_block()
        new_block = Block(
            index=previous_block.index + 1,
            timestamp=self._now(),
            event_type=event_type,
            payload=payload,
            previous_hash=previous_block.hash,
        )
        self.chain.append(new_block)
        return new_block

    def verify_integrity(self):
        """
        Recalculates the hash of every block and checks:
          1. The stored hash matches a freshly recomputed hash (data untampered)
          2. Each block's previous_hash correctly links to the prior block's hash
        Returns a detailed per-block report plus an overall verdict.
        """
        report = []
        valid = True

        for i, block in enumerate(self.chain):
            recomputed_hash = block.compute_hash()
            hash_matches = recomputed_hash == block.hash

            if i == 0:
                link_matches = block.previous_hash == "0" * 64
            else:
                link_matches = block.previous_hash == self.chain[i - 1].hash

            block_valid = hash_matches and link_matches
            if not block_valid:
                valid = False

            report.append(
                {
                    "index": block.index,
                    "event_type": block.event_type,
                    "stored_hash": block.hash,
                    "recomputed_hash": recomputed_hash,
                    "hash_matches": hash_matches,
                    "previous_hash_link_valid": link_matches,
                    "block_valid": block_valid,
                }
            )

        return {"valid": valid, "blocks_checked": len(self.chain), "report": report}

    def to_list(self):
        return [b.to_dict() for b in self.chain]


ledger = Blockchain()


# --------------------------------------------------------------------------- #
# Database setup & seed data (all prices in INR)
# --------------------------------------------------------------------------- #

def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.executescript(
            """
            DROP TABLE IF EXISTS medicines;
            DROP TABLE IF EXISTS orders;

            CREATE TABLE medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                stock INTEGER NOT NULL,
                price REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'Placed',
                created_at TEXT NOT NULL
            );
            """
        )

        seed_medicines = [
            ("Paracetamol 650mg", "Pain Relief", 150, 30.00),
            ("Amoxicillin 500mg", "Antibiotics", 80, 85.00),
            ("Metformin 500mg", "Diabetes", 200, 50.00),
            ("Atorvastatin 10mg", "Cardiovascular", 90, 110.00),
            ("Azithromycin 250mg", "Antibiotics", 60, 95.00),
            ("Cetirizine 10mg", "Antihistamine", 120, 35.00),
        ]
        db.executemany(
            "INSERT INTO medicines (name, category, stock, price, active) VALUES (?, ?, ?, ?, 1)",
            seed_medicines,
        )
        db.commit()


def seed_blockchain_and_orders():
    """Pre-mine sample ledger blocks: inventory seeding + sample orders."""
    with sqlite3.connect(DATABASE) as db:
        db.row_factory = sqlite3.Row
        medicines = db.execute("SELECT * FROM medicines").fetchall()

        # Block 1: bulk inventory seeding event
        inventory_payload = {
            "action": "INITIAL_INVENTORY_SEED",
            "currency": "INR",
            "items": [
                {
                    "medicine": m["name"],
                    "category": m["category"],
                    "stock": m["stock"],
                    "unit_price_inr": m["price"],
                }
                for m in medicines
            ],
            "total_inventory_value_inr": round(
                sum(m["stock"] * m["price"] for m in medicines), 2
            ),
        }
        ledger.add_block("INVENTORY_SEED", inventory_payload)

        # Sample Order 1
        order1_items = [
            {"medicine": "Paracetamol 650mg", "qty": 2, "unit_price_inr": 30.00, "subtotal_inr": 60.00},
            {"medicine": "Cetirizine 10mg", "qty": 1, "unit_price_inr": 35.00, "subtotal_inr": 35.00},
        ]
        order1_total = round(sum(i["subtotal_inr"] for i in order1_items), 2)
        cur = db.execute(
            "INSERT INTO orders (customer_name, items_json, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Aarav Sharma", json.dumps(order1_items), order1_total, "Delivered", datetime.now(timezone.utc).isoformat()),
        )
        order1_id = cur.lastrowid
        db.execute(
            "UPDATE medicines SET stock = stock - 2 WHERE name = 'Paracetamol 650mg'"
        )
        db.execute(
            "UPDATE medicines SET stock = stock - 1 WHERE name = 'Cetirizine 10mg'"
        )
        ledger.add_block(
            "ORDER_PLACED",
            {
                "order_id": order1_id,
                "customer_name": "Aarav Sharma",
                "items": order1_items,
                "total_inr": order1_total,
                "currency": "INR",
            },
        )

        # Sample Order 2
        order2_items = [
            {"medicine": "Amoxicillin 500mg", "qty": 1, "unit_price_inr": 85.00, "subtotal_inr": 85.00},
            {"medicine": "Atorvastatin 10mg", "qty": 3, "unit_price_inr": 110.00, "subtotal_inr": 330.00},
        ]
        order2_total = round(sum(i["subtotal_inr"] for i in order2_items), 2)
        cur = db.execute(
            "INSERT INTO orders (customer_name, items_json, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Priya Nair", json.dumps(order2_items), order2_total, "Processing", datetime.now(timezone.utc).isoformat()),
        )
        order2_id = cur.lastrowid
        db.execute(
            "UPDATE medicines SET stock = stock - 1 WHERE name = 'Amoxicillin 500mg'"
        )
        db.execute(
            "UPDATE medicines SET stock = stock - 3 WHERE name = 'Atorvastatin 10mg'"
        )
        ledger.add_block(
            "ORDER_PLACED",
            {
                "order_id": order2_id,
                "customer_name": "Priya Nair",
                "items": order2_items,
                "total_inr": order2_total,
                "currency": "INR",
            },
        )

        # Block: a stock replenishment event by Admin
        db.execute(
            "UPDATE medicines SET stock = stock + 50 WHERE name = 'Azithromycin 250mg'"
        )
        ledger.add_block(
            "STOCK_UPDATE",
            {
                "medicine": "Azithromycin 250mg",
                "change": "+50 units",
                "reason": "Supplier restock",
                "unit_price_inr": 95.00,
            },
        )

        db.commit()


# --------------------------------------------------------------------------- #
# Helper serializers
# --------------------------------------------------------------------------- #

def medicine_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "stock": row["stock"],
        "price": row["price"],
        "active": bool(row["active"]),
    }


def order_to_dict(row):
    return {
        "id": row["id"],
        "customer_name": row["customer_name"],
        "items": json.loads(row["items_json"]),
        "total": row["total"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# Patient Module - Catalog & Ordering
# --------------------------------------------------------------------------- #

@app.route("/api/medicines", methods=["GET"])
def get_medicines():
    """Active medicine catalog, with optional search & category filters."""
    db = get_db()
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    query = "SELECT * FROM medicines WHERE active = 1"
    params = []

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")
    if category and category.lower() != "all":
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY name ASC"
    rows = db.execute(query, params).fetchall()
    return jsonify([medicine_to_dict(r) for r in rows])


@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT category FROM medicines WHERE active = 1 ORDER BY category ASC"
    ).fetchall()
    return jsonify([r["category"] for r in rows])


@app.route("/api/orders", methods=["POST"])
def place_order():
    """Place an order from the patient cart. Decrements stock & mines a block."""
    db = get_db()
    data = request.get_json(force=True) or {}
    customer_name = (data.get("customer_name") or "Guest Patient").strip()
    cart = data.get("items", [])  # [{id, qty}]

    if not cart:
        return jsonify({"error": "Cart is empty"}), 400

    order_items = []
    total = 0.0

    # Validate stock & build order line items
    for entry in cart:
        med = db.execute(
            "SELECT * FROM medicines WHERE id = ? AND active = 1", (entry.get("id"),)
        ).fetchone()
        if med is None:
            return jsonify({"error": f"Medicine id {entry.get('id')} not found"}), 404

        qty = int(entry.get("qty", 0))
        if qty <= 0:
            return jsonify({"error": f"Invalid quantity for {med['name']}"}), 400
        if qty > med["stock"]:
            return jsonify({"error": f"Insufficient stock for {med['name']}"}), 400

        subtotal = round(qty * med["price"], 2)
        total += subtotal
        order_items.append(
            {
                "medicine_id": med["id"],
                "medicine": med["name"],
                "qty": qty,
                "unit_price_inr": med["price"],
                "subtotal_inr": subtotal,
            }
        )

    total = round(total, 2)

    # Persist order & decrement stock atomically
    cur = db.execute(
        "INSERT INTO orders (customer_name, items_json, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (customer_name, json.dumps(order_items), total, "Placed", datetime.now(timezone.utc).isoformat()),
    )
    order_id = cur.lastrowid

    for item in order_items:
        db.execute(
            "UPDATE medicines SET stock = stock - ? WHERE id = ?",
            (item["qty"], item["medicine_id"]),
        )
    db.commit()

    # Mine a new ledger block for this transaction
    block = ledger.add_block(
        "ORDER_PLACED",
        {
            "order_id": order_id,
            "customer_name": customer_name,
            "items": order_items,
            "total_inr": total,
            "currency": "INR",
        },
    )

    return jsonify({"order": order_to_dict(db.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()), "block": block.to_dict()}), 201


@app.route("/api/orders", methods=["GET"])
def get_orders():
    db = get_db()
    rows = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    return jsonify([order_to_dict(r) for r in rows])


@app.route("/api/orders/<int:order_id>/status", methods=["PUT"])
def update_order_status(order_id):
    """Admin: update an order's fulfillment status. Mines a new block."""
    db = get_db()
    data = request.get_json(force=True) or {}
    new_status = data.get("status")

    valid_statuses = {"Placed", "Processing", "Shipped", "Delivered", "Cancelled"}
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of {sorted(valid_statuses)}"}), 400

    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return jsonify({"error": "Order not found"}), 404

    old_status = order["status"]
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    db.commit()

    block = ledger.add_block(
        "ORDER_STATUS_UPDATE",
        {
            "order_id": order_id,
            "customer_name": order["customer_name"],
            "total_inr": order["total"],
            "old_status": old_status,
            "new_status": new_status,
        },
    )

    updated = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify({"order": order_to_dict(updated), "block": block.to_dict()})


# --------------------------------------------------------------------------- #
# Admin Module - Inventory Management
# --------------------------------------------------------------------------- #

@app.route("/api/admin/medicines", methods=["GET"])
def admin_get_all_medicines():
    db = get_db()
    rows = db.execute("SELECT * FROM medicines ORDER BY id ASC").fetchall()
    return jsonify([medicine_to_dict(r) for r in rows])


@app.route("/api/admin/medicines", methods=["POST"])
def admin_add_medicine():
    db = get_db()
    data = request.get_json(force=True) or {}

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    try:
        stock = int(data.get("stock", 0))
        price = round(float(data.get("price", 0)), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Stock and price must be numeric"}), 400

    if not name or not category:
        return jsonify({"error": "Name and category are required"}), 400
    if stock < 0 or price <= 0:
        return jsonify({"error": "Stock must be >= 0 and price must be > 0"}), 400

    cur = db.execute(
        "INSERT INTO medicines (name, category, stock, price, active) VALUES (?, ?, ?, ?, 1)",
        (name, category, stock, price),
    )
    db.commit()
    med_id = cur.lastrowid

    block = ledger.add_block(
        "MEDICINE_ADDED",
        {
            "medicine_id": med_id,
            "name": name,
            "category": category,
            "stock": stock,
            "unit_price_inr": price,
        },
    )

    new_row = db.execute("SELECT * FROM medicines WHERE id = ?", (med_id,)).fetchone()
    return jsonify({"medicine": medicine_to_dict(new_row), "block": block.to_dict()}), 201


@app.route("/api/admin/medicines/<int:med_id>", methods=["PUT"])
def admin_update_medicine(med_id):
    """Update stock and/or price for an existing medicine. Mines a block."""
    db = get_db()
    data = request.get_json(force=True) or {}

    med = db.execute("SELECT * FROM medicines WHERE id = ?", (med_id,)).fetchone()
    if med is None:
        return jsonify({"error": "Medicine not found"}), 404

    new_stock = data.get("stock", med["stock"])
    new_price = data.get("price", med["price"])

    try:
        new_stock = int(new_stock)
        new_price = round(float(new_price), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Stock and price must be numeric"}), 400

    if new_stock < 0 or new_price <= 0:
        return jsonify({"error": "Stock must be >= 0 and price must be > 0"}), 400

    db.execute(
        "UPDATE medicines SET stock = ?, price = ? WHERE id = ?",
        (new_stock, new_price, med_id),
    )
    db.commit()

    block = ledger.add_block(
        "STOCK_UPDATE",
        {
            "medicine_id": med_id,
            "name": med["name"],
            "old_stock": med["stock"],
            "new_stock": new_stock,
            "old_price_inr": med["price"],
            "new_price_inr": new_price,
        },
    )

    updated = db.execute("SELECT * FROM medicines WHERE id = ?", (med_id,)).fetchone()
    return jsonify({"medicine": medicine_to_dict(updated), "block": block.to_dict()})


@app.route("/api/admin/medicines/<int:med_id>/toggle", methods=["PUT"])
def admin_toggle_medicine(med_id):
    """Activate / deactivate a listing. Mines a block."""
    db = get_db()
    med = db.execute("SELECT * FROM medicines WHERE id = ?", (med_id,)).fetchone()
    if med is None:
        return jsonify({"error": "Medicine not found"}), 404

    new_active = 0 if med["active"] else 1
    db.execute("UPDATE medicines SET active = ? WHERE id = ?", (new_active, med_id))
    db.commit()

    block = ledger.add_block(
        "LISTING_STATUS_CHANGE",
        {
            "medicine_id": med_id,
            "name": med["name"],
            "active": bool(new_active),
        },
    )

    updated = db.execute("SELECT * FROM medicines WHERE id = ?", (med_id,)).fetchone()
    return jsonify({"medicine": medicine_to_dict(updated), "block": block.to_dict()})


# --------------------------------------------------------------------------- #
# Auditor Module - Blockchain Explorer
# --------------------------------------------------------------------------- #

@app.route("/api/blockchain", methods=["GET"])
def get_blockchain():
    return jsonify(ledger.to_list())


@app.route("/api/blockchain/verify", methods=["GET"])
def verify_blockchain():
    return jsonify(ledger.verify_integrity())


@app.route("/api/blockchain/tamper-demo", methods=["POST"])
def tamper_demo():
    """
    Educational endpoint: intentionally corrupts a block's payload in memory
    so the Auditor can demonstrate that 'Verify Ledger Integrity' catches it.
    Does NOT touch the SQLite database - only the in-memory ledger copy.
    """
    data = request.get_json(force=True) or {}
    index = data.get("index")

    target = next((b for b in ledger.chain if b.index == index), None)
    if target is None:
        return jsonify({"error": "Block not found"}), 404
    if target.event_type == "GENESIS":
        return jsonify({"error": "Cannot tamper with the genesis block in this demo"}), 400

    target.payload["total_inr"] = 999999.99
    target.payload["_tampered"] = True
    # NOTE: hash intentionally NOT recomputed here, simulating an attacker
    # editing historical data without redoing the proof-of-work / hash chain.

    return jsonify({"message": f"Block {index} payload tampered in memory for demo purposes."})


@app.route("/api/blockchain/reset-demo", methods=["POST"])
def reset_demo():
    """Rebuilds the entire chain fresh (undoes the tamper demo)."""
    global ledger
    ledger = Blockchain()
    seed_blockchain_and_orders_from_existing_db()
    return jsonify({"message": "Ledger rebuilt from genesis."})


def seed_blockchain_and_orders_from_existing_db():
    """Re-mine ledger blocks that mirror current DB state (used by reset-demo)."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    medicines = db.execute("SELECT * FROM medicines").fetchall()
    orders = db.execute("SELECT * FROM orders ORDER BY id ASC").fetchall()

    ledger.add_block(
        "INVENTORY_SEED",
        {
            "action": "INITIAL_INVENTORY_SEED",
            "currency": "INR",
            "items": [
                {
                    "medicine": m["name"],
                    "category": m["category"],
                    "stock": m["stock"],
                    "unit_price_inr": m["price"],
                }
                for m in medicines
            ],
        },
    )

    for o in orders:
        ledger.add_block(
            "ORDER_PLACED",
            {
                "order_id": o["id"],
                "customer_name": o["customer_name"],
                "items": json.loads(o["items_json"]),
                "total_inr": o["total"],
                "currency": "INR",
            },
        )
    db.close()


# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    from flask import render_template
    return render_template("index.html")


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    init_db()
    seed_blockchain_and_orders()
    print("=" * 70)
    print(" TrustMed: Blockchain-Secured Medical Management")
    print(" Ledger initialized with", len(ledger.chain), "blocks")
    print(" Server running at http://localhost:5000")
    print("=" * 70)
    app.run(debug=True, host="0.0.0.0", port=5000)
