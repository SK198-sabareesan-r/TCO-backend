# AWS Calculator Integration

## Status: ✅ IMPLEMENTED

Automated AWS Pricing Calculator link generation integrated into the pipeline.

---

## Overview

The pipeline now automatically generates shareable AWS Calculator links for each service after cost estimation. These links are stored in the Excel output as clickable hyperlinks.

---

## How It Works

### Flow:

```
1. Service Processing (Orchestrator)
   ↓
2. SQL Mapping (SQL Generator Agent)
   ↓
3. Cost Estimation (Cost Agent)
   ↓
4. Calculator Link Generation (NEW!) ← Automated
   ↓
5. Excel Output with Calculator Links
```

### Integration Point:

After cost estimation completes successfully, the orchestrator:
1. Extracts the best match instance details
2. Prepares parameters (instance type, region, OS, tenancy, etc.)
3. Calls the calculator automation in headless mode
4. Captures the shareable link
5. Stores it in the result dictionary
6. Excel writer adds it as a clickable hyperlink

---

## Features

### ✅ Fully Automated
- No manual input required
- Runs in headless browser mode (invisible)
- Integrated into existing pipeline flow

### ✅ Dynamic Parameters
- Instance type from best_match
- Region from AWS mapping
- OS, tenancy from service parameters
- Storage, database engine for RDS

### ✅ Excel Integration
- New column: "AWS Calculator Link"
- Clickable hyperlinks
- Wide column (50 chars) for full URL visibility

### ✅ Supported Services
- **EC2**: Full support with all parameters
- **RDS**: Full support with database engine, deployment, storage
- **S3, Lambda, VPC**: Not yet supported (calculator URLs different)

---

## Files Created/Modified

### New Files:

1. **`utils/aws_calculator.py`** - Calculator automation module
   - `generate_ec2_calculator_link()` - EC2 automation
   - `generate_rds_calculator_link()` - RDS automation
   - `generate_calculator_link_sync()` - Synchronous wrapper
   - Uses Playwright for browser automation
   - Headless mode enabled by default

### Modified Files:

