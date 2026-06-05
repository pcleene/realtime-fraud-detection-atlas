// Verify sharding configuration and data distribution
// Run this script against Atlas cluster
//
// Usage:
//   mongosh "mongodb+srv://<username>:<password>@<cluster>.mongodb.net/" < scripts/verify-sharding.js

print("=== RegionalBank Fraud Detection POC - Sharding Verification ===\n");

use("RegionalBank_fraud");

// Check cluster status
print("1. Cluster Status:");
print("==================");
sh.status();

// Check shard distribution for customers
print("\n2. Customers Collection Distribution:");
print("======================================");
try {
    db.customers.getShardDistribution();
} catch (e) {
    print("  Unable to get distribution: " + e.message);
}

// Check shard distribution for transactions
print("\n3. Transactions Collection Distribution:");
print("=========================================");
try {
    db.transactions.getShardDistribution();
} catch (e) {
    print("  Unable to get distribution: " + e.message);
}

// Verify query routing for customer lookup
print("\n4. Query Routing Verification:");
print("===============================");

// Get a sample customer_id if data exists
var sampleCustomer = db.customers.findOne({}, { customer_id: 1 });
var testCustomerId = sampleCustomer ? sampleCustomer.customer_id : "CUST-TEST123456";

// Test customer query routing
print("\nCustomer lookup (should be SINGLE_SHARD):");
var customerExplain = db.customers
    .find({ customer_id: testCustomerId })
    .explain("executionStats");

if (customerExplain.queryPlanner.winningPlan.shards) {
    print("  Shards targeted: " + customerExplain.queryPlanner.winningPlan.shards.length);
    print("  Single shard: " + (customerExplain.queryPlanner.winningPlan.shards.length === 1 ? "YES" : "NO"));
} else {
    print("  Query target: " + customerExplain.queryPlanner.winningPlan.stage);
}

// Test transaction query routing
print("\nTransaction lookup by customer (should be SINGLE_SHARD):");
var txnExplain = db.transactions
    .find({ customer_id: testCustomerId })
    .sort({ timestamp: -1 })
    .limit(10)
    .explain("executionStats");

if (txnExplain.queryPlanner.winningPlan.shards) {
    print("  Shards targeted: " + txnExplain.queryPlanner.winningPlan.shards.length);
    print("  Single shard: " + (txnExplain.queryPlanner.winningPlan.shards.length === 1 ? "YES" : "NO"));
} else {
    print("  Query target: " + txnExplain.queryPlanner.winningPlan.stage);
}

// Collection statistics
print("\n5. Collection Statistics:");
print("=========================");

var customersStats = db.runCommand({ collStats: "customers" });
print("\nCustomers:");
print("  - Count: " + (customersStats.count || 0));
print("  - Size: " + ((customersStats.size || 0) / (1024 * 1024)).toFixed(2) + " MB");
print("  - Sharded: " + (customersStats.sharded ? "Yes" : "No"));
if (customersStats.shards) {
    print("  - Shards: " + Object.keys(customersStats.shards).length);
}

var txnStats = db.runCommand({ collStats: "transactions" });
print("\nTransactions:");
print("  - Count: " + (txnStats.count || 0));
print("  - Size: " + ((txnStats.size || 0) / (1024 * 1024)).toFixed(2) + " MB");
print("  - Sharded: " + (txnStats.sharded ? "Yes" : "No"));
if (txnStats.shards) {
    print("  - Shards: " + Object.keys(txnStats.shards).length);
}

var blacklistStats = db.runCommand({ collStats: "blacklist_locations" });
print("\nBlacklist Locations:");
print("  - Count: " + (blacklistStats.count || 0));

var holidaysStats = db.runCommand({ collStats: "holidays" });
print("\nHolidays:");
print("  - Count: " + (holidaysStats.count || 0));

// Index verification
print("\n6. Index Verification:");
print("======================");

print("\nCustomers indexes:");
db.customers.getIndexes().forEach(function(idx) {
    print("  - " + idx.name + ": " + JSON.stringify(idx.key));
});

print("\nTransactions indexes:");
db.transactions.getIndexes().forEach(function(idx) {
    print("  - " + idx.name + ": " + JSON.stringify(idx.key));
});

print("\nBlacklist locations indexes:");
db.blacklist_locations.getIndexes().forEach(function(idx) {
    print("  - " + idx.name + ": " + JSON.stringify(idx.key));
});

print("\nHolidays indexes:");
db.holidays.getIndexes().forEach(function(idx) {
    print("  - " + idx.name + ": " + JSON.stringify(idx.key));
});

// Check balancer status (Atlas manages this)
print("\n7. Balancer Status:");
print("===================");
try {
    print("Balancer running: " + sh.isBalancerRunning());
    print("Balancer state: " + sh.getBalancerState());
} catch (e) {
    print("  (Atlas manages balancer automatically)");
}

print("\n=== Verification Complete ===");
