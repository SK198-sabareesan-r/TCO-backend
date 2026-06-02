# Agent Architecture

## Overview

The cloud migration system uses a multi-agent architecture powered by AWS Bedrock (Claude) for intelligent SQL generation and fallback mapping. The system processes cloud services from GCP/Azure and maps them to AWS equivalents with cost optimization.

## System Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ENTRY POINTS                                    │
├─────────────────────────────────────────────────────────────────────────┤
│  • run_pipeline.py (CLI)  →  python run_pipeline.py --input file.xlsx  │
│  • main.py (FastAPI)      →  POST /migrate (upload XLSX)               │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR AGENT                                   │
│                  (agents/orchestrator.py)                               │
├─────────────────────────────────────────────────────────────────────────┤
│  1. Read input XLSX (utils/excel.py)                                   │
│  2. For each service row:                                               │
│     → Call SQL Generator Agent                                          │
│     → Call Cost Agent                                                   │
│     → Generate AWS Calculator Link                                      │
│     → Incremental save to output XLSX                                   │
│  3. Print summary & token usage                                         │
│  4. Write final output XLSX (5 sheets)                                  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
┌─────────────────────────────────┐  ┌──────────────────────────────────┐
│   SQL GENERATOR AGENT           │  │      COST AGENT                  │
│ (agents/sql_generator_agent.py) │  │  (agents/cost_agent.py)          │
├─────────────────────────────────┤  ├──────────────────────────────────┤
│ STEP 1: LLM-Powered SQL Gen     │  │ 1. Validate tenancy              │
│  • Load KPI mappings            │  │ 2. Enrich matches with costs:    │
│  • Load DB schema               │  │    - On-Demand pricing           │
│  • Call Bedrock (Claude) to     │  │    - 6 Savings Plans (1yr/3yr)   │
│    generate SQL query           │  │    - Spot pricing                │
│  • Execute SQL on PostgreSQL    │  │ 3. Pick optimized (weighted):    │
│  • Validate regional avail.     │  │    - Cost (40%)                  │
│                                 │  │    - Generation (30%)            │
│ STEP 2: Smart Fallback (if 0)  │  │    - Family availability (30%)   │
│  • LLM normalizes unusual specs │  │ 4. Build cost comparison         │
│    (7 GiB → 8 GiB)              │  │ 5. Calculate savings             │
│  • Retry SQL with corrected     │  │                                  │
│    specs                        │  │ Uses: utils/cost_client.py       │
│  • Return SQL results           │  │       utils/aws_calculator.py    │
│                                 │  │                                  │
│ Uses: utils/kpi_loader.py       │  └──────────────────────────────────┘
│       data/schema.py            │
│       tools/llm_mapper.py       │
│       utils/db.py               │
│       utils/token_tracker.py    │
└─────────────────────────────────┘
```

## Agent Details

### 1. Orchestrator Agent
**Location:** `agents/orchestrator.py`

**Purpose:** Top-level coordinator for the entire migration pipeline

**Key Functions:**
- `run_migration_pipeline(input_xlsx, output_xlsx)` - Main entry point
- `process_single_service(service_row)` - Process one service through full pipeline
- `process_all_services(services, output_path)` - Batch processing with incremental saves
- `print_summary(results)` - Console cost summary

**Pipeline Flow:**
1. Read input XLSX using `utils/excel.read_input_xlsx()`
2. For each service:
   - Call SQL Generator Agent → get AWS matches
   - Call Cost Agent → calculate costs & optimize
   - Generate AWS Calculator link
   - Incremental save to output XLSX
3. Print console summary with totals
4. Print token usage summary
5. Write final output XLSX with 5 sheets

**Output XLSX Sheets:**
1. Summary - Best match + optimized costs per service
2. All Matches - All AWS candidates with costs
3. CSP Options - All 6 Savings Plans + Spot pricing
4. Cost Comparison - Current vs AWS OnDemand vs Optimized
5. Mapping Details - Parameters used for matching

---

### 2. SQL Generator Agent
**Location:** `agents/sql_generator_agent.py`

**Purpose:** LLM-powered SQL generation with smart fallback

**Architecture:**
- Uses AWS Bedrock (Claude Sonnet 4) for SQL generation
- Implements prompt caching (90% discount on cached tokens)
- Smart fallback: LLM normalizes unusual specs and retries SQL

**Key Functions:**
- `generate_and_execute_sql(...)` - Main entry point
- `SQLGeneratorAgent.generate_sql_with_llm(...)` - LLM generates SQL query
- `SQLGeneratorAgent.execute_query(...)` - Execute SQL with fallback
- `SQLGeneratorAgent._llm_fallback(...)` - Smart fallback logic

**Two-Step Process:**

**STEP 1: LLM-Powered SQL Generation**
1. Load KPI mappings from `data/kpi_mappings.json`
2. Load database schema from `data/schema.py`
3. Build comprehensive prompt with:
   - Database schema (table, columns, types)
   - KPI configuration (allowed fields, tolerances)
   - Regional availability rules
   - Query examples
4. Call Bedrock to generate SQL query
5. Post-process SQL (fix LIKE patterns, add filters)
6. Execute SQL on PostgreSQL
7. Validate regional availability
8. Return matches

**STEP 2: Smart Fallback (if 0 matches)**
1. Call LLM to normalize unusual specs:
   - 7 GiB memory → 8 GiB (next higher standard)
   - 14 GiB memory → 16 GiB
   - 28 GiB memory → 32 GiB
2. Retry SQL with corrected specs
3. Return SQL results (never synthetic LLM matches)

**Mapping Methods:**
- `LLM_SQL_GENERATION` - SQL generated by LLM, matches found
- `LLM_FALLBACK` - LLM normalized specs, retry SQL succeeded
- `FAILED` - No matches found even after fallback

**Regional Availability Validation:**
- Mumbai (ap-south-1): Only t3, m5, m6i, c5, c6i, r5, r6i families
- Avoids instances with limited pricing (gd, gn, dn suffixes)
- Adds availability warnings to matches

**Token Optimization:**
- Prompt caching on system prompt (~3000 tokens cached)
- 90% discount on cached tokens after first call
- Tracks cache hits/writes via `utils/token_tracker.py`

---

### 3. Cost Agent
**Location:** `agents/cost_agent.py`

**Purpose:** Calculate AWS costs and optimize pricing plans

**Key Functions:**
- `calculate_and_compare_costs(service_row, mapping)` - Main entry point
- `enrich_match_with_costs(match, service_type, input_row)` - Add pricing to match
- `pick_optimised(matches_with_costs)` - Select best option using weighted scoring
- `build_cost_comparison(...)` - Build comparison table
- `validate_tenancy(...)` - Validate tenancy rules

**Cost Calculation Flow:**
1. Validate tenancy (RDS always Shared, T family not recommended for Dedicated)
2. For each AWS match:
   - Call pricing API via `utils/cost_client.py`
   - Get On-Demand pricing
   - Get 6 Compute Savings Plans (1yr/3yr × no/partial/all upfront)
   - Get Spot pricing (if Shared tenancy)
   - Add 500ms delay between calls (rate limiting)
3. Pick optimized instance using weighted scoring:
   - Cost: 40% weight (lower is better)
   - Generation: 30% weight (current gen preferred)
   - Family: 30% weight (production-ready families)
4. Build cost comparison:
   - Current provider cost
   - AWS On-Demand cost
   - AWS Optimized cost (best savings plan)
   - Monthly/annual savings
   - Savings percentage
5. Return enriched results

**Pricing Plans:**
- On-Demand: Pay-as-you-go hourly pricing
- Compute Savings Plans: 1yr/3yr with no/partial/all upfront
- Spot Instances: Up to 90% discount (variable pricing)

**Fallback Logic:**
- If no instances have valid pricing → try alternative families
- Mumbai fallback: t3a, m6i, c6i (known to be available)
- Validates pricing before returning results

---

## Supporting Components

### KPI Loader (`utils/kpi_loader.py`)
**Purpose:** Load and access KPI mappings from `data/kpi_mappings.json`

**Key Functions:**
- `load_kpi()` - Load entire KPI file (cached)
- `get_region_mapping(provider, region)` - Map GCP/Azure region to AWS
- `get_instance_mapping(service_type, provider, instance_type)` - Get instance mapping
- `get_query_parameters(service_type)` - Get tolerances, max results
- `normalize_region_from_kpi(provider, region)` - Normalize region
- `get_tolerance_for_service(service_type)` - Get vCPU/memory tolerances
- `get_storage_class_mapping(...)` - Map Azure/GCP storage to AWS S3

### LLM Mapper (`tools/llm_mapper.py`)
**Purpose:** Fallback mapping using Claude via AWS Bedrock

**Key Functions:**
- `llm_fallback_tool(...)` - Map service using LLM
- `llm_map_service(...)` - Core LLM mapping logic

**Features:**
- Uses AWS Bedrock (Claude Sonnet 4)
- Prompt caching (~1100 tokens cached)
- Returns structured JSON with AWS equivalents
- Includes GCP/Azure to AWS mapping examples

### Database Client (`utils/db.py`)
**Purpose:** PostgreSQL connection and query execution

**Key Functions:**
- `get_connection()` - Get database connection
- `execute_query(sql, params)` - Execute parameterized query
- `test_connection()` - Health check

### Cost Client (`utils/cost_client.py`)
**Purpose:** AWS pricing API integration

**Key Functions:**
- `get_costs_for_match(service_type, match, input_row)` - Get all pricing
- `get_ondemand_cost(...)` - On-Demand pricing
- `get_savings_plan_costs(...)` - All 6 Savings Plans
- `get_spot_cost(...)` - Spot pricing
- `normalize_region(region)` - Normalize region for pricing API

### AWS Calculator (`utils/aws_calculator.py`)
**Purpose:** Generate AWS Pricing Calculator links

**Key Functions:**
- `generate_calculator_link_sync(...)` - Generate calculator URL
- Uses Playwright to automate calculator form
- Returns shareable calculator link

### Token Tracker (`utils/token_tracker.py`)
**Purpose:** Track LLM token usage and costs

**Key Functions:**
- `track_tokens(...)` - Record token usage
- `get_token_stats()` - Get usage statistics
- `print_token_summary()` - Print summary table
- Tracks cache hits/writes for prompt caching

### Excel Utilities (`utils/excel.py`)
**Purpose:** Read input XLSX and write output XLSX

**Key Functions:**
- `read_input_xlsx(filepath)` - Read user input
- `write_output_xlsx(results, output_path)` - Write 5-sheet output
- Supports multi-sheet Azure/GCP exports
- Auto-detects provider from filename
- Normalizes column names with aliases

### Database Schema (`data/schema.py`)
**Purpose:** Define database schema for SQL generation

**Key Functions:**
- `get_schema(service_type)` - Get schema for service
- `get_table_name(service_type)` - Get table name
- `get_columns(service_type)` - Get all columns
- `get_matching_fields(service_type)` - Get fields for WHERE clause
- `get_select_fields(service_type)` - Get fields for SELECT clause

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. USER INPUT (XLSX)                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│   service_name: "Web Server"                                            │
│   service_type: "ec2"                                                   │
│   current_provider: "GCP"                                               │
│   instance_type: "n2-standard-4"                                        │
│   vcpus: 4                                                              │
│   memory_gib: 16                                                        │
│   region: "us-central1"                                                 │
│   tenancy: "Shared"                                                     │
│   operating_system: "Linux"                                             │
│   current_monthly_cost_usd: 450.00                                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. ORCHESTRATOR reads input → process_single_service()                 │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. SQL GENERATOR AGENT                                                  │
├─────────────────────────────────────────────────────────────────────────┤
│ STEP 1: LLM-Powered SQL Generation                                      │
│   • Load KPI: region mapping (us-central1 → us-east-1)                 │
│   • Load schema: ec2_pricing table structure                            │
│   • Build prompt with KPI + schema + rules                              │
│   • Call Bedrock: Generate SQL query                                    │
│   • Execute SQL: SELECT * FROM ec2_pricing WHERE ...                    │
│   • Result: 3 matches (m5.xlarge, m6i.xlarge, t3.xlarge)               │
│                                                                         │
│ IF 0 matches → STEP 2: Smart Fallback                                  │
│   • Call LLM: "Normalize 7 GiB to next higher AWS standard"            │
│   • LLM returns: 8 GiB                                                  │
│   • Retry SQL with corrected specs                                      │
│   • Return SQL results                                                  │
│                                                                         │
│ OUTPUT:                                                                 │
│   {                                                                     │
│     "matches": [                                                        │
│       {                                                                 │
│         "instance_type": "m5.xlarge",                                   │
│         "vcpus": 4,                                                     │
│         "memory_gib": "16 GiB",                                         │
│         "regioncode": "us-east-1",                                      │
│         "operatingsystem": "Linux",                                     │
│         "tenancy": "Shared",                                            │
│         "current_generation": "Yes"                                     │
│       },                                                                │
│       { ... m6i.xlarge ... },                                           │
│       { ... t3.xlarge ... }                                             │
│     ],                                                                  │
│     "method": "LLM_SQL_GENERATION",                                     │
│     "match_count": 3                                                    │
│   }                                                                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. COST AGENT                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ For each match:                                                         │
│   • Validate tenancy (RDS → Shared, T family → warn if Dedicated)      │
│   • Call pricing API:                                                   │
│     - On-Demand: $0.192/hr = $140.16/mo                                │
│     - Savings Plans (6 options):                                        │
│       * 1yr no upfront: $0.128/hr = $93.44/mo (33% off)                │
│       * 1yr partial: $0.125/hr = $91.25/mo (35% off)                   │
│       * 1yr all upfront: $0.122/hr = $89.06/mo (37% off)               │
│       * 3yr no upfront: $0.096/hr = $70.08/mo (50% off)                │
│       * 3yr partial: $0.093/hr = $67.89/mo (52% off)                   │
│       * 3yr all upfront: $0.090/hr = $65.70/mo (54% off)               │
│     - Spot: $0.058/hr = $42.34/mo (70% off)                            │
│   • Add 500ms delay (rate limiting)                                     │
│                                                                         │
│ Pick optimized using weighted scoring:                                  │
│   • Cost (40%): Lower is better                                         │
│   • Generation (30%): Current gen preferred                             │
│   • Family (30%): Production-ready families (m5, m6i, t3)              │
│   • Winner: m5.xlarge with 3yr all upfront = $65.70/mo                 │
│                                                                         │
│ Build comparison:                                                       │
│   • Current (GCP): $450.00/mo                                           │
│   • AWS On-Demand: $140.16/mo                                           │
│   • AWS Optimized: $65.70/mo (3yr all upfront)                         │
│   • Savings: $384.30/mo (85.4%)                                         │
│                                                                         │
│ OUTPUT:                                                                 │
│   {                                                                     │
│     "aws_matches": [ ... 3 matches with costs ... ],                   │
│     "best_match": { "instance_type": "m5.xlarge", ... },               │
│     "optimised": {                                                      │
│       "instance_type": "m5.xlarge",                                     │
│       "plan_label": "3yr all upfront",                                  │
│       "monthly_usd": 65.70,                                             │
│       "annual_usd": 788.40,                                             │
│       "discount_percent": 54                                            │
│     },                                                                  │
│     "comparison": {                                                     │
│       "current_provider": { "monthly_usd": 450.00 },                   │
│       "aws_ondemand": { "monthly_usd": 140.16 },                       │
│       "aws_optimised": { "monthly_usd": 65.70 },                       │
│       "savings": {                                                      │
│         "monthly_usd": 384.30,                                          │
│         "annual_usd": 4611.60,                                          │
│         "percent": 85.4,                                                │
│         "verdict": "🟢 Great savings"                                   │
│       }                                                                 │
│     }                                                                   │
│   }                                                                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. AWS CALCULATOR LINK GENERATION                                       │
├─────────────────────────────────────────────────────────────────────────┤
│   • Use Playwright to automate AWS Pricing Calculator                   │
│   • Fill form with instance details                                     │
│   • Generate shareable link                                             │
│   • Add to result: calculator_link                                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. ORCHESTRATOR aggregates results                                      │
├─────────────────────────────────────────────────────────────────────────┤
│   • Incremental save to output XLSX after each service                  │
│   • Continue to next service                                            │
│   • After all services: print summary + token usage                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 7. OUTPUT XLSX (5 sheets)                                               │
├─────────────────────────────────────────────────────────────────────────┤
│ Sheet 1: Summary                                                        │
│   • One row per service                                                 │
│   • Best AWS match + optimized costs                                    │
│   • AWS Calculator link (clickable)                                     │
│                                                                         │
│ Sheet 2: All Matches                                                    │
│   • All AWS candidates per service                                      │
│   • On-Demand, Savings Plans, Spot costs                                │
│   • Highlighted: best match (green), spot (yellow)                      │
│                                                                         │
│ Sheet 3: CSP Options                                                    │
│   • All 6 Compute Savings Plans per instance                            │
│   • Spot pricing (if Shared tenancy)                                    │
│   • Upfront fees, hourly rates, monthly/annual costs                    │
│                                                                         │
│ Sheet 4: Cost Comparison                                                │
│   • Side-by-side: Current vs AWS OnDemand vs Optimized                 │
│   • Monthly/annual savings                                              │
│   • Totals row at bottom                                                │
│                                                                         │
│ Sheet 5: Mapping Details                                                │
│   • Input parameters (vCPUs, memory, region, OS, tenancy)              │
│   • Mapped AWS parameters                                               │
│   • Helps understand matching criteria                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. LLM-Powered SQL Generation
- Uses AWS Bedrock (Claude Sonnet 4) to generate SQL queries
- Understands database schema and KPI mappings
- Generates optimized queries with proper filters and tolerances
- Handles complex scenarios (unusual specs, regional availability)

### 2. Prompt Caching (90% Cost Reduction)
- System prompts cached (~3000 tokens for SQL, ~1100 for LLM mapper)
- 90% discount on cached tokens after first call
- Dramatically reduces token costs for batch processing
- Tracked via `utils/token_tracker.py`

### 3. Smart Fallback Logic
- If SQL returns 0 matches → LLM normalizes unusual specs
- Example: 7 GiB memory → 8 GiB (next higher standard)
- Retry SQL with corrected specs
- Never returns synthetic LLM matches (always SQL results)

### 4. Regional Availability Validation
- Validates instance families per region
- Mumbai (ap-south-1): Only t3, m5, m6i, c5, c6i, r5, r6i
- Avoids instances with limited pricing (gd, gn, dn suffixes)
- Adds warnings to matches with availability issues

### 5. Comprehensive Cost Analysis
- On-Demand pricing (pay-as-you-go)
- 6 Compute Savings Plans (1yr/3yr × no/partial/all upfront)
- Spot pricing (up to 90% discount)
- Weighted scoring for optimization (cost 40%, generation 30%, family 30%)

### 6. Incremental Saves
- Saves output XLSX after each service
- Prevents data loss on errors
- Allows monitoring progress during long runs

### 7. Multi-Sheet Excel Output
- Summary: Best match + optimized costs
- All Matches: All candidates with costs
- CSP Options: All 6 Savings Plans + Spot
- Cost Comparison: Current vs AWS
- Mapping Details: Parameters used

### 8. AWS Calculator Integration
- Generates shareable AWS Pricing Calculator links
- Uses Playwright to automate form filling
- Clickable links in Excel output
- Allows users to customize estimates

### 9. Token Usage Tracking
- Tracks all LLM calls (input/output tokens)
- Monitors cache hits/writes
- Calculates costs per operation
- Prints summary table at end

### 10. Multi-Provider Support
- GCP: Compute Engine, Cloud SQL, Cloud Storage, Cloud Functions
- Azure: Virtual Machines, SQL Database, Blob Storage, Functions
- AWS: EC2, RDS, S3, Lambda, VPC
- Auto-detects provider from filename or column

---

## Configuration Files

### KPI Mappings (`data/kpi_mappings.json`)
Defines all mappings and parameters:
- Region mappings (GCP/Azure → AWS)
- Instance mappings (GCP/Azure → AWS)
- Storage class mappings (Azure/GCP → S3)
- Service name mappings (normalize service types)
- Query parameters (tolerances, max results)
- Cost calculation parameters

### Database Schema (`data/schema.py`)
Defines database structure:
- Table names per service type
- Column definitions and types
- Matching fields (for WHERE clause)
- Select fields (for SELECT clause)
- Used by LLM to generate correct SQL

### Environment Variables (`.env`)
Required configuration:
```bash
# AWS Credentials
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-east-1

