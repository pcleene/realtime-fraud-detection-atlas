// Atlas Setup Script for RegionalBank Fraud Detection POC
// Run this script against your Atlas cluster using mongosh
//
// Usage:
//   mongosh "mongodb+srv://<username>:<password>@<cluster>.mongodb.net/" < scripts/atlas-setup.js
//
// Prerequisites:
//   1. Atlas cluster with sharding enabled (M30+ for sharded cluster)
//   2. Database user with dbAdmin and readWrite roles
//   3. PrivateLink endpoint configured (for EC2 deployment)

print("=== RegionalBank Fraud Detection POC - Atlas Setup ===\n");

// Switch to the database
use("RegionalBank_fraud");

// ============================================
// Step 1: Enable Sharding on Database
// ============================================
print("Step 1: Enabling sharding on database...");
try {
    sh.enableSharding("RegionalBank_fraud");
    print("  Database sharding enabled");
} catch (e) {
    if (e.message.includes("already enabled")) {
        print("  Database sharding already enabled");
    } else {
        print("  Warning: " + e.message);
    }
}

// ============================================
// Step 2: Create Indexes Before Sharding
// ============================================
print("\nStep 2: Creating indexes...");

// Customers indexes
print("  Creating customers indexes...");
db.customers.createIndex({ customer_id: 1 }, { unique: true, name: "customer_id_unique" });
db.customers.createIndex({ "features.latest_location": "2dsphere" }, { sparse: true, name: "features_location_2dsphere" });

// Transactions indexes (shard key index will be created by shardCollection)
print("  Creating transactions indexes...");
db.transactions.createIndex({ customer_id: 1, timestamp: -1 }, { name: "customer_timestamp" });
db.transactions.createIndex({ location: "2dsphere" }, { sparse: true, name: "location_2dsphere" });
db.transactions.createIndex({ timestamp: -1, "fraud_score.risk_level": -1 }, { name: "timestamp_risk_level_desc" });

// Blacklist locations indexes
print("  Creating blacklist_locations indexes...");
db.blacklist_locations.createIndex({ city: 1, province: 1 }, { name: "city_province" });
db.blacklist_locations.createIndex({ location: "2dsphere" }, { name: "location_2dsphere" });

// Holidays indexes
print("  Creating holidays indexes...");
db.holidays.createIndex({ "date_range.start": 1, "date_range.end": 1 }, { name: "date_range" });
db.holidays.createIndex({ year: 1 }, { name: "year" });

// Rules indexes
print("  Creating rules indexes...");
db.rules.createIndex({ active: 1, type: 1 }, { name: "active_type" });

print("  All indexes created");

// ============================================
// Step 3: Shard Collections
// ============================================
print("\nStep 3: Sharding collections...");

// Shard customers collection
print("  Sharding customers collection...");
try {
    sh.shardCollection("RegionalBank_fraud.customers", { customer_id: 1 });
    print("    customers sharded with key: { customer_id: 1 }");
} catch (e) {
    if (e.message.includes("already sharded")) {
        print("    customers already sharded");
    } else {
        print("    Warning: " + e.message);
    }
}

// Shard transactions collection
print("  Sharding transactions collection...");
try {
    sh.shardCollection("RegionalBank_fraud.transactions", {
        customer_id: 1,
        shard_key_month: 1,
        _id: 1
    });
    print("    transactions sharded with key: { customer_id: 1, shard_key_month: 1, _id: 1 }");
} catch (e) {
    if (e.message.includes("already sharded")) {
        print("    transactions already sharded");
    } else {
        print("    Warning: " + e.message);
    }
}

// ============================================
// Step 4: Verify Setup
// ============================================
print("\nStep 4: Verifying setup...");

print("\n  Shard status:");
sh.status();

print("\n  Collection indexes:");
print("    customers: " + JSON.stringify(db.customers.getIndexes().map(i => i.name)));
print("    transactions: " + JSON.stringify(db.transactions.getIndexes().map(i => i.name)));
print("    blacklist_locations: " + JSON.stringify(db.blacklist_locations.getIndexes().map(i => i.name)));
print("    holidays: " + JSON.stringify(db.holidays.getIndexes().map(i => i.name)));

print("\n=== Atlas Setup Complete ===");
print("\nNext steps:");
print("  1. Configure PrivateLink endpoint in Atlas");
print("  2. Update .env with Atlas connection string");
print("  3. Run seed script: python -m seed.main");
print("  4. Start API server: uvicorn app.main:app");
