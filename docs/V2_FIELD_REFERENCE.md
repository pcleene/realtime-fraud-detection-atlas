# V2 Field Reference — Internal Only (NOT for Regional Bank)

This document maps every masked field name from RegionalBank's specification to its inferred meaning. This is the single source of truth for Claude Code when implementing the V2 scoring engine. **This file must never be shared externally.**

---

## Core Transaction Fields (pot_dataset)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID (CIF number) | string | Primary key linking to all master tables. ~35.8M customers in production. |
| `transaction_id_masked` | Transaction ID | UUID string | Unique per row. |
| `service` | Service code | int | Numeric codes (5, 12, 16, 17, 30–38, 46). Livin app service types. |
| `service_name` | Service category | char | Single-letter (A–Z). Y = transfers, X = bill pay, N = top-up, etc. |
| `z1` | Transaction timestamp | datetime | Current transaction time. |
| `b1` | Source account number | string | ~306 unique. Sender's bank account ("acctno" in spec). |
| `c1` | Source account name | string | Partially masked holder name. |
| `b2` | Destination account number | string | ~24,760 unique. Beneficiary account. |
| `c2` | Destination account name | string | ~23,451 unique. Beneficiary name. |
| `d2` | Destination bank name | string | "BRI", "BTN", "RegionalBank", "Bank BCA", etc. |
| `at3` | Transaction amount | decimal | Core amount field used in most rules. IDR. |
| `tp` | Transaction purpose code | int | Values: 0, 300, 55555. Transfer purpose/category. |
| `at7` | Transaction fee | decimal | Admin charge (0, 1000, 2500, etc.). |
| `flag_fraud` | Fraud label | string | "TRX FRAUD" or "TRX NON FRAUD". Ground truth. |
| `status` | Transaction status | string | SUCCESS, FAILED, PENDING, EXPIRED, REJECT. |
| `is_financial` | Is financial transaction | int | Binary 0/1. Monetary vs non-monetary (inquiry). |
| `n2` | Merchant/beneficiary description | string | Used in var_5 suspicious merchant check. |

## Customer Master (pot_master_id)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID | string | Same CIF. Primary key. |
| `e1` | Email address | string | Format: uuid@test.com in sample. Checked against pot_be (var_3). |
| `f1` | Phone number | string | Indonesian mobile (628...). Checked against pot_bmn (var_7). |
| `r` | Registration date | datetime | Account opening / registration date. |

## Customer Segment (pot_master_id_sg)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID | string | |
| `y` | Customer segment | string | PB = Prioritas Banking, PL = Privilege/Regular, PR = Premium. |

## Device Profile (pot_master_id_dp)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID | string | |
| `h1` | Device model | string | e.g. "samsung SM-A805F", "OPPO CPH2269". Checked in var_4, var_25. |
| `r` | Device registered date | datetime | When device was registered/paired. |

## Provisioning Log (pot_master_id_pl)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID | string | |
| `pt` | Provisioning time | datetime | Device/app activation on Livin. Used in var_26, var_19. |

## Card Change Log (pot_master_id_ccl)

| Masked | Inferred Meaning | Type | Notes |
|--------|-----------------|------|-------|
| `a1` | Customer ID | string | |
| `w1` | Card change type | int | Values 1-5. Card lifecycle event type. |
| `w2` | Card change time | datetime | When card event happened. Used in var_24. |

## Derived / Rolling Fields (not stored as table columns — computed at scoring time)

| Masked | Inferred Meaning | Derivation |
|--------|-----------------|------------|
| `z2` | Previous transaction time | Last z1 for this customer. |
| `dif_z1_z2` | Time gap (seconds) | z1 - z2. Used in var_8. |
| `diff_d_z` | Day gap | Calendar-day difference. Used in var_10. |
| `at4` | Previous amount | Last at3. Used in var_17, var_21. |
| `at5` | Second previous amount | Second-last at3. |
| `at3_sum` | Amount sum in window | Sum of at3 within time window. var_18, var_29. |
| `at6` | Amount std dev | Standard deviation of at3 in window. var_28. |
| `z3` | Typical txn hour (lower) | Statistical lower bound of customer's transaction hours. var_13. |
| `z4` | Typical txn hour (upper) | Statistical upper bound. var_13. |
| `z5` / `l_pt` | Last provisioning time | Last pt value. var_26. |
| `w3` | Last card change time | Last w2 value. var_24. |
| `bl` | Account balance | Running balance from pot_rbl. var_15, var_18, var_19. |