# Bedrock Model
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0

# PostgreSQL Database
DB_HOST=your_rds_endpoint
DB_PORT=5432
DB_NAME=aws_pricing
DB_USER=your_user
DB_PASSWORD=your_password
```

---

## Entry Points

### CLI (`run_pipeline.py`)
```bash
# Run migration
python run_pipeline.py --input services.xlsx --output results.xlsx

# Create sample input
python run_pipeline.py --create-sample --sample-output sample.xlsx
```

### FastAPI (`main.py`)
```bash
# Start server
python main.py

# Endpoints:
# POST /migrate          - Upload XLSX, download result XLSX
# POST /migrate/json     - Upload XLSX, return JSON
# GET  /health           - Health check
# GET  /schema           - Show expected input schema
```

---

## Benefits of This Architecture

### 1. Intelligent SQL Generation
- LLM understands schema and generates optimal queries
- No hardcoded SQL templates
- Adapts to schema changes automatically
- Handles edge cases gracefully

### 2. Cost Efficiency
- Prompt caching reduces token costs by 90%
- Batch processing benefits from cache
- Only pays full price for first call

### 3. Accuracy
- SQL results from real AWS pricing database
- No synthetic LLM matches
- Regional availability validation
- Weighted scoring for optimization

### 4. Transparency
- 5-sheet Excel output with all details
- Token usage tracking
- Mapping parameters visible
- AWS Calculator links for verification

### 5. Scalability
- Incremental saves prevent data loss
- Handles large input files
- Rate limiting for API calls
- Efficient database queries

### 6. Maintainability
- Clear separation of concerns
- Each agent has single responsibility
- Easy to test independently
- Configuration-driven (KPI, schema)

### 7. Extensibility
- Add new service types via schema
- Add new providers via KPI mappings
- Add new pricing plans via cost client
- Add new agents without modifying existing

---

## Testing

### Unit Tests
```bash
# Test SQL generation
python -m pytest tests/test_sql_generator.py

