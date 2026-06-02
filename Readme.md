# Cloud Migration Cost Estimator

Estimates AWS migration costs for GCP and Azure workloads using a multi-agent pipeline: LLM-powered SQL matching via AWS Bedrock (Claude), real-time AWS pricing APIs, and PostgreSQL RDS for instance data.

---

## Architecture

```
Input XLSX  (GCP/Azure services + specs)
     │
     ▼
┌──────────────────────────────────────────────────────┐
│                  Orchestrator                        │
│  agents/orchestrator.py                              │
│  Reads each service row, coordinates agents,         │
│  saves incrementally, prints summary                 │
└──────────────┬───────────────────────────────────────┘
               │  for each service row
     ┌─────────▼──────────────┐
     │  SQL Generator Agent   │   agents/sql_generator_agent.py
     │                        │
     │  1. Check KPI mappings │──→ data/kpi_mappings.json
     │     (instance/region)  │
     │  2. LLM generates SQL  │──→ AWS Bedrock (Claude Sonnet 4)
     │     using schema +     │        Prompt cached for efficiency
     │     KPI context        │
     │  3. Execute SQL        │──→ PostgreSQL RDS
     │  4. If 0 results →     │        ec2_pricing / rds_pricing /
     │     LLM normalises     │        s3_pricing / lambda_pricing /
     │     specs, retry SQL   │        vpc_pricing tables
     └─────────┬──────────────┘
               │  matched AWS instances (up to 3)
     ┌─────────▼──────────────┐
     │     Cost Agent         │   agents/cost_agent.py
     │                        │
     │  For each match:       │──→ utils/cost_client.py
     │  - On-Demand price     │        AWS Pricing API (real-time)
     │  - Best Savings Plan   │        Spot pricing (EC2)
     │    (CSP / RI)          │
     │  - Spot pricing        │
     │                        │
     │  Weighted scoring:     │
     │  - Cost       (40%)    │
     │  - Generation (30%)    │
     │  - Family     (30%)    │
     │                        │
     │  Tenancy validation    │
     │  Fallback instances    │
     │  if no pricing found   │
     └─────────┬──────────────┘
               │  enriched results
     ┌─────────▼──────────────┐
     │  AWS Calculator Link   │   utils/aws_calculator.py
     │  (generated per match) │
     └─────────┬──────────────┘
               │
     ┌─────────▼──────────────┐
     │     Output XLSX        │   utils/excel.py
     │  Sheet 1: Summary      │
     │  Sheet 2: All Matches  │
     │  Sheet 3: CSP Options  │
     │  Sheet 4: Cost Compare │
     │  Sheet 5: Mapping Det. │
     └────────────────────────┘
```

---

## Project Structure

```
cloud_migration/
├── api.py                      # FastAPI app — main entry point (v2)
├── run_pipeline.py             # CLI entry point
├── pricing.py                  # AWS pricing calculations (EC2/RDS/S3/VPC/Lambda)
├── requirements.txt
├── .env.example
├── .gitignore
├── Readme.md
│
├── agents/
│   ├── sql_generator_agent.py  # LLM-powered SQL generation + execution
│   ├── cost_agent.py           # Cost calculation, scoring, comparison
│   └── orchestrator.py        # Full pipeline coordinator
│
├── calculator/
│   ├── ec2.py                  # EC2 pricing calculator
│   └── rds.py                  # RDS pricing calculator
│
├── config/
│   ├── .env                    # Local credentials (gitignored)
│   ├── secrets.py              # Credential loader (Secrets Manager → .env)
│   └── __init__.py
│
├── data/
│   ├── input/                  # Input XLSX files
│   ├── kpi_mappings.json       # Instance/region/storage class mappings
│   └── schema.py               # DB table schemas + field definitions
│
├── docs/                       # Documentation (architecture, setup, API)
│
├── tools/
│   └── llm_mapper.py           # LLM fallback mapper tool
│
└── utils/
    ├── aws_calculator.py       # AWS Calculator link generator
    ├── cost_client.py          # AWS Pricing API client + region normalisation
    ├── db.py                   # PostgreSQL connection pool
    ├── excel.py                # XLSX reader + 5-sheet writer
    ├── kpi_loader.py           # KPI mappings loader
    ├── s3_calculator.py        # S3 cost calculator
    └── token_tracker.py        # LLM token usage + cost tracking
```