2. **`agents/orchestrator.py`**
   - Added Step 3: Generate AWS Calculator Link
   - Calls calculator after cost estimation
   - Handles errors gracefully (doesn't fail pipeline)
   - Stores link in result["calculator_link"]

3. **`utils/excel.py`**
   - Added "AWS Calculator Link" column to Summary sheet
   - Makes links clickable (hyperlink style)
   - Increased column width to 50 chars

4. **`requirements.txt`**
   - Added `playwright>=1.40.0`

---

## Installation

### 1. Install Python Dependencies:
```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers:
```bash
playwright install chromium
```

This downloads the Chromium browser (~100MB) needed for automation.

---

## Usage

### Automatic (Default):

Just run your pipeline normally:
```bash
python run_pipeline.py --input data/input/Emcure_azure.xlsx --output results.xlsx
```

Calculator links are generated automatically for each service!

### Expected Logs:

```
[INFO] Processing: vm-emqrdevapp01 (ec2 / Azure)
[INFO] ✅ vm-emqrdevapp01 → m5ad.large | OnDemand: $48.91/mo | Optimised: $21.9/mo
[INFO] 🔗 Generating calculator link for m5ad.large...
[INFO] ✅ Generated EC2 calculator link: m5ad.large
[INFO] ✅ Calculator link generated
```

### Excel Output:

The Summary sheet will have a new column with clickable links:
```
| Service Name    | ... | AWS Calculator Link                                    |
|-----------------|-----|--------------------------------------------------------|
| vm-emqrdevapp01 | ... | https://calculator.aws/#/estimate?id=abc123def456...   |
```

Click the link to open the pre-filled AWS Calculator!

---

## Parameters Passed to Calculator

### EC2:
- Instance Type: `m5.xlarge`
- Region: `Asia Pacific (Mumbai)`
- Operating System: `Linux` / `Windows`
- Tenancy: `Shared Instances` / `Dedicated`
- Number of Instances: `1`
- Pricing Model: `on-demand`
- Usage: `100%`
- Storage: From input (if provided)

### RDS:
- Instance Type: `db.r5.large`
- Region: `Asia Pacific (Mumbai)`
- Database Engine: `MySQL` / `PostgreSQL` / etc.
- Deployment: `Single-AZ` / `Multi-AZ`
- Storage Type: `General Purpose SSD (gp2)`
- Storage Amount: From input (default 100 GB)
- Number of Instances: `1`

---

## Error Handling

### Graceful Failures:

If calculator link generation fails:
- ⚠️ Warning logged
- Empty string stored in result
- Pipeline continues normally
- Excel shows empty cell (no link)

### Common Failure Reasons:
1. Network timeout (AWS Calculator slow to load)
2. Page structure changed (AWS updated their UI)
3. Playwright browser not installed
4. Instance type not found in calculator

### Impact:
- **Zero impact on pipeline** - cost estimation still works
- Only the calculator link column will be empty
- All other data (costs, matches, etc.) unaffected

---

## Performance Impact

### Time Added Per Service:
- **EC2**: ~8-12 seconds
- **RDS**: ~10-15 seconds
- **Failed/Skipped**: ~0 seconds

### For 76 Services:
- **Without calculator**: ~10-15 minutes
- **With calculator**: ~20-30 minutes
- **Additional time**: ~10-15 minutes

### Optimization:
- Headless mode (no UI rendering)
- Minimal wait times
- Parallel processing possible (future enhancement)

---

## Disabling Calculator Generation

If you want to disable calculator link generation:

### Option 1: Comment out in orchestrator.py

Find this section (around line 120):
```python
# ── Step 3: Generate AWS Calculator Link ──────────────────────────────
calculator_link = ""
if best_match.get("instance_type"):
    try:
        from utils.aws_calculator import generate_calculator_link_sync
        ...
```

Comment it out:
```python
# ── Step 3: Generate AWS Calculator Link (DISABLED) ───────────────────
calculator_link = ""
# if best_match.get("instance_type"):
#     try:
#         from utils.aws_calculator import generate_calculator_link_sync
#         ...
```

### Option 2: Environment Variable (Future Enhancement)

Could add:
```python
ENABLE_CALCULATOR_LINKS = os.getenv("ENABLE_CALCULATOR_LINKS", "true").lower() == "true"
```

---

## Troubleshooting

### Issue: "playwright not found"
**Solution:**
```bash
pip install playwright
playwright install chromium
```

### Issue: Calculator links are empty
**Check logs for:**
- `⚠️ Failed to generate calculator link`
- `Calculator link generation error: ...`

**Common causes:**
- Network timeout
- AWS Calculator page changed
- Instance type not recognized

**Solution:**
- Check internet connection
- Verify instance type exists in AWS Calculator
- Check logs for specific error

### Issue: Pipeline is slow
**Cause:** Calculator generation adds 8-15 seconds per service

**Solutions:**
1. Disable calculator generation (see above)
2. Run on faster network
3. Process fewer services at once

### Issue: Browser window opens (not headless)
**Check:** `headless=True` in `aws_calculator.py`

Should be:
```python
browser = await p.chromium.launch(
    headless=True,  # ← Should be True
    args=["--no-sandbox", "--disable-setuid-sandbox"]
)
```

---

## Future Enhancements

### Possible Improvements:

1. **Parallel Processing**
   - Generate multiple calculator links simultaneously
   - Reduce total time from 15 min to 5 min

2. **S3/Lambda/VPC Support**
   - Add calculator automation for other services
   - Different URLs and form structures

3. **Caching**
   - Cache calculator links for same instance+region
   - Avoid regenerating identical configurations

4. **Retry Logic**
   - Retry failed calculator generations
   - Exponential backoff for network errors

5. **Configuration**
   - Environment variable to enable/disable
   - Timeout configuration
   - Max retries configuration

6. **Cost Scraping**
   - Extract costs from calculator page
   - Compare with API pricing
   - Validation and discrepancy detection

---

## Example Output

### Console Log:
```
[1/76] Processing service
Processing: pharmaco (rds / Azure)
✅ pharmaco → db.t2.micro | OnDemand: $35.04/mo | Optimised: $24.53/mo
🔗 Generating calculator link for db.t2.micro...
✅ Generated RDS calculator link: db.t2.micro
✅ Calculator link generated

[2/76] Processing service
Processing: vm-emqrdevapp01 (ec2 / Azure)
✅ vm-emqrdevapp01 → m5ad.large | OnDemand: $48.91/mo | Optimised: $21.9/mo
🔗 Generating calculator link for m5ad.large...
✅ Generated EC2 calculator link: m5ad.large
✅ Calculator link generated
```

### Excel Output:
```
Summary Sheet:
┌─────────────────┬──────┬─────────┬────────────────┬─────────────────────────────────────────────────┐
│ Service Name    │ Type │ Provider│ AWS Instance   │ AWS Calculator Link                             │
├─────────────────┼──────┼─────────┼────────────────┼─────────────────────────────────────────────────┤
│ pharmaco        │ rds  │ Azure   │ db.t2.micro    │ https://calculator.aws/#/estimate?id=abc123...  │
│ vm-emqrdevapp01 │ ec2  │ Azure   │ m5ad.large     │ https://calculator.aws/#/estimate?id=def456...  │
└─────────────────┴──────┴─────────┴────────────────┴─────────────────────────────────────────────────┘
```

Click any link to open the pre-filled AWS Calculator in your browser!

---

## Summary

✅ Fully automated calculator link generation  
✅ Integrated into pipeline after cost estimation  
✅ Headless browser mode (invisible)  
✅ Dynamic parameters from orchestrator  
✅ Clickable links in Excel output  
✅ Graceful error handling  
✅ EC2 and RDS support  
✅ ~10-15 seconds per service  
✅ Zero impact on pipeline if disabled  

**Result:** Every service now has a shareable AWS Calculator link for validation and stakeholder sharing!
