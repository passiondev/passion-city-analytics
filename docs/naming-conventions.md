# Data Warehouse Naming Conventions

**Status:** Draft — pending team sign-off
**Owner:** Data & Analytics
**Applies to:** All Bronze, Silver, and Gold layer assets


---

## 1. Table Naming

All tables are prefixed by their medallion layer to make lineage and trust level immediately visible.

| Prefix | Layer | Purpose |
|---|---|---|
| `bronze_` | Raw / landing | Unmodified source data, as ingested |
| `silver_` | Cleansed / conformed | Deduplicated, typed, business-rule-applied data |
| `gold_` | Curated / presentation | Aggregated, modeled data for reporting & BI |

**Pattern:**
```
<layer>_<source_or_domain>_<entity>[_<qualifier>]
```

**Examples:**
- `bronze_salesforce_accounts`
- `silver_crm_customers`
- `gold_finance_monthly_revenue`

**Rules:**
- All lowercase, words separated by underscores (`snake_case`).
- No abbreviations unless they're already standard across the org (e.g., `crm`, `erp`).
- Domain/source name comes before entity name (`silver_crm_customers`, not `silver_customers_crm`).
- Avoid pluralization inconsistency — pick one convention (recommend plural for entity tables: `customers`, `orders`) and apply it everywhere.
- Fact tables in Gold should be prefixed with `fct_` after the layer prefix; dimension tables with `dim_`.
  - `gold_fct_orders`
  - `gold_dim_customer`

---

## 2. Column Naming

All column names use `snake_case` — lowercase words separated by underscores. No camelCase, no PascalCase, no spaces.

**Rules:**
- Descriptive, unabbreviated names preferred: `customer_id` not `cust_id`, `order_date` not `ord_dt`.
- Boolean columns prefixed with `is_`, `has_`, or `was_`: `is_active`, `has_subscription`, `was_refunded`.
- Avoid reserved SQL keywords as column names (`order`, `group`, `select`, etc.).
- Consistent units/currency should be reflected in the name where ambiguity is possible: `amount_usd`, `duration_seconds`.

---

## 3. Metric Naming

Metrics (measures used in Gold-layer reporting models) follow a consistent structure so they're self-describing in dashboards and semantic layers.

**Pattern:**
```
<aggregation>_<subject>[_<qualifier>]
```

**Examples:**
- `total_revenue`
- `avg_order_value`
- `count_active_users`
- `total_revenue_ytd`

**Rules:**
- Lead with the aggregation type: `total_`, `avg_`, `count_`, `min_`, `max_`, `pct_`.
- Time-bound qualifiers go at the end: `_mtd`, `_qtd`, `_ytd`, `_trailing_30d`.
- Ratios/percentages should make the relationship clear: `pct_orders_cancelled`, not `cancel_rate` (ambiguous denominator).
- One metric = one meaning. Don't reuse a metric name across models with different underlying logic.

---

## 4. Date & Key Field Conventions

### Date/time fields
| Suffix | Type | Example |
|---|---|---|
| `_date` | Calendar date (no time) | `order_date`, `signup_date` |
| `_at` | Full timestamp | `created_at`, `updated_at`, `deleted_at` |
| `_time` | Time-of-day only | `pickup_time` |

- Always store timestamps in UTC; if a local-time version is also needed, suffix it explicitly: `created_at_local`.
- Date keys in Gold dimensional models use `YYYYMMDD` integer surrogate keys where a date dimension join is needed: `date_key`.

### Key fields
| Suffix | Meaning | Example |
|---|---|---|
| `_id` | Natural/source-system identifier | `customer_id`, `order_id` |
| `_key` | Surrogate key generated in the warehouse | `customer_key`, `date_key` |
| `_sk` | Acceptable alternate for surrogate key if `_key` is ambiguous with business keys | `customer_sk` |

**Rules:**
- Primary keys of dimension tables are always `<entity>_key` (surrogate), with the source system's natural identifier preserved as `<entity>_id`.
- Foreign keys in fact tables match the referenced dimension's key name exactly (`customer_key` in `gold_fct_orders` matches `customer_key` in `gold_dim_customer`).
- Never overload a single `id` column across unrelated entities — always qualify with the entity name.

---

## 5. Storage & Ownership

This document lives in the GitHub repo at:
```
/docs/naming-conventions.md
```

Any proposed change to these conventions should go through a PR against this file, tagging the Data & Analytics team for review.