---

## Setup

### 1. Clone and install dependencies
```bash
cd cloud_migration
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure credentials
```bash
cp .env.example config/.env
```

Edit `config/.env`:
```env
# AWS (for Bedrock LLM + Pricing API)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...           # if using temporary credentials
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0

# PostgreSQL RDS (AWS instance pricing database)
DB_HOST=your-rds-host.rds.amazonaws.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=...
```

### 3. Enable AWS Bedrock model access
- Go to AWS Console → Bedrock → Model access
- Enable **Claude Sonnet 4** (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- Ensure your IAM role/user has `bedrock:InvokeModel` permission

### 4. Start the API server
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Production URL: `https://tco.shellkode.ai`
Local URL: `http://localhost:8000`
Swagger docs: `http://localhost:8000/docs`

---

## Usage

### REST API

```bash
# Health check
curl http://localhost:8000/health

# Upload XLSX → download result XLSX
curl -X POST http://localhost:8000/migrate \
  -F "file=@your_azure_export.xlsx" \
  -F "source_provider=Azure" \
  -o aws_estimate.xlsx

# Upload XLSX → get JSON response
curl -X POST http://localhost:8000/migrate/json \
  -F "file=@your_gcp_export.xlsx" \
  -F "source_provider=GCP"

# Async upload → poll for result
curl -X POST http://localhost:8000/migrate/async \
  -F "file=@services.xlsx" \
  -F "source_provider=Azure"
# Returns: { "job_id": "...", "status": "pending" }

curl http://localhost:8000/jobs/{job_id}
curl http://localhost:8000/download/{job_id} -o result.xlsx
```

### CLI

```bash
# Generate a sample input XLSX
python run_pipeline.py --create-sample

# Run pipeline on a file
python run_pipeline.py --input data/input/Emcure_azure.xlsx

# Custom output path
python run_pipeline.py --input services.xlsx --output results.xlsx
```

---

## Input XLSX Format

| Column | Required | Description |
|--------|----------|-------------|
| `service_name` | No | Human label e.g. "Web Server" |
| `service_type` | **Yes** | `ec2`, `rds`, `s3`, `vpc`, `lambda` |
| `current_provider` | **Yes** | `Azure`, `GCP` |
| `instance_type` | No | Source instance e.g. `n2-standard-4`, `Standard_D4s_v3` |
| `vcpus` | No | Number of vCPUs |
| `memory_gib` | No | Memory in GiB |
| `region` | No | Source region (auto-normalised to AWS) |
| `tenancy` | No | `Shared` / `Dedicated` (default: Shared) |
| `operating_system` | No | `Linux` / `Windows` (default: Linux) |
| `storage_gb` | No | Storage in GB |
| `number_of_instances` | No | Instance count (default: 1) |
| `current_monthly_cost_usd` | No | Current spend for comparison |
| `database_engine` | RDS only | `MySQL`, `PostgreSQL`, `MariaDB`, `Oracle`, `SQL Server` |
| `multi_az` | RDS only | `TRUE` / `FALSE` |
| `memory_mb` | Lambda only | Memory in MB |
| `invocations_per_month` | Lambda only | Monthly invocations |
| `avg_duration_ms` | Lambda only | Average execution time in ms |
| `data_transfer_out_gb` | S3/VPC | Outbound GB/month |
| `nat_gateways` | VPC only | Number of NAT gateways |

Auto-detection: Provider can be inferred from the filename (`azure_export.xlsx` → Azure).
Multi-sheet: Azure exports with sheets like "Virtual Machines", "SQL DBs", "Storage Accounts" are supported.