## Blacklist / Lookup Tables

| Table | Key Column(s) | Inferred Purpose | Production Size | Used By |
|-------|--------------|-----------------|-----------------|---------|
| `pot_bf` | `b23` | Blacklisted destination accounts | 470K | var_1 |
| `pot_bf24` | `b23`, `a23`, `b13` | 24h fraud cascade accounts | 49K | var_2 |
| `pot_be` (pot_ebl) | `e13` | Blacklisted emails | small (~100) | var_3 |
| `pot_rtd` | `h13` | Risky device models | 3.6M | var_4 |
| `pot_sm` | `n23` | Suspicious merchant name patterns | 132K | var_5 |
| `pot_anj` | `j23` | Gambling-affiliated accounts | 470K | var_6 |
| `pot_bmn` | `f13` | Blacklisted phone numbers | 35.8M | var_7 |
| `pot_pp` | `q2`, `p2` | Online loan providers (name, account) | 1.7K | var_9 |
| `pot_sl` | `service`, `x` | Per-service transaction limits | 13 rows | var_12 |
| `pot_va` | `service`, `at1`, `at2` | Per-service amount thresholds (lower, upper) | 28 in sample | var_14 |
| `pot_ta` | `a1`, `service_ever` | Services ever used by customer | 35.8M | var_11 |
| `pot_nb` | `a1`, `b24`, `c24`, `service`, `service_name` | Customer's known beneficiaries | 450M | var_22 |
| `pot_cb` | `a13`, `c23` | Compliance/watchlist accounts | 1M | var_23 |
| `pot_rkd` | `h23` | High-risk device models | 3.6M | var_25 |
| `pot_btv` | `a1`, `av1` | Per-customer amount volatility threshold | 35.8M | var_28 |
| `pot_btvs` | `a1`, `av2` | Per-customer cumulative sum threshold | 35.8M | var_29 |

## Supplementary Transaction Tables

| Table | Columns | Inferred Purpose | Production Size |
|-------|---------|-----------------|-----------------|
| `pot_i` | `a1, b1, c1, b2, c2, at3, z1` | Incoming transactions to customer. var_9 loan detection. | 1.34B |
| `pot_rbl` | `a1, b1, z1, c_d, at3, bl` | Running balance ledger. `c_d` = Credit/Debit, `bl` = balance after. var_15, var_18, var_19. | 1.34B |

## All 31 Rules — Quick Reference

