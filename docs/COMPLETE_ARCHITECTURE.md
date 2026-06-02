# Cloud Migration Cost Estimation - Complete Architecture

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Details](#component-details)
4. [Data Flow](#data-flow)
5. [Agent System](#agent-system)
6. [Pricing Engine](#pricing-engine)
7. [Database Schema](#database-schema)
8. [Excel Processing](#excel-processing)
9. [Configuration & KPI Mappings](#configuration--kpi-mappings)
10. [Error Handling & Fallbacks](#error-handling--fallbacks)

---

## System Overview

### Purpose
Automated cloud migration cost estimation tool that:
- Reads Azure/GCP service configurations from Excel
- Maps to equivalent AWS services using LLM-powered SQL generation
- Calculates real-time AWS pricing (OnDemand, CSP, Spot)
- Generates comprehensive cost comparison reports

### Key Features
- ✅ Multi-cloud support (Azure, GCP → AWS)
- ✅ LLM-powered SQL generation (AWS Bedrock - Claude Sonnet 4)
- ✅ Prompt caching (90% token cost reduction)
- ✅ Real-time AWS pricing via API
- ✅ 6 CSP plans + Spot pricing
- ✅ Smart fallback (LLM normalizes unusual specs)
- ✅ Regional availability validation
- ✅ KPI-driven service mappings
- ✅ Incremental Excel output
- ✅ Token usage tracking
- ✅ AWS Calculator link generation

### Technology Stack
- **Language**: Python 3.11+
- **AI Framework**: AWS Bedrock (Claude Sonnet 4)
- **Database**: PostgreSQL (AWS RDS pricing data)
- **Cloud APIs**: AWS Pricing API, EC2 API, Savings Plans API
- **Excel**: openpyxl
- **Caching**: functools.lru_cache + Bedrock prompt caching
- **Automation**: Playwright (AWS Calculator links)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INPUT LAYER                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   Excel Input Reader          │
                    │   (utils/excel.py)            │
                    │   - Multi-sheet support       │
                    │   - Auto-detect provider      │
                    │   - Normalize columns         │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       ORCHESTRATION LAYER                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   Orchestrator Agent          │
                    │   (agents/orchestrator.py)    │
                    │   - Process each service      │
                    │   - Coordinate agents         │
                    │   - Incremental save          │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   SQL Generator Agent           │     │   Cost Agent                    │
│   (agents/sql_generator_agent)  │     │   (agents/cost_agent.py)        │
│   - LLM-powered SQL generation  │     │   - Real-time AWS pricing       │
│   - Prompt caching (90% off)    │     │   - CSP/Spot calculation        │
│   - PostgreSQL query execution  │     │   - Cost optimization           │
│   - Smart fallback (normalize)  │     │   - Weighted scoring            │
│   - Regional validation         │     │   - AWS Calculator links        │
└─────────────────┬───────────────┘     └─────────────────┬───────────────┘
                  │                                       │
                  ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                      │
└─────────────────────────────────────────────────────────────────────────┘
                  │                                       │
    ┌─────────────┴─────────────┐         ┌─────────────┴─────────────┐
    │   PostgreSQL Database     │         │   AWS Pricing APIs        │
    │   (utils/db.py)           │         │   (utils/cost_client.py)  │
    │   - EC2 pricing table     │         │   - Pricing API           │
    │   - RDS pricing table     │         │   - Savings Plans API     │
    │   - S3 pricing table      │         │   - EC2 Spot API          │
    │   - Lambda pricing table  │         │   - LRU cache             │
    │   - VPC pricing table     │         │                           │
    └───────────────────────────┘         └───────────────────────────┘
                                                        │
                                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         OUTPUT LAYER                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │   Excel Output Writer         │
                    │   (utils/excel.py)            │
                    │   - 5 sheets output           │
                    │   - Formatted tables          │
                    │   - Cost comparisons          │
                    └───────────────────────────────┘
```

---

## Component Details

### 1. Orchestrator Agent
**File**: `agents/orchestrator.py`

**Responsibilities**:
- Read input Excel file
- Process each service row sequentially
- Coordinate SQL Generator and Cost agents
- Handle errors gracefully
- Save results incrementally
- Generate console summary

**Key Functions**:
- `run_migration_pipeline()` - Main entry point
- `process_single_service()` - Process one service
- `process_all_services()` - Batch processing with incremental saves
- `print_summary()` - Console output

**Flow**:
```
1. Read Excel → List of service dicts
2. For each service:
   a. Call SQL Generator Agent → AWS matches
   b. Call Cost Agent → Pricing + optimization
   c. Save incrementally to Excel
3. Print summary to console
4. Final Excel write
```

### 2. SQL Generator Agent
**File**: `agents/sql_generator_agent.py`

**Responsibilities**:
- Generate SQL queries using LLM (AWS Bedrock - Claude Sonnet 4)
- Execute queries against PostgreSQL
- Smart fallback: LLM normalizes specs → retry SQL
- Return matched AWS instances

**Key Features**:
- **LLM-Powered SQL Generation**: Uses Claude to generate optimized SQL queries
- **Prompt Caching**: Caches system prompts (~3000 tokens) for 90% cost reduction
- **KPI-Aware**: LLM understands KPI mappings and only uses allowed fields
- **Schema-Driven**: LLM uses `data/schema.py` for correct table structure
- **Smart Fallback**: LLM fixes unusual specs (7 GiB → 8 GiB) and retries SQL
- **Regional Validation**: Validates instance availability per region
- **No Synthetic Matches**: All results come from database (never LLM-generated)

**Key Functions**:
- `generate_sql_with_llm()` - LLM generates SQL query from KPI + schema
- `execute_query()` - Run SQL, handle fallback
- `_llm_fallback()` - LLM normalizes specs, retry SQL
- `validate_instance_for_region()` - Check regional availability

**Two-Step Process**:

**STEP 1: LLM-Powered SQL Generation**
```
1. Load KPI mappings (allowed fields, tolerances, max results)
2. Load database schema (table structure, columns, types)
3. Build comprehensive prompt with:
   - Database schema (table, columns, types)
   - KPI configuration (allowed fields, tolerances)
   - Regional availability rules
   - Query examples and best practices
4. Call AWS Bedrock (Claude Sonnet 4) to generate SQL
5. Post-process SQL (fix LIKE patterns, add filters)
6. Execute SQL on PostgreSQL
7. Validate regional availability
8. Return matches
```

**STEP 2: Smart Fallback (if 0 matches)**
```
1. Call LLM to normalize unusual specs:
   - 7 GiB memory → 8 GiB (next higher standard)
   - 14 GiB memory → 16 GiB
   - 28 GiB memory → 32 GiB
2. Retry SQL with corrected specs
3. Return SQL results (never synthetic LLM matches)
```

**Prompt Caching**:
```python
# System prompt cached (~3000 tokens)
request_body = {
    "system": [
        {
            "type": "text",
            "text": system_prompt,  # Schema, KPI, rules, examples
            "cache_control": {"type": "ephemeral"}  # Cache this!
        }
    ],
    "messages": [{"role": "user", "content": user_message}]
}

# First call: 3000 input tokens (full price)
# Subsequent calls: 300 input tokens + 2700 cached (90% discount)
```

**Regional Availability Validation**:
```python
# Mumbai (ap-south-1) validation
MUMBAI_AVAILABLE_EC2_FAMILIES = {'t3', 't3a', 'm5', 'm5a', 'm6i', 'c5', 'c6i', 'r5', 'r6i'}
MUMBAI_AVOID_SUFFIXES = {'gd', 'gn', 'dn'}  # Limited/no pricing

# Validate before returning matches
is_valid, warning = validate_instance_for_region(
    instance_type="m8i.large",
    region="ap-south-1",
    service_type="ec2"
)
# → (False, "⚠️ EC2 instance m8i.large may not be available in Mumbai")
```

**Example**:
```python
# Input: Azure VM with 7 GiB memory
result = generate_and_execute_sql(
    service_type="ec2",
    provider="azure",
    vcpus=2,
    memory_gib=7,  # Unusual spec
    region="Central India",
    use_llm_fallback=True  # Smart fallback enabled
)

# STEP 1: LLM generates SQL
# SELECT "instancetype" AS instance_type, CAST("vcpu" AS INTEGER) AS vcpus, "memory" AS memory_gib
# FROM ec2_pricing
# WHERE "instancetype" IS NOT NULL
#   AND CAST("vcpu" AS INTEGER) BETWEEN 2 AND 2
#   AND "memory" LIKE '%7 GiB%'
#   AND "regioncode" = 'ap-south-1'
#   AND "operatingsystem" = 'Linux'
# ORDER BY ABS(CAST("vcpu" AS INTEGER) - 2) ASC
# LIMIT 3

# Execute → 0 matches (7 GiB is unusual)

# STEP 2: LLM Fallback
# LLM: "7 GiB is non-standard. Round up to 8 GiB (next AWS size)"
# Retry SQL with memory LIKE '%8 GiB%'
# Execute → 3 matches

# Output:
{
    "matches": [
        {"instance_type": "t3a.large", "vcpus": 2, "memory_gib": "8 GiB"},
        {"instance_type": "m6i.large", "vcpus": 2, "memory_gib": "8 GiB"},
        {"instance_type": "c6i.large", "vcpus": 2, "memory_gib": "8 GiB"}
    ],
    "method": "LLM_FALLBACK",
    "notes": "Original SQL returned 0 matches. LLM normalized 7 GiB → 8 GiB. Retry SQL found 3 matches."
}
```

**Token Usage Tracking**:
```python
# Track all LLM calls
track_tokens(
    input_tokens=300,
    output_tokens=500,
    operation="sql_generation",
    model="claude-sonnet-4",
    cache_creation_tokens=3000,  # First call only
    cache_read_tokens=2700       # Subsequent calls
)

# Print summary at end
print_token_summary()
# ┌─────────────────┬────────┬─────────┬───────┬────────┐
# │ Operation       │ Calls  │ Input   │ Output│ Cost   │
# ├─────────────────┼────────┼─────────┼───────┼────────┤
# │ sql_generation  │ 28     │ 11,400  │ 14,000│ $0.15  │
# │ llm_fallback    │ 5      │ 2,100   │ 2,500 │ $0.03  │
# └─────────────────┴────────┴─────────┴───────┴────────┘
```

### 3. Cost Agent
**File**: `agents/cost_agent.py`

**Responsibilities**:
- Call AWS Pricing APIs for each match
- Calculate OnDemand, CSP (6 plans), Spot pricing
- Pick optimized instance (weighted scoring)
- Compare costs vs current provider

**Key Features**:
- **Real-time Pricing**: Calls AWS APIs (not estimates)
- **Comprehensive CSP**: All 6 combinations (1yr/3yr × no/partial/all upfront)
- **Spot Pricing**: For Shared tenancy EC2 instances
- **Weighted Scoring**: Cost (40%), Generation (30%), Family (30%)
- **Tenancy Validation**: RDS always Shared, T-family warning for Dedicated

**Key Functions**:
- `calculate_and_compare_costs()` - Main entry point
- `enrich_match_with_costs()` - Add pricing to one match
- `pick_optimised()` - Select best instance using weighted scoring
- `build_cost_comparison()` - Current vs AWS comparison

**Scoring Algorithm**:
```python
# Weighted scoring for best instance selection
cost_score = 1000.0 / monthly_cost  # Lower cost = higher score
gen_score = 10.0 if current_gen else 3.0
family_score = FAMILY_SCORES.get(family, 5.0)  # Regional availability

total_score = (
    cost_score * 0.4 +      # 40% weight on cost
    gen_score * 0.3 +       # 30% weight on generation
    family_score * 0.3      # 30% weight on family
)
```

**Example**:
```python
# Input: 3 AWS matches for Azure VM
matches = [
    {"instance_type": "t3a.large", "costs": {...}},
    {"instance_type": "m6i.large", "costs": {...}},
    {"instance_type": "c6i.large", "costs": {...}}
]

# Output: Best match based on weighted scoring
optimised = pick_optimised(matches)
# → t3a.large (lowest cost, current gen, widely available)
```

### 4. LLM Mapper (Fallback Tool)
**File**: `tools/llm_mapper.py`

**Responsibilities**:
- Normalize unusual specs to standard AWS specs
- Used by SQL Generator Agent when SQL returns 0 matches
- Returns corrected specs for SQL retry

**Key Features**:
- **Spec Normalization**: Maps unusual values to AWS standards
- **Region Mapping**: Converts Azure/GCP regions to AWS
- **Confidence Scoring**: Indicates reliability of mapping

**Example**:
```python
# Input: Unusual Azure VM specs
llm_result = llm_fallback_tool(
    service_type="ec2",
    current_provider="azure",
    vcpus=2,
    memory_gib=7,  # Unusual
    region="Central India"
)

# Output: Normalized specs
{
    "vcpus": 2,
    "memory_gib": 8,  # Rounded up to standard AWS size
    "aws_region": "Asia Pacific (Mumbai)",
    "suggested_instance_type": "t3a.large",
    "confidence": "high"
}
```

---

## Data Flow

### End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. INPUT: Excel file with Azure/GCP services                           │
│    - Virtual Machines, SQL Databases, Storage Accounts, etc.           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. EXCEL READER: Parse and normalize                                   │
│    - Auto-detect provider (Azure/GCP)                                  │
│    - Normalize column names (Size → instance_type)                     │
│    - Set defaults (storage_gb=100 for S3, OS=Linux)                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. ORCHESTRATOR: Process each service                                  │
│    For each service row:                                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4a. SQL GENERATOR AGENT         │   │ 4b. COST AGENT                  │
│ - Load KPI mappings             │   │ - For each AWS match:           │
│ - Load database schema          │   │   * Validate tenancy            │
│ - Build LLM prompt with:        │   │   * Call AWS Pricing API        │
│   * Schema structure            │   │   * Get OnDemand price          │
│   * KPI allowed fields          │   │   * Get 6 CSP plans             │
│   * Regional rules              │   │   * Get Spot price (if Shared)  │
│   * Query examples              │   │ - Pick optimized instance       │
│ - Call Bedrock (Claude) to      │   │   * Weighted scoring            │
│   generate SQL query            │   │   * Cost 40%, Gen 30%, Fam 30%  │
│ - Execute SQL on PostgreSQL     │   │ - Generate AWS Calculator link  │
│ - Validate regional availability│   │ - Compare vs current cost       │
│ - If 0 matches:                 │   │ - Return enriched results       │
│   * LLM normalizes specs        │   │                                 │
│   * Retry SQL with fixed specs  │   │                                 │
│ - Return AWS matches            │   │                                 │
└─────────────────────────────────┘   └─────────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. INCREMENTAL SAVE: Write to Excel after each service                 │
│    - Prevents data loss on errors                                      │
│    - Shows progress in real-time                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. OUTPUT: Excel file with 5 sheets                                    │
│    - Summary: One row per service, best match + savings + calc link    │
│    - All Matches: All AWS candidates with pricing                      │
│    - CSP Options: All 6 CSP plans + Spot per instance                  │
│    - Cost Comparison: Current vs AWS OnDemand vs Optimized             │
│    - Mapping Details: Parameters used for matching                     │
│                                                                          │
│ 7. CONSOLE OUTPUT: Summary table + token usage statistics              │
└─────────────────────────────────────────────────────────────────────────┘
```

### Detailed Service Processing Flow

```
Service Row: Azure VM (Standard_D2s_v3, 2 vCPU, 7 GiB, Central India)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SQL GENERATOR AGENT                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│ 1. Load KPI mappings:                                                   │
│    - Service: Virtual Machines → ec2                                    │
│    - Region: Central India → ap-south-1 (Asia Pacific Mumbai)          │
│    - Allowed fields: vcpu, memory, regioncode, operatingsystem          │
│    - Tolerances: vCPU ±0%, Memory ±0% (exact match)                    │
│    - Max results: 3                                                     │
│                                                                          │
│ 2. Load database schema:                                                │
│    - Table: ec2_pricing                                                 │
│    - Columns: instancetype, vcpu, memory, regioncode, operatingsystem   │
│    - Types: vcpu is TEXT (must CAST to INTEGER)                        │
│    - Memory format: "8 GiB", "16 GiB" (use LIKE pattern)               │
│                                                                          │
│ 3. Build LLM prompt:                                                    │
│    System Prompt (CACHED ~3000 tokens):                                │
│    - Database schema with column types                                  │
│    - KPI allowed fields (only use these in WHERE)                       │
│    - Regional availability rules (Mumbai: t3, m5, m6i, c5, c6i, r5, r6i)│
│    - Query examples and best practices                                  │
│    - JSON output format                                                 │
│                                                                          │
│    User Message (~300 tokens):                                          │
│    - Service type: ec2                                                  │
│    - Provider: Azure                                                    │
│    - vCPUs: 2, Memory: 7 GiB (unusual!)                                │
│    - Region: ap-south-1                                                 │
│    - OS: Linux, Tenancy: Shared                                         │
│                                                                          │
│ 4. Call AWS Bedrock (Claude Sonnet 4):                                 │
│    Request: Generate SQL query                                          │
│    Response: {                                                          │
│      "sql": "SELECT \"instancetype\" AS instance_type, ...",            │
│      "params": [2, 2, "%7 GiB%", "ap-south-1", "Linux", 2, 7.0, 3]    │
│    }                                                                    │
│    Token usage: 300 input + 2700 cached (90% discount!) + 500 output   │
│                                                                          │
│ 5. Post-process SQL:                                                    │
│    - Fix LIKE patterns: '%7 GiB%' → '%%7 GiB%%' (escape %)            │
│    - Add instancetype IS NOT NULL filter                                │
│    - Add instance_type alias to SELECT                                  │
│                                                                          │
│ 6. Execute SQL on PostgreSQL:                                           │
│    SELECT "instancetype" AS instance_type,                              │
│           CAST("vcpu" AS INTEGER) AS vcpus,                             │
│           "memory" AS memory_gib,                                       │
│           "regioncode", "operatingsystem", "tenancy"                    │
│    FROM ec2_pricing                                                     │
│    WHERE "instancetype" IS NOT NULL                                     │
│      AND "instancetype" != ''                                           │
│      AND CAST("vcpu" AS INTEGER) BETWEEN 2 AND 2                        │
│      AND "memory" LIKE '%%7 GiB%%'                                      │
│      AND "regioncode" = 'ap-south-1'                                    │
│      AND "operatingsystem" = 'Linux'                                    │
│    ORDER BY ABS(CAST("vcpu" AS INTEGER) - 2) ASC,                      │
│             ABS(CAST(REPLACE("memory", ' GiB', '') AS FLOAT) - 7) ASC  │
│    LIMIT 3                                                              │
│                                                                          │
│    Result: 0 rows (7 GiB is unusual, no AWS instances with 7 GiB)      │
│                                                                          │
│ 7. Smart Fallback (LLM normalizes specs):                              │
│    Call LLM: "Map 7 GiB to next higher standard AWS size"              │
│    LLM Response: {                                                      │
│      "vcpus": 2,                                                        │
│      "memory_gib": 8,  ← Normalized from 7 to 8                        │
│      "aws_region": "Asia Pacific (Mumbai)",                             │
│      "suggested_instance_type": "t3a.large",                            │
│      "confidence": "high"                                               │
│    }                                                                    │
│    Token usage: 300 input + 1100 cached + 200 output                   │
│                                                                          │
│ 8. Retry SQL with corrected specs:                                     │
│    WHERE "memory" LIKE '%%8 GiB%%'  ← Changed from 7 to 8              │
│                                                                          │
│    Result: 3 rows                                                       │
│    - t3a.large (2 vCPU, 8 GiB, General Purpose, Current Gen)           │
│    - m6i.large (2 vCPU, 8 GiB, General Purpose, Current Gen)           │
│    - c6i.large (2 vCPU, 8 GiB, Compute Optimized, Current Gen)         │
│                                                                          │
│ 9. Validate regional availability:                                     │
│    - t3a.large: ✅ Available in Mumbai (t3a in allowed list)           │
│    - m6i.large: ✅ Available in Mumbai (m6i in allowed list)           │
│    - c6i.large: ✅ Available in Mumbai (c6i in allowed list)           │
│                                                                          │
│ 10. Return result:                                                      │
│    {                                                                    │
│      "matches": [                                                       │
│        {"instance_type": "t3a.large", "vcpus": 2, "memory_gib": "8 GiB"},│
│        {"instance_type": "m6i.large", "vcpus": 2, "memory_gib": "8 GiB"},│
│        {"instance_type": "c6i.large", "vcpus": 2, "memory_gib": "8 GiB"} │
│      ],                                                                 │
│      "method": "LLM_FALLBACK",                                          │
│      "notes": "Original SQL returned 0 matches. LLM normalized 7 GiB → 8 GiB. Retry SQL found 3 matches.",│
│      "token_usage": {                                                   │
│        "sql_generation": {"input": 300, "cached": 2700, "output": 500},│
│        "llm_fallback": {"input": 300, "cached": 1100, "output": 200}   │
│      }                                                                  │
│    }                                                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ COST AGENT                                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ For each match, call AWS Pricing APIs:                                 │
│                                                                          │
│ Match 1: t3a.large (ap-south-1)                                         │
│ ├─ Validate tenancy: Shared ✅ (T family OK for Shared)                │
│ ├─ OnDemand: $0.0376/hr = $27.45/mo = $329.40/yr                       │
│ ├─ CSP 1yr No Upfront: $0.0263/hr = $19.20/mo (30% discount)           │
│ ├─ CSP 1yr Partial: $0.0244/hr = $17.81/mo (35% discount)              │
│ ├─ CSP 1yr All: $0.0233/hr = $17.01/mo (38% discount)                  │
│ ├─ CSP 3yr No Upfront: $0.0188/hr = $13.72/mo (50% discount)           │
│ ├─ CSP 3yr Partial: $0.0169/hr = $12.34/mo (55% discount)              │
│ ├─ CSP 3yr All: $0.0150/hr = $10.95/mo (60% discount) ← Best CSP       │
│ └─ Spot: $0.0113/hr = $8.25/mo (70% discount) ← Lowest cost            │
│                                                                          │
│ Match 2: m6i.large (ap-south-1)                                         │
│ ├─ OnDemand: $0.096/hr = $70.08/mo = $840.96/yr                        │
│ └─ ... (6 CSP plans + Spot)                                            │
│                                                                          │
│ Match 3: c6i.large (ap-south-1)                                         │
│ ├─ OnDemand: $0.085/hr = $62.05/mo = $744.60/yr                        │
│ └─ ... (6 CSP plans + Spot)                                            │
│                                                                          │
│ Weighted Scoring (Cost 40%, Generation 30%, Family 30%):               │
│ ├─ t3a.large:                                                           │
│ │  - Cost score: 1000/10.95 = 91.3 × 0.4 = 36.5                        │
│ │  - Gen score: 10.0 (current gen) × 0.3 = 3.0                         │
│ │  - Family score: 9.0 (t3a widely available) × 0.3 = 2.7              │
│ │  - Total: 42.2 ← WINNER                                              │
│ ├─ m6i.large:                                                           │
│ │  - Cost score: 1000/48.00 = 20.8 × 0.4 = 8.3                         │
│ │  - Gen score: 10.0 × 0.3 = 3.0                                       │
│ │  - Family score: 7.0 (m6i available) × 0.3 = 2.1                     │
│ │  - Total: 13.4                                                        │
│ └─ c6i.large:                                                           │
│    - Cost score: 1000/42.00 = 23.8 × 0.4 = 9.5                         │
│    - Gen score: 10.0 × 0.3 = 3.0                                       │
│    - Family score: 7.0 × 0.3 = 2.1                                     │
│    - Total: 14.6                                                        │
│                                                                          │
│ Selected: t3a.large with CSP 3yr All Upfront ($10.95/mo)               │
│                                                                          │
│ Generate AWS Calculator Link:                                           │
│ ├─ Use Playwright to automate AWS Pricing Calculator                   │
│ ├─ Fill form: t3a.large, ap-south-1, Linux, Shared, 730 hrs/mo         │
│ ├─ Generate shareable link                                              │
│ └─ Link: https://calculator.aws/#/estimate?id=abc123...                │
│                                                                          │
│ Cost Comparison:                                                        │
│ ├─ Current (Azure Standard_D2s_v3): $50.00/mo                          │
│ ├─ AWS OnDemand (t3a.large): $27.45/mo (45% savings)                   │
│ └─ AWS Optimized (t3a.large CSP 3yr All): $10.95/mo (78% savings) ✅   │
│                                                                          │
│ OUTPUT:                                                                 │
│   {                                                                     │
│     "aws_matches": [ ... 3 matches with costs ... ],                   │
│     "best_match": {                                                     │
│       "instance_type": "t3a.large",                                     │
│       "vcpus": 2,                                                       │
│       "memory_gib": "8 GiB",                                            │
│       "regioncode": "ap-south-1"                                        │
│     },                                                                  │
│     "optimised": {                                                      │
│       "instance_type": "t3a.large",                                     │
│       "plan_label": "CSP 3yr All Upfront",                              │
│       "monthly_usd": 10.95,                                             │
│       "annual_usd": 131.40,                                             │
│       "discount_percent": 60,                                           │
│       "reasoning": "Best match based on weighted scoring..."            │
│     },                                                                  │
│     "calculator_link": "https://calculator.aws/#/estimate?id=abc123",  │
│     "comparison": {                                                     │
│       "current_provider": { "monthly_usd": 50.00, "annual_usd": 600.00 },│
│       "aws_ondemand": { "monthly_usd": 27.45, "annual_usd": 329.40 },  │
│       "aws_optimised": { "monthly_usd": 10.95, "annual_usd": 131.40 }, │
│       "savings": {                                                      │
│         "monthly_usd": 39.05,                                           │
│         "annual_usd": 468.60,                                           │
│         "percent": 78.1,                                                │
│         "verdict": "🟢 Great savings"                                   │
│       }                                                                 │
│     }                                                                   │
│   }                                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Agent System

### Strands Framework
The project uses **Strands** (AWS Bedrock) for AI agent orchestration.

**Key Concepts**:
- **Agents**: Autonomous AI components with specific responsibilities
- **System Prompts**: Define agent behavior and expertise
- **Tool Calling**: Agents can call Python functions
- **Multi-step Reasoning**: Agents can plan and execute complex workflows

### Agent Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR AGENT                              │
│                         (Top-level coordinator)                         │
│                                                                          │
│  System Prompt: "You are the orchestrator for cloud migration..."      │
│  Responsibilities:                                                      │
│  - Coordinate full pipeline                                             │
│  - Handle errors gracefully                                             │
│  - Ensure every service gets processed                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│   SQL GENERATOR AGENT           │   │   COST AGENT                    │
│   (Mapping specialist)          │   │   (FinOps specialist)           │
│                                 │   │                                 │
│ System Prompt:                  │   │ System Prompt:                  │
│ "You generate SQL queries       │   │ "You are a FinOps expert        │
│  using KPI mappings..."         │   │  specializing in AWS cost       │
│                                 │   │  optimization..."               │
│ Responsibilities:               │   │                                 │
│ - Generate SQL from KPI         │   │ Responsibilities:               │
│ - Execute queries               │   │ - Calculate costs               │
│ - Handle fallback               │   │ - Identify optimized option     │
│                                 │   │ - Compare with current cost     │
└─────────────────────────────────┘   └─────────────────────────────────┘
```

### Agent Communication

Agents communicate through structured dictionaries:

```python
# SQL Generator Agent Output
{
    "matches": [
        {"instance_type": "t3a.large", "vcpus": 2, "memory_gib": 8, ...},
        {"instance_type": "m6i.large", "vcpus": 2, "memory_gib": 8, ...}
    ],
    "match_count": 2,
    "method": "LLM_FALLBACK",
    "notes": "LLM normalized 7 GiB → 8 GiB. Retry SQL found 2 matches."
}

# Cost Agent Output
{
    "aws_matches": [...],  # Matches with costs attached
    "best_match": {"instance_type": "t3a.large", ...},
    "optimised": {"monthly_usd": 10.95, "plan_label": "CSP 3yr All", ...},
    "costs": {"ondemand": {...}, "best_savings_plan": {...}, "spot": {...}},
    "comparison": {"savings": {"monthly_usd": 39.05, "percent": 78.1}}
}
```

---

## Pricing Engine

### AWS Pricing APIs

The system uses 3 AWS APIs for real-time pricing:

1. **AWS Pricing API** (`boto3.client('pricing')`)
   - OnDemand pricing for EC2, RDS, S3, Lambda, VPC
   - Region: `us-east-1` (global pricing endpoint)
   - Caching: `@lru_cache(maxsize=256)`

2. **AWS Savings Plans API** (`boto3.client('savingsplans')`)
   - Compute Savings Plan rates
   - All 6 combinations: 1yr/3yr × no/partial/all upfront
   - Returns: hourly rate, upfront fee, offering ID

3. **AWS EC2 API** (`boto3.client('ec2')`)
   - Spot instance pricing
   - Region-specific (must use regional endpoint)
   - Returns: current spot price (fluctuates)

### Pricing Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. ONDEMAND PRICING                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│ get_ondemand_price(instance_type, region, os, tenancy)                 │
│ ├─ Call: pricing_client.get_products(ServiceCode="AmazonEC2", ...)     │
│ ├─ Filter: instanceType, location, operatingSystem, tenancy            │
│ ├─ Parse: OnDemand terms → pricePerUnit                                │
│ └─ Return: $0.0376/hr                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. COMPUTE SAVINGS PLAN PRICING                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ get_csp_rate(instance_type, region, plan_type)                         │
│ ├─ Call: savingsplans_client.describe_savings_plans_offering_rates()   │
│ ├─ Filter: instanceType, region, savingsPlanType, paymentOption        │
│ ├─ Iterate: Find best rate for this instance                           │
│ └─ Return: (hourly_rate, upfront_fee, offering_id)                     │
│                                                                          │
│ For each plan type:                                                     │
│ ├─ 1yr_no_upfront: $0.0263/hr, $0 upfront                              │
│ ├─ 1yr_partial_upfront: $0.0244/hr, $150 upfront                       │
│ ├─ 1yr_all_upfront: $0.0233/hr, $204 upfront                           │
│ ├─ 3yr_no_upfront: $0.0188/hr, $0 upfront                              │
│ ├─ 3yr_partial_upfront: $0.0169/hr, $450 upfront                       │
│ └─ 3yr_all_upfront: $0.0150/hr, $394 upfront                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. SPOT PRICING (Shared tenancy only)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│ get_spot_price(instance_type, region)                                  │
│ ├─ Call: ec2_client.describe_spot_price_history()                      │
│ ├─ Filter: instanceType, productDescription="Linux/UNIX"               │
│ └─ Return: $0.0113/hr (current spot price)                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. COST CALCULATION                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│ calculate_csp_discount(od_hourly, csp_hourly, upfront_fee, plan_type)  │
│                                                                          │
│ Effective hourly = csp_hourly + (upfront_fee / plan_hours)             │
│ Monthly cost = effective_hourly × 730 hours                            │
│ Annual cost = monthly_cost × 12                                         │
│ Discount % = ((od_hourly - effective_hourly) / od_hourly) × 100        │
│                                                                          │
│ Example (CSP 3yr All Upfront):                                          │
│ ├─ OnDemand: $0.0376/hr                                                │
│ ├─ CSP rate: $0.0150/hr                                                │
│ ├─ Upfront: $394                                                       │
│ ├─ Amortized upfront: $394 / (3 × 365 × 24) = $0.0150/hr              │
│ ├─ Effective hourly: $0.0150 + $0.0150 = $0.0300/hr                   │
│ ├─ Monthly: $0.0300 × 730 = $21.90/mo                                 │
│ └─ Discount: 60%                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Caching Strategy

All pricing API calls use `@lru_cache` to avoid redundant API calls:

```python
@lru_cache(maxsize=256)
def get_ondemand_price(instance_type, region, os, tenancy):
    # Cache key: (instance_type, region, os, tenancy)
    # Cache hit: Return cached price (no API call)
    # Cache miss: Call API, cache result, return price
    ...

@lru_cache(maxsize=256)
def get_csp_rate(instance_type, region, plan_type):
    # Cache key: (instance_type, region, plan_type)
    ...

@lru_cache(maxsize=256)
def get_spot_price(instance_type, region):
    # Cache key: (instance_type, region)
    # Note: Spot prices fluctuate, cache for session only
    ...
```

**Benefits**:
- Reduces API calls by 90%+
- Faster processing (cached calls are instant)
- Avoids AWS rate limiting
- Works across multiple services with same instance type

**Cache Lifetime**:
- Session-based (cleared on script restart)
- Suitable for batch processing
- Spot prices may be slightly stale (acceptable for estimation)

---

## Database Schema

### PostgreSQL Tables

The system uses 5 PostgreSQL tables with AWS pricing data:

#### 1. EC2 Pricing Table
```sql
CREATE TABLE ec2_pricing (
    sku TEXT,
    instancetype TEXT,
    instancefamily TEXT,
    vcpu TEXT,
    memory TEXT,
    location TEXT,
    regioncode TEXT,
    tenancy TEXT,
    operatingsystem TEXT,
    currentgeneration TEXT,
    networkperformance TEXT,
    physicalprocessor TEXT,
    storage TEXT,
    -- ... 80+ columns total
);

-- Indexes for fast queries
CREATE INDEX idx_ec2_instance ON ec2_pricing(instancetype);
CREATE INDEX idx_ec2_vcpu ON ec2_pricing(vcpu);
CREATE INDEX idx_ec2_region ON ec2_pricing(regioncode);
```

**Key Fields**:
- `instancetype`: e.g., "t3a.large", "m6i.xlarge"
- `vcpu`: e.g., "2", "4", "8" (stored as TEXT)
- `memory`: e.g., "8 GiB", "16 GiB" (stored as TEXT)
- `regioncode`: e.g., "ap-south-1", "us-east-1"
- `operatingsystem`: "Linux", "Windows", "RHEL", "SUSE"
- `tenancy`: "Shared", "Dedicated", "Host"
- `currentgeneration`: "Yes", "No"

**Query Example**:
```sql
SELECT instancetype, vcpu, memory, location
FROM ec2_pricing
WHERE CAST(vcpu AS INTEGER) BETWEEN 2 AND 2
  AND memory LIKE '%8 GiB%'
  AND regioncode = 'ap-south-1'
  AND operatingsystem = 'Linux'
  AND tenancy = 'Shared'
  AND currentgeneration = 'Yes'
ORDER BY ABS(CAST(vcpu AS INTEGER) - 2) ASC
LIMIT 3;
```

#### 2. RDS Pricing Table
```sql
CREATE TABLE rds_pricing (
    sku TEXT,
    instancetype TEXT,
    instancefamily TEXT,
    vcpu TEXT,
    memory TEXT,
    location TEXT,
    regioncode TEXT,
    databaseengine TEXT,
    deploymentoption TEXT,
    currentgeneration TEXT,
    -- ... 40+ columns total
);
```

**Key Fields**:
- `databaseengine`: "MySQL", "PostgreSQL", "MariaDB", "Oracle", "SQL Server"
- `deploymentoption`: "Single-AZ", "Multi-AZ"

#### 3. S3 Pricing Table
```sql
CREATE TABLE s3_pricing (
    sku TEXT,
    location TEXT,
    regioncode TEXT,
    storageclass TEXT,
    volumetype TEXT,
    availability TEXT,
    durability TEXT,
    -- ... 20+ columns total
);
```

**Key Fields**:
- `storageclass`: "General Purpose", "Infrequent Access", "Archive"

#### 4. Lambda Pricing Table
```sql
CREATE TABLE lambda_pricing (
    sku TEXT,
    location TEXT,
    regioncode TEXT,
    lambdamanagedinstancetype TEXT,
    -- ... 10+ columns total
);
```

#### 5. VPC Pricing Table
```sql
CREATE TABLE vpc_pricing (
    sku TEXT,
    location TEXT,
    regioncode TEXT,
    endpointtype TEXT,
    attachmenttype TEXT,
    -- ... 15+ columns total
);
```

### Schema Management

**File**: `data/schema.py`

Defines table structures programmatically:

```python
EC2_SCHEMA = {
    "table_name": "ec2_pricing",
    "columns": ["sku", "instancetype", "vcpu", ...],
    "matching_fields": ["vcpu", "memory", "regioncode", "operatingsystem"],
    "select_fields": ["instancetype", "vcpu", "memory", "location", ...]
}

# Helper functions
get_schema(service_type)        # Get full schema
get_table_name(service_type)    # Get table name
get_matching_fields(service_type)  # Get fields for WHERE clause
get_select_fields(service_type)    # Get fields for SELECT clause
```

**Usage in SQL Generator**:
```python
schema = get_schema("ec2")
table_name = schema["table_name"]  # "ec2_pricing"
select_fields = schema["select_fields"]  # ["instancetype", "vcpu", ...]

sql = f"SELECT {', '.join(select_fields)} FROM {table_name} WHERE ..."
```

---

## Excel Processing

### Input Excel Format

**Supported Formats**:
1. **Single-sheet**: All services in one sheet
2. **Multi-sheet**: Separate sheets per service type (Azure export format)

**Column Mapping**:
```python
# Azure columns → Normalized columns
"Size" → "instance_type"
"Name" → "service_name"
"Location" → "region"
"SKU" → "instance_type"
"Capacity" → "vcpus"
"DataMaxSizeGB" → "storage_gb"
"OSName" → "operating_system"
```

**Auto-Detection**:
- Provider: From filename ("azure" → Azure, "gcp" → GCP)
- Service Type: From sheet name ("Virtual Machines" → ec2)
- Defaults: storage_gb=100 for S3, OS=Linux, tenancy=Shared

**Example Input**:
```
Sheet: Virtual Machines
┌──────────────┬────────────────┬──────┬────────┬──────────────┬──────┐
│ Name         │ Size           │ vCPU │ Memory │ Location     │ OS   │
├──────────────┼────────────────┼──────┼────────┼──────────────┼──────┤
│ web-server-1 │ Standard_D2s_v3│ 2    │ 8      │ Central India│ Linux│
│ db-server-1  │ Standard_E4s_v3│ 4    │ 32     │ Central India│ Linux│
└──────────────┴────────────────┴──────┴────────┴──────────────┴──────┘

Sheet: SQL DBs
┌──────────────┬────────┬──────────┬──────────────┬────────┐
│ Name         │ SKU    │ Capacity │ DataMaxSizeGB│ Location│
├──────────────┼────────┼──────────┼──────────────┼────────┤
│ prod-db      │ GP_Gen5│ 4        │ 100          │ Central │
└──────────────┴────────┴──────────┴──────────────┴────────┘
```

### Output Excel Format

**5 Sheets**:

#### Sheet 1: Summary
One row per input service with best AWS match and savings.

**Columns**:
- Service Name, Type, Provider
- Current Instance/Config, Current Monthly Cost
- Recommended AWS Instance, AWS Region
- AWS OnDemand (Hourly, Monthly, Annual)
- Optimized Plan, Optimized (Monthly, Annual)
- Savings (Monthly, Annual, %)
- Match Method, Notes

**Highlighting**:
- Green: Positive savings
- Orange: Higher cost on AWS

#### Sheet 2: All Matches
All AWS candidates per service with full pricing.

**Columns**:
- Service Name, Input vCPUs, Input Memory
- AWS Instance Type, AWS vCPUs, AWS Memory
- Region, Tenancy, OS
- OnDemand (Hourly, Monthly, Annual)
- Best Savings Plan, Plan (Monthly, Annual), Discount %
- Spot (Hourly, Monthly, Annual), Spot Discount %
- Recommended (✅ Best), Match Method

**Highlighting**:
- Light blue: All matches
- Light green: Best match
- Light yellow: Spot pricing

#### Sheet 3: CSP Options
All 6 CSP plans + Spot pricing per instance.

**Columns**:
- Service Name, AWS Instance Type, Region
- Plan Term (1YR/3YR/SPOT)
- Payment Option (No/Partial/All Upfront, Variable)
- Upfront Fee, Hourly Rate, Monthly Cost, Annual Cost
- Discount %, Monthly Savings, Annual Savings
- vs OnDemand Monthly, Recommended (✅ Best / ⚡ Spot)

**Highlighting**:
- Light green: Best CSP plan
- Light yellow: Spot pricing

#### Sheet 4: Cost Comparison
Side-by-side comparison: Current vs AWS OnDemand vs AWS Optimized.

**Columns**:
- Service, Current Provider, Current Instance
- Current (Monthly, Annual)
- AWS OnDemand (Hourly, Monthly, Annual)
- AWS Optimized Plan, AWS Optimized (Monthly, Annual)
- Savings (Monthly, Annual, %)
- Cost Trend (🟢/🟡/⚪/🔴), Recommendation

**Totals Row**:
- Sum of all costs
- Total savings (monthly, annual, %)

#### Sheet 5: Mapping Details
Parameters used for matching and comparison.

**Columns**:
- Service Name
- Input: Service Type, Provider, Instance Type, vCPUs, Memory, Storage, Region, OS, Tenancy
- AWS: Instance Type, vCPUs, Memory, Region, OS, Tenancy
- Mapping Method, KPI Used, SQL Query Used, Notes

**Highlighting**:
- Green: KPI-based mapping
- Orange: LLM-based mapping

---

## Configuration & KPI Mappings

### KPI Mappings File
**File**: `data/kpi_mappings.json`

Central configuration for all service mappings.

**Structure**:
```json
{
  "version": "1.0",
  "service_name_mappings": {...},
  "region_mappings": [...],
  "mapping_fields": {...},
  "instance_mappings": {...},
  "storage_class_mappings": {...}
}
```

#### 1. Service Name Mappings
Maps Azure/GCP service names to AWS service types.

```json
"service_name_mappings": {
  "ec2": {
    "aws_names": ["EC2", "Elastic Compute Cloud"],
    "gcp_names": ["Compute Engine", "GCE"],
    "azure_names": ["Virtual Machines", "Azure VM", "VM"]
  },
  "s3": {
    "aws_names": ["S3", "Simple Storage Service"],
    "gcp_names": ["Cloud Storage", "GCS"],
    "azure_names": ["Blob Storage", "Storage Acc"]
  },
  "rds": {
    "aws_names": ["RDS", "Relational Database Service"],
    "gcp_names": ["Cloud SQL", "AlloyDB"],
    "azure_names": ["Azure SQL Database", "SQL DBs", "PostgreSQL Flexible"]
  }
}
```

**Usage**:
```python
# Input: "Virtual Machines" (Azure sheet name)
service_type = normalize_service_name("Virtual Machines", "Azure")
# Output: "ec2"
```

#### 2. Region Mappings
Maps Azure/GCP regions to AWS regions.

```json
"region_mappings": [
  {
    "aws_region_code": "ap-south-1",
    "aws_region_name": "Asia Pacific (Mumbai)",
    "azure_region": "Central India",
    "azure_programmatic_name": "centralindia",
    "gcp_region": "asia-south1"
  },
  {
    "aws_region_code": "us-east-1",
    "aws_region_name": "US East (N. Virginia)",
    "azure_region": "East US",
    "gcp_region": "us-east1"
  }
]
```

**Usage**:
```python
# Input: "Central India" (Azure region)
aws_region = normalize_region_from_kpi("Azure", "Central India")
# Output: "Asia Pacific (Mumbai)"
```

#### 3. Mapping Fields
Defines which fields to use for SQL queries per service type.

```json
"mapping_fields": {
  "ec2": {
    "description": "Fields for mapping to AWS EC2",
    "required_fields": [
      "region", "instance_type", "vcpu", "memory", 
      "operating_system", "storage"
    ],
    "field_aliases": {
      "vcpu": ["vcpu", "vcpus", "cpu", "cores"],
      "memory": ["memory", "memory_gib", "ram"],
      "region": ["region", "location", "zone"]
    }
  },
  "s3": {
    "required_fields": ["region", "storage_class", "storage_amount"]
  },
  "rds": {
    "required_fields": ["database_engine", "region", "storage"]
  }
}
```

**Usage**:
```python
# SQL Generator checks allowed fields
allowed_fields = KPI_ALLOWED_FIELDS.get("ec2")
# → {"region", "instance_type", "vcpu", "memory", "operating_system", "storage"}

# Only these fields are used in WHERE clause
if "vcpu" in allowed_fields:
    conditions.append('CAST("vcpu" AS INTEGER) BETWEEN %s AND %s')
```

#### 4. Storage Class Mappings
Maps Azure/GCP storage SKUs to AWS S3 storage classes.

```json
"storage_class_mappings": {
  "s3": {
    "azure_to_aws": {
      "standard_lrs": "General Purpose",
      "premium_lrs": "High Performance"
    },
    "gcp_to_aws": {
      "standard": "General Purpose",
      "nearline": "Infrequent Access",
      "coldline": "Archive"
    }
  }
}
```

**Usage**:
```python
# Input: Azure Storage Account with SKU "Standard_LRS"
aws_storage_class = get_storage_class_mapping("s3", "Azure", "Standard_LRS")
# Output: "General Purpose"
```

### Query Parameters

**File**: `utils/kpi_loader.py`

Helper functions to load KPI configurations:

```python
# Get tolerance for vCPU/memory matching
vcpu_tolerance, mem_tolerance = get_tolerance_for_service("ec2")
# → (0.0, 0.0) for exact match

# Get max results per query
max_results = get_max_results("ec2")
# → 3

# Check if current generation preferred
prefer_current = should_prefer_current_generation("ec2")
# → True
```

---

## Error Handling & Fallbacks

### Multi-Layer Fallback Strategy

```
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: SQL with Exact Specs                                          │
│ ├─ Generate SQL using input specs (e.g., 7 GiB memory)                 │
│ ├─ Execute against PostgreSQL                                          │
│ └─ If matches found → SUCCESS                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (0 matches)
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: LLM Normalization + SQL Retry                                 │
│ ├─ LLM analyzes unusual specs                                          │
│ ├─ LLM suggests next higher standard AWS specs                         │
│ ├─ Retry SQL with corrected specs                                      │
│ └─ If matches found → SUCCESS (with note)                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (still 0 matches)
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: Fallback Instance Families                                    │
│ ├─ Try alternative instance families known to be available             │
│ ├─ For 2vCPU/8GiB: try t3a.large, m6i.large, c6i.large                 │
│ └─ If any has valid pricing → SUCCESS (with fallback note)             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (still no valid pricing)
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: Graceful Failure                                              │
│ ├─ Log warning                                                          │
│ ├─ Return empty result with detailed notes                             │
│ └─ Continue processing next service (don't crash)                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Error Handling Examples

#### 1. Unusual Memory Size
```
Input: 7 GiB memory (non-standard)
Layer 1: SQL with 7 GiB → 0 matches
Layer 2: LLM normalizes to 8 GiB → SQL retry → 3 matches ✅
Result: t3a.large (2 vCPU, 8 GiB)
Note: "LLM normalized 7 GiB → 8 GiB. Retry SQL found 3 matches."
```

#### 2. Unavailable Instance in Region
```
Input: m8i.large in ap-south-1 (not available in Mumbai)
Layer 1: SQL → 1 match (m8i.large)
Layer 2: Pricing API → No pricing available
Layer 3: Try fallback families (t3a, m6i, c6i) → m6i.large has pricing ✅
Result: m6i.large (2 vCPU, 8 GiB)
Note: "Fallback used: m6i.large (original m8i.large not available in region)"
```

#### 3. Complete Failure
```
Input: Invalid specs or unsupported service
Layer 1: SQL → 0 matches
Layer 2: LLM → Unable to normalize
Layer 3: Fallback families → No valid pricing
Layer 4: Graceful failure ⚠️
Result: Empty match
Note: "No AWS instances found matching these specs in this region."
```

### Incremental Saving

To prevent data loss on errors:

```python
def process_all_services(services, output_path):
    results = []
    for idx, service in enumerate(services):
        result = process_single_service(service)
        results.append(result)
        
        # Save after EACH service
        write_output_xlsx(results, output_path)
        logger.info(f"Saved {idx+1}/{len(services)} services")
    
    return results
```

**Benefits**:
- No data loss if script crashes
- Progress visible in real-time
- Can resume from last saved state
- User can review partial results

### Retry Configuration

AWS API calls use adaptive retry:

```python
from botocore.config import Config

retry_config = Config(
    retries={
        'max_attempts': 5,
        'mode': 'adaptive'  # Handles throttling automatically
    }
)

pricing_client = boto3.client(
    "pricing",
    region_name="us-east-1",
    config=retry_config
)
```

**Retry Behavior**:
- Automatic exponential backoff
- Handles AWS rate limiting (429 errors)
- Max 5 attempts per API call
- Adaptive mode adjusts delay based on response

---

## Deployment & Setup

### Prerequisites

1. **Python 3.11+**
2. **PostgreSQL Database** with AWS pricing data
3. **AWS Credentials** with permissions:
   - `pricing:GetProducts`
   - `savingsplans:DescribeSavingsPlansOfferingRates`
   - `ec2:DescribeSpotPriceHistory`
4. **Environment Variables**:
   ```bash
   AWS_ACCESS_KEY_ID=your_key
   AWS_SECRET_ACCESS_KEY=your_secret
   DB_HOST=your_rds_endpoint
   DB_NAME=pricing_db
   DB_USER=admin
   DB_PASSWORD=your_password
   ```

### Installation

```bash
# Clone repository
git clone <repo_url>
cd cloud_migration

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Dependencies

**File**: `requirements.txt`

```
boto3>=1.28.0          # AWS SDK
psycopg2-binary>=2.9.0 # PostgreSQL driver
openpyxl>=3.1.0        # Excel processing
python-dotenv>=1.0.0   # Environment variables
strands>=1.0.0         # AI agent framework
```

### Running the Pipeline

#### Basic Usage

```bash
# Run with default settings
python run_pipeline.py

# Specify input file
python run_pipeline.py --input data/input/azure_export.xlsx

# Specify output file
python run_pipeline.py --input azure.xlsx --output aws_estimate.xlsx
```

#### Programmatic Usage

```python
from agents.orchestrator import run_migration_pipeline

# Run pipeline
output_path = run_migration_pipeline(
    input_xlsx="data/input/azure_export.xlsx",
    output_xlsx="results/aws_estimate.xlsx"
)

print(f"Results saved to: {output_path}")
```

### File Structure

```
cloud_migration/
├── agents/
│   ├── orchestrator.py           # Main coordinator
│   ├── sql_generator_agent.py    # SQL generation + execution
│   └── cost_agent.py             # Cost calculation + optimization
├── tools/
│   └── llm_mapper.py             # LLM fallback tool
├── utils/
│   ├── cost_client.py            # AWS Pricing API client
│   ├── db.py                     # PostgreSQL connection
│   ├── excel.py                  # Excel reader/writer
│   └── kpi_loader.py             # KPI configuration loader
├── data/
│   ├── kpi_mappings.json         # Service/region/field mappings
│   ├── schema.py                 # Database schema definitions
│   ├── schema.sql                # SQL table creation scripts
│   └── input/                    # Input Excel files
│       ├── azure_export.xlsx
│       └── gcp_export.xlsx
├── .env                          # Environment variables (not in git)
├── .env.example                  # Example environment config
├── requirements.txt              # Python dependencies
├── run_pipeline.py               # CLI entry point
└── README.md                     # User documentation
```

### Logging

The system uses Python's logging module:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
```

**Log Levels**:
- `INFO`: Progress updates, API calls, matches found
- `WARNING`: Fallbacks used, missing data, unusual specs
- `ERROR`: API failures, database errors, critical issues
- `DEBUG`: SQL queries, detailed pricing, cache hits

**Example Output**:
```
2024-01-15 10:30:15 - orchestrator - INFO - Starting migration pipeline
2024-01-15 10:30:16 - excel - INFO - Loaded 28 services from azure_export.xlsx
2024-01-15 10:30:17 - sql_generator - INFO - Processing: web-server-1 (ec2 / Azure)
2024-01-15 10:30:18 - sql_generator - WARNING - SQL returned 0 matches. Trying LLM fallback...
2024-01-15 10:30:19 - sql_generator - INFO - LLM normalized 7 GiB → 8 GiB
2024-01-15 10:30:20 - sql_generator - INFO - Retry SQL found 3 matches
2024-01-15 10:30:21 - cost_agent - INFO - Selected: t3a.large ($10.95/mo with CSP 3yr All)
2024-01-15 10:30:22 - orchestrator - INFO - ✅ web-server-1 → t3a.large | OnDemand: $27.45/mo | Optimised: $10.95/mo | Savings: 60%
```

---

## Performance & Optimization

### Processing Speed

**Typical Performance**:
- 28 services: ~5-10 minutes
- Per service: ~20-30 seconds
- Bottleneck: AWS API calls (real-time pricing)

**Breakdown per Service**:
```
LLM SQL Generation:  2-3s   (AWS Bedrock - Claude)
SQL Query:           0.5s   (PostgreSQL)
LLM Fallback:        2-3s   (if needed)
Pricing API Calls:   15-20s (OnDemand + 6 CSP + Spot)
Cost Calculation:    0.5s
AWS Calculator Link: 3-5s   (Playwright automation)
Excel Write:         0.5s
Total:               ~25-35s per service
```

**Token Usage (with prompt caching)**:
```
First service:
- SQL generation: 3000 input (full) + 500 output = 3500 tokens
- LLM fallback: 1400 input (full) + 200 output = 1600 tokens
- Total: 5100 tokens

Subsequent services (90% cached):
- SQL generation: 300 input + 2700 cached + 500 output = 3500 tokens (90% discount on 2700)
- LLM fallback: 300 input + 1100 cached + 200 output = 1600 tokens (90% discount on 1100)
- Total: 5100 tokens (but 3800 cached = ~70% cost reduction)

28 services total:
- Input tokens: ~11,400 (3000 + 27×300 for SQL + 1400 + 5×300 for fallback)
- Cached tokens: ~75,600 (27×2700 for SQL + 5×1100 for fallback)
- Output tokens: ~15,000 (28×500 for SQL + 5×200 for fallback)
- Cost: ~$0.18 (vs $1.20 without caching = 85% savings)
```

### Optimization Strategies

#### 1. Prompt Caching (90% Cost Reduction)
Caches static system prompts for massive token savings:

```python
# System prompt cached (~3000 tokens for SQL, ~1100 for LLM mapper)
request_body = {
    "system": [
        {
            "type": "text",
            "text": system_prompt,  # Schema, KPI, rules, examples
            "cache_control": {"type": "ephemeral"}  # Cache this!
        }
    ],
    "messages": [{"role": "user", "content": user_message}]
}

# First call: Full price on all tokens
# Subsequent calls: 90% discount on cached tokens
```

**Impact**:
- First service: 3000 input tokens (full price)
- Subsequent services: 300 input + 2700 cached (90% discount)
- 28 services: 85% total cost reduction

#### 2. LRU Cache for Pricing
Reduces API calls by 90%+ for duplicate instance types:

```python
@lru_cache(maxsize=256)
def get_ondemand_price(instance_type, region, os, tenancy):
    # First call: API request (slow)
    # Subsequent calls: Cache hit (instant)
    ...
```

**Impact**:
- Without cache: 28 services × 3 matches × 8 API calls = 672 API calls
- With cache: ~70 API calls (90% reduction)

#### 3. Incremental Saves
Prevents data loss and shows progress:

```python
# Save after each service (not at the end)
for service in services:
    result = process_single_service(service)
    results.append(result)
    write_output_xlsx(results, output_path)  # Incremental save
```

#### 4. Retry Configuration
Handles AWS rate limiting automatically:

```python
retry_config = Config(
    retries={'max_attempts': 5, 'mode': 'adaptive'}
)
```

#### 5. Token Usage Tracking
Monitors LLM costs in real-time:

```python
# Track every LLM call
track_tokens(
    input_tokens=300,
    output_tokens=500,
    operation="sql_generation",
    cache_creation_tokens=3000,  # First call
    cache_read_tokens=2700       # Subsequent calls
)

# Print summary at end
print_token_summary()
```

#### 6. Parallel Processing (Future Enhancement)
Currently sequential, could be parallelized:

```python
# Future: Process multiple services in parallel
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(process_single_service, services))
```

**Estimated Speedup**: 5x faster (5 services in parallel)

### Memory Usage

**Typical Memory**:
- Small dataset (10 services): ~50 MB
- Medium dataset (100 services): ~200 MB
- Large dataset (1000 services): ~1 GB

**Memory Optimization**:
- LRU cache limited to 256 entries
- Excel written incrementally (not held in memory)
- Database results fetched in batches

---

## Troubleshooting

### Common Issues

#### 1. AWS API Rate Limiting
**Symptom**: `TooManyRequestsException` or `ThrottlingException`

**Solution**:
- Retry config handles this automatically
- If persistent, reduce `max_workers` in parallel processing
- Add delay between API calls: `time.sleep(0.5)`

#### 2. Database Connection Timeout
**Symptom**: `psycopg2.OperationalError: timeout expired`

**Solution**:
- Check database credentials in `.env`
- Verify RDS security group allows your IP
- Test connection: `psql -h $DB_HOST -U $DB_USER -d $DB_NAME`

#### 3. No Pricing Found
**Symptom**: "No instances with valid pricing found"

**Solution**:
- Check if instance type exists in region
- Verify AWS credentials have pricing permissions
- Try fallback instance families (automatic in Layer 3)

#### 4. LLM Fallback Fails
**Symptom**: "LLM normalization failed"

**Solution**:
- Check Strands/Bedrock credentials
- Verify model access (Claude, etc.)
- Review input specs for validity

#### 5. Excel Write Errors
**Symptom**: `PermissionError: [Errno 13] Permission denied`

**Solution**:
- Close output Excel file if open
- Check write permissions on output directory
- Use different output filename

### Debug Mode

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Debug Output**:
- SQL queries with parameters
- API request/response details
- Cache hit/miss statistics
- Detailed pricing calculations

---

## Future Enhancements

### Planned Features

1. **Parallel Processing**
   - Process multiple services simultaneously
   - 5x speedup for large datasets

2. **Cost Optimization Recommendations**
   - Right-sizing suggestions
   - Reserved Instance vs Savings Plan comparison
   - Multi-year TCO analysis

3. **Additional Cloud Providers**
   - GCP → AWS (currently Azure → AWS)
   - AWS → Azure (reverse migration)
   - Multi-cloud cost comparison

4. **Advanced Pricing**
   - Volume discounts
   - Enterprise agreements
   - Custom pricing tiers

5. **Web Interface**
   - Upload Excel via web UI
   - Real-time progress tracking
   - Interactive cost charts

6. **API Endpoint**
   - REST API for programmatic access
   - Webhook notifications
   - Batch processing queue

---

## Conclusion

This cloud migration cost estimation system provides:

✅ **LLM-Powered Intelligence**: Claude Sonnet 4 generates optimized SQL queries
✅ **Prompt Caching**: 90% token cost reduction through intelligent caching
✅ **Accurate Pricing**: Real-time AWS API calls (not estimates)
✅ **Comprehensive Options**: OnDemand + 6 CSP plans + Spot pricing
✅ **Smart Matching**: SQL-first with LLM fallback for unusual specs
✅ **Regional Validation**: Ensures instance availability per region
✅ **Multi-Cloud Support**: Azure/GCP → AWS with auto-detection
✅ **Detailed Reports**: 5-sheet Excel with full breakdown + calculator links
✅ **Token Tracking**: Real-time monitoring of LLM usage and costs
✅ **Production-Ready**: Error handling, caching, incremental saves

**Key Differentiators**:
- LLM generates SQL (not hardcoded templates)
- Prompt caching reduces costs by 85%+
- Real AWS pricing (not estimates)
- All 6 CSP combinations (not just best)
- Smart fallback (LLM fixes specs, retries SQL)
- Regional availability validation
- AWS Calculator link generation
- Token usage tracking and optimization
- KPI-driven (user-configurable mappings)
- Incremental saves (no data loss)

**Architecture Highlights**:
- Agent-based design (orchestrator, SQL generator, cost agent)
- LLM-powered SQL generation with schema awareness
- Multi-layer fallback strategy (SQL → LLM normalize → retry → fallback families)
- Weighted scoring for optimization (cost 40%, generation 30%, family 30%)
- Comprehensive error handling and graceful degradation

**Performance**:
- 28 services in ~5-10 minutes
- ~25-35 seconds per service
- 85% token cost reduction with caching
- 90% API call reduction with LRU cache

For questions or support, contact the development team.
