// Atlas Setup Script for RegionalBank Fraud Detection V2
// Run this script against your Atlas cluster using mongosh
//
// Usage:
//   mongosh "mongodb+srv://<username>:<password>@<cluster>.mongodb.net/" < scripts/atlas-setup-v2.js

print("=== RegionalBank Fraud Detection V2 - Atlas Setup ===\n");

use("RegionalBank_fraud_v2");

// Step 1: Enable sharding
print("Step 1: Enabling sharding on database...");
try {
    sh.enableSharding("RegionalBank_fraud_v2");
    print("  Database sharding enabled");
} catch (e) {
    print("  " + (e.message.includes("already enabled") ? "Already enabled" : "Warning: " + e.message));
}

// Step 2: Create indexes
print("\nStep 2: Creating indexes...");

// Customers
print("  Creating customers indexes...");
db.customers.createIndex({ customer_id: 1 }, { unique: true, name: "customer_id_unique" });

// Transactions
print("  Creating transactions indexes...");
db.transactions.createIndex({ customer_id: 1, z1: -1 }, { name: "customer_z1" });
db.transactions.createIndex({ z1: -1, "fraud_score.risk_level": -1 }, { name: "z1_risk_level_desc" });
db.transactions.createIndex({ "fraud_score.triggered_count": 1 }, { sparse: true, name: "triggered_count" });

// Blacklist collections (small, loaded to memory -- indexes for batch refresh)
print("  Creating blacklist indexes...");
db.pot_bf.createIndex({ b23: 1 }, { unique: true, name: "b23_unique" });
db.pot_bf24.createIndex({ b23: 1 }, { name: "b23_idx" });
db.pot_sm.createIndex({ n3: 1 }, { unique: true, name: "n3_unique" });
db.pot_anj.createIndex({ b23: 1 }, { unique: true, name: "b23_unique" });
db.pot_pp.createIndex({ b23: 1 }, { unique: true, name: "b23_unique" });
db.pot_cb.createIndex({ b23: 1 }, { unique: true, name: "b23_unique" });

// Service config + overflow
print("  Creating service config and overflow indexes...");
db.pot_sl_va.createIndex({ service: 1 }, { unique: true, name: "service_unique" });
db.pot_nb_overflow.createIndex({ customer_id: 1, b2: 1 }, { unique: true, name: "customer_b2_unique" });

// Consolidated transaction-level lookups (single-field index, not sharded)
print("  Creating txn_lookups index...");
db.txn_lookups.createIndex({ lookup_value: 1 }, { name: "idx_lookup_value" });

// Load tests
db.load_tests.createIndex({ test_id: 1 }, { name: "test_id_1" });

print("  All indexes created");

// Step 3: Shard collections (only customers + transactions)
print("\nStep 3: Sharding collections...");

try {
    sh.shardCollection("RegionalBank_fraud_v2.customers", { customer_id: 1 });
    print("  customers sharded: { customer_id: 1 }");
} catch (e) {
    print("  " + (e.message.includes("already sharded") ? "customers already sharded" : "Warning: " + e.message));
}

try {
    sh.shardCollection("RegionalBank_fraud_v2.transactions", { customer_id: 1, shard_key_month: 1, _id: 1 });
    print("  transactions sharded: { customer_id: 1, shard_key_month: 1, _id: 1 }");
} catch (e) {
    print("  " + (e.message.includes("already sharded") ? "transactions already sharded" : "Warning: " + e.message));
}

try {
    sh.shardCollection("RegionalBank_fraud_v2.pot_nb_overflow", { customer_id: 1, b2: 1 });
    print("  pot_nb_overflow sharded (range): { customer_id: 1, b2: 1 }");
} catch (e) {
    print("  " + (e.message.includes("already sharded") ? "pot_nb_overflow already sharded" : "Warning: " + e.message));
}

// Step 4: Verify
print("\nStep 4: Verifying...");
sh.status();

print("\n  Collection indexes:");
["customers", "transactions", "pot_bf", "pot_bf24", "pot_sm", "pot_anj", "pot_pp", "pot_cb", "pot_sl_va", "pot_nb_overflow", "txn_lookups", "load_tests"].forEach(c => {
    print("    " + c + ": " + JSON.stringify(db[c].getIndexes().map(i => i.name)));
});

print("\n=== V2 Atlas Setup Complete ===");
print("\nNext steps:");
print("  1. Update backend_v2/.env with DB_NAME=RegionalBank_fraud_v2");
print("  2. Run seed: cd backend_v2 && python -m seed.main");
print("  3. Start V2 API: uvicorn app.main:app --port 8001");