# Test cost calculation
python -m pytest tests/test_cost_agent.py

# Test KPI loader
python -m pytest tests/test_kpi_loader.py
```

### Integration Tests
```bash
# Test full pipeline
python test_calculator_debug.py

# Test regional validation
python test_regional_validation.py

# Test token tracking
python test_token_tracking.py
```

### Manual Testing
```bash
# Create sample input
python run_pipeline.py --create-sample

# Run pipeline
python run_pipeline.py --input sample_services.xlsx
```

---

## Performance Metrics

### Token Usage (with caching)
- First service: ~5000 input tokens, ~500 output tokens
- Subsequent services: ~2000 input tokens (60% cached), ~500 output tokens
- Cost reduction: ~70% on input tokens after first call

### Processing Time
- SQL generation: ~2-3 seconds per service
- Cost calculation: ~3-5 seconds per service (3 matches × 500ms delay)
- Total: ~5-8 seconds per service
- 10 services: ~1 minute

### Database Queries
- 1 SQL query per service (initial)
- 1 SQL query for fallback (if needed)
- Parameterized queries (SQL injection safe)
- Indexed columns for fast lookups

---

## Future Enhancements

### Potential Improvements
1. Parallel processing of services (reduce total time)
2. Batch pricing API calls (reduce delays)
3. Cache pricing results (reduce API calls)
4. Add more service types (EKS, ECS, Lambda@Edge)
5. Add more providers (Oracle Cloud, IBM Cloud)
6. Add compliance checks (HIPAA, PCI-DSS)
7. Add optimization recommendations (rightsizing, reserved capacity)
8. Add migration timeline estimates
9. Add TCO (Total Cost of Ownership) analysis
10. Add carbon footprint comparison

### Potential New Agents
1. Validation Agent - Validate input data quality
2. Optimization Agent - Suggest cost optimizations
3. Compliance Agent - Check compliance requirements
4. Reporting Agent - Generate executive summaries
5. Monitoring Agent - Track migration progress
6. Recommendation Agent - Suggest architecture improvements

---

## Troubleshooting

### Common Issues

**Issue: SQL returns 0 matches**
- Check KPI mappings for region/instance
- Check database has pricing data for region
- Enable LLM fallback (default: enabled)
- Check logs for SQL query and parameters

**Issue: Pricing API returns no data**
- Check AWS credentials in .env
- Check region has pricing data
- Check instance family availability
- Try alternative instance families

**Issue: Token usage too high**
- Verify prompt caching is working (check logs for cache hits)
- Reduce max_results in KPI (default: 3)
- Simplify system prompts
- Use smaller model (if available)

**Issue: Output XLSX missing data**
- Check incremental saves (should save after each service)
- Check error logs for specific service failures
- Verify all required columns in input
- Check database connection

**Issue: Calculator links not working**
- Check Playwright installation
- Check browser automation permissions
- Try manual calculator link generation
- Verify instance type is valid

---

## Glossary

**Agent** - Autonomous component with specific responsibility

**KPI** - Key Performance Indicator (here: configuration mappings)

**LLM** - Large Language Model (Claude Sonnet 4 via Bedrock)

**Bedrock** - AWS service for accessing foundation models

**Prompt Caching** - Caching system prompts to reduce token costs

**CSP** - Compute Savings Plan (AWS pricing model)

**Spot** - AWS Spot Instances (variable pricing, up to 90% off)

**On-Demand** - Pay-as-you-go pricing (no commitment)

**Reserved** - 1yr/3yr commitment pricing (deprecated, replaced by CSP)

**Tenancy** - Shared (multi-tenant) or Dedicated (single-tenant)

**Current Generation** - Latest instance family (e.g., m6i vs m5)

**Regional Availability** - Instance families available in specific regions

**Weighted Scoring** - Optimization algorithm using multiple criteria

**Incremental Save** - Saving output after each service (prevents data loss)