---

## Output XLSX — 5 Sheets

| Sheet | Contents |
|-------|----------|
| **Summary** | One row per service: best AWS match, optimised plan, savings vs current |
| **All Matches** | All AWS candidates evaluated (up to 3 per service), marked ✅ for recommended |
| **CSP Options** | All 6 Savings Plan options + Spot pricing per match |
| **Cost Comparison** | Side-by-side: Current Provider vs AWS On-Demand vs AWS Optimised |
| **Mapping Details** | Input params used, mapping method (SQL / LLM_FALLBACK / LLM_ONLY), AWS Calculator link |

---

## Mapping Logic

```
Input specs
    │
    ▼
[KPI lookup] ── Direct instance mapping? (kpi_mappings.json)
    │              e.g. n2-standard-4 → m5.xlarge
    │
    ▼
[LLM generates SQL] ── Claude reads schema + KPI allowed fields
    │                    Generates parameterised PostgreSQL query
    │
    ▼
[Execute SQL] ── PostgreSQL RDS
    │
    ├── results > 0 ──→ Return matches  (method: SQL)
    │
    └── 0 results
            │
            ▼
        [LLM normalises specs] ── Maps unusual specs to
            │                      nearest standard AWS specs
            │
            ▼
        [Retry SQL] ── Broader tolerance
            │
            ├── results > 0 ──→ Return  (method: LLM_FALLBACK)
            │
            └── 0 results ──→ Use LLM suggestion  (method: LLM_ONLY)
```

---

## Cost Scoring

Each matched instance is scored on three criteria to pick the optimised recommendation:

| Criteria | Weight | Detail |
|----------|--------|--------|
| Cost | 40% | Lower effective monthly cost scores higher |
| Generation | 30% | Current generation instances preferred |
| Instance Family | 30% | Widely available families (t3, m5, m6i, c5, c6i) score higher |

Tenancy rules enforced automatically:
- RDS → always `Shared` (no Dedicated support)
- T-family EC2 + Dedicated → warning logged, allowed
- S3 / Lambda / VPC → tenancy not applicable

---

## Token Tracking

All Bedrock LLM calls are tracked automatically. Summary printed after each pipeline run:

```
================================================================================
  TOKEN USAGE SUMMARY
================================================================================
  Total LLM Calls:     8
  Total Input Tokens:  24,150
  Total Output Tokens: 3,840
  Total Tokens:        27,990
  Estimated Cost:      $0.138 (Claude Sonnet 4)
================================================================================
```

The system prompt is **prompt-cached** in Bedrock — repeated calls for the same service type reuse the cached prompt at a 90% token discount.

---

## Credential Priority

`config/secrets.py` resolves credentials in this order:

1. **AWS Secrets Manager** — if `AWS_SECRET_NAME` is set in environment
2. **`config/.env`** — local development fallback
3. **IAM Role** — default boto3 credential chain (production/EC2/ECS)

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check + DB connectivity |
| GET | `/schema` | Expected XLSX input format |
| POST | `/migrate` | Upload XLSX → download result XLSX |
| POST | `/migrate/json` | Upload XLSX → JSON response |
| POST | `/migrate/async` | Upload XLSX → job ID |
| GET | `/jobs/{job_id}` | Poll async job status |
| GET | `/download/{job_id}` | Download completed job result |
| DELETE | `/jobs/{job_id}` | Delete job + cleanup temp files |

Full Swagger docs available at `/docs`.

---

## Further Documentation

All detailed docs are in the `docs/` folder:

- `AGENT_ARCHITECTURE.md` — deep dive into agent design
- `API_DOCUMENTATION.md` — full API reference
- `COMPLETE_ARCHITECTURE.md` — end-to-end system design
- `FRONTEND_INTEGRATION.md` — frontend integration guide
- `CREDENTIALS_SETUP.md` — AWS credentials setup
- `AWS_SSO_SETUP.md` — SSO configuration
- `GETTING_STARTED.md` — step-by-step onboarding