| Rule | Category | What It Checks | Data Sources | Weight |
|------|----------|---------------|-------------|--------|
| var_1 | Blacklist | Destination account (`b2`/`c2`) on fraud blacklist | pot_bf (in-memory) | 15 |
| var_2 | Blacklist | Customer involved in confirmed fraud in last 24h | pot_bf24 (in-memory) | 15 |
| var_3 | Blacklist | Customer's email (`e1`) on blacklist | pot_be → pre-computed flag | 10 |
| var_4 | Device | Customer's device (`h1`) on risky device list | pot_rtd → pre-computed flag | 5 |
| var_5 | Blacklist | Merchant/beneficiary name (`n2`) suspicious | pot_sm (in-memory) | 10 |
| var_6 | Blacklist | Destination account linked to gambling | pot_anj (in-memory) | 10 |
| var_7 | Blacklist | Customer's phone (`f1`) on blacklist | pot_bmn → pre-computed flag | 10 |
| var_8 | Velocity | Time gap between transactions (seconds) < threshold | Rolling: z1_prev on customer | 8 |
| var_9 | Behavioral | Received online loan → rapid outflow | pot_pp (in-memory) + pot_i_recent on customer | 10 |
| var_10 | Velocity | Day gap between transactions < threshold | Rolling: z1_prev on customer | 5 |
| var_11 | Behavioral | First time using this service | service_ever on customer | 3 |
| var_12 | Amount | Amount vs service transaction limit | pot_sl (in-memory) | 5 |
| var_13 | Velocity | Transaction outside usual hours (z3–z4) | z3, z4 on customer | 5 |
| var_14 | Amount | Amount above historical avg for service | pot_va (in-memory) | 5 |
| var_15 | Amount | Amount / balance ratio too high | bl on customer | 8 |
| var_16 | Pattern | Repetitive/sequential amount pattern | at3_recent on customer | 5 |
| var_17 | Amount | Sudden amount spike (at3/at4 ratio) | at3_prev on customer | 5 |
| var_18 | Amount | Cumulative amount in window vs balance | at3_sum + bl on customer | 8 |
| var_19 | Amount | Post-provisioning cumulative vs balance | at3_sum + bl + pt_latest on customer | 8 |
| var_20 | Pattern | Same exact amount repeated N times | at3_recent on customer | 5 |
| var_21 | Amount | Sudden amount drop (at3/at4 ratio) | at3_prev on customer | 3 |
| var_22 | Merchant | Unknown beneficiary (not in known list) | b24_list on customer + overflow | 5 |
| var_23 | Blacklist | Destination on compliance watchlist | pot_cb (in-memory) | 10 |
| var_24 | Velocity | Transaction within window of card change | w2_latest on customer | 8 |
| var_25 | Device | Customer's device on high-risk list | pot_rkd → pre-computed flag | 5 |
| var_26 | Velocity | Transaction within window of provisioning | pt_latest on customer | 8 |
| var_28 | Amount | Amount std dev exceeds customer threshold | at6 + av1 on customer | 5 |
| var_29 | Amount | Cumulative sum exceeds customer threshold | at3_sum + av2 on customer | 5 |
| var_30 | Pattern | Repetitive purpose code pattern | tp_recent on customer | 3 |
| var_31 | Pattern | Purpose-to-amount ratio anomaly | tp from transaction + at3 | 3 |

**Note:** var_27 is missing from RegionalBank's spec. We skip it.

## Customer Document Structure (V2 MongoDB)

The customer document embeds data from 12+ relational tables into one document. The field naming in the actual code uses the **masked names** (e1, f1, h1, etc.) — NOT the inferred names. The inferred names in this document are for developer understanding only.

```
Customer document fields → source table:
  _id                    → generated (CUST-{hex12})
  e1                     → pot_master_id.e1
  f1                     → pot_master_id.f1
  r                      → pot_master_id.r
  y                      → pot_master_id_sg.y
  pot_master_id_dp[]     → pot_master_id_dp (h1, r)
  flags.var_3            → pot_master_id.e1 ∈ pot_be?
  flags.var_4            → pot_master_id_dp.h1 ∈ pot_rtd?
  flags.var_7            → pot_master_id.f1 ∈ pot_bmn?
  flags.var_25           → pot_master_id_dp.h1 ∈ pot_rkd?
  av1                    → pot_btv.av1
  av2                    → pot_btvs.av2
  service_ever[]         → pot_ta.service_ever
  b24_count              → count of pot_nb rows for this a1
  b24_list[]             → pot_nb.b24 values (flat strings, max 500)
  rolling.z1_prev        → last z1 (maintained at scoring time)
  rolling.at3_prev       → last at3
  rolling.at3_prev2      → second-last at3
  rolling.pt_latest      → last pt from pot_master_id_pl
  rolling.w2_latest      → last w2 from pot_master_id_ccl
  rolling.w1_latest      → last w1 from pot_master_id_ccl
  rolling.z3             → typical txn hour lower bound
  rolling.z4             → typical txn hour upper bound
  rolling.bl             → latest balance from pot_rbl
  rolling.b1             → account number from pot_rbl
  rolling.at3_recent[]   → last 10 at3 values
  rolling.tp_recent[]    → last 10 tp values
  rolling.at3_sum        → sum of at3 in current window
  rolling.at6            → std dev of at3 in current window
  rolling.bl_window_start→ balance at start of window
  rolling.window_start   → window start time
  rolling.pot_i_recent[] → recent incoming loan txns (at3, z1, q2)
```
