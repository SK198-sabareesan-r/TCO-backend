# API Endpoints for Frontend Integration

**Base URL:** `http://localhost:8000`

---

## 1. Health Check

**Endpoint:** `GET /health`

**Purpose:** Check if API server is running and database is connected

**Request:** None

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-02T20:37:29.329075",
  "components": {
    "api": "operational",
    "database": "connected",
    "llm": "operational"
  },
  "version": "2.0.0"
}
```

**JavaScript Example:**
```javascript
const response = await fetch('http://localhost:8000/health');
const data = await response.json();

if (data.status === 'healthy') {
  console.log('✅ API is ready');
}
```

---

## 2. Get Input Schema

**Endpoint:** `GET /schema`

**Purpose:** Get information about expected Excel file format and columns

**Request:** None

**Response:**
```json
{
  "description": "Expected columns in the input XLSX file",
  "source_providers": ["Azure", "GCP"],
  "target_provider": "AWS (fixed)",
  "required_columns": ["service_type", "current_provider"],
  "optional_columns": {
    "service_name": "Human-readable name (e.g. Web Server, DB Primary)",
    "service_type": "ec2 | rds | s3 | vpc | lambda",
    "current_provider": "Azure | GCP",
    "instance_type": "Source instance type (e.g. n2-standard-4, Standard_D4s_v3)",
    "vcpus": "Number of vCPUs",
    "memory_gib": "Memory in GiB",
    "region": "Source region (Azure/GCP region names)",
    "tenancy": "Shared | Dedicated (default: Shared)",
    "operating_system": "Linux | Windows (default: Linux)",
    "storage_gb": "Storage in GB",
    "number_of_instances": "Count of this instance type (default: 1)",
    "current_monthly_cost_usd": "Current monthly spend for comparison",
    "database_engine": "[RDS only] MySQL | PostgreSQL | MariaDB | Oracle | SQL Server",
    "multi_az": "[RDS only] TRUE | FALSE",
    "workload": "Constant | Variable (informational)",
    "notes": "Any additional notes"
  },
  "example_rows": [
    {
      "service_name": "Web Server",
      "service_type": "ec2",
      "current_provider": "Azure",
      "instance_type": "Standard_D4s_v3",
      "vcpus": 4,
      "memory_gib": 16,
      "region": "Central India",
      "operating_system": "Linux",
      "storage_gb": 100,
      "current_monthly_cost_usd": 450.00
    }
  ]
}
```

**JavaScript Example:**
```javascript
const response = await fetch('http://localhost:8000/schema');
const schema = await response.json();

console.log('Supported providers:', schema.source_providers);
console.log('Required columns:', schema.required_columns);
```

---

## 3. Upload & Get JSON Results (RECOMMENDED)

**Endpoint:** `POST /migrate/json`

**Purpose:** Upload Excel file and receive detailed JSON results with cost estimates

**Request:**
- **Content-Type:** `multipart/form-data`
- **Parameters:**
  - `file` (required): Excel file (.xlsx or .xls)
  - `source_provider` (required): "Azure" or "GCP"

**Response:**
```json
{
  "success": true,
  "source_provider": "Azure",
  "target_provider": "AWS",
  "summary": {
    "total_services": 10,
    "total_current_cost": 3255.00,
    "total_aws_ondemand_cost": 3407.19,
    "total_aws_optimized_cost": 2089.48,
    "total_savings": 1165.52,
    "savings_percent": 35.8,
    "processing_time_seconds": 42.69,
    "token_usage": {
      "total_input_tokens": 7832,
      "total_output_tokens": 3139,
      "total_cached_tokens": 0,
      "estimated_cost_usd": 0.0000
    }
  },
  "results": [
    {
      "input": {
        "service_name": "Web Server",
        "service_type": "ec2",
        "current_provider": "Azure",
        "instance_type": "Standard_D4s_v3",
        "vcpus": 4,
        "memory_gib": 16,
        "region": "Central India",
        "operating_system": "Linux",
        "storage_gb": 100,
        "current_monthly_cost_usd": 450.00
      },
      "best_match": {
        "instance_type": "m5.xlarge",
        "vcpus": 4,
        "memory_gib": 16,
        "region": "ap-south-1",
        "regioncode": "ap-south-1",
        "tenancy": "Shared",
        "operatingsystem": "Linux"
      },
      "costs": {
        "ondemand": {
          "hourly_usd": 0.192,
          "monthly_usd": 140.16,
          "annual_usd": 1681.92
        },
        "best_savings_plan": {
          "plan_type": "1yr_partial_upfront",
          "hourly_usd": 0.118,
          "monthly_usd": 86.14,
          "annual_usd": 1033.68,
          "discount_percent": 38.5
        },
        "spot": {
          "hourly_usd": 0.058,
          "monthly_usd": 42.34,
          "annual_usd": 508.08,
          "discount_percent": 69.8
        }
      },
      "optimised": {
        "instance_type": "m5.xlarge",
        "plan": "1yr_partial_upfront",
        "plan_label": "1-Year Partial Upfront",
        "monthly_usd": 86.14,
        "annual_usd": 1033.68,
        "savings_vs_current": 363.86,
        "savings_percent": 80.9
      },
      "calculator_link": "https://calculator.aws/#/estimate?id=..."
    }
  ],
  "timestamp": "2026-03-02T20:39:26.555709"
}
```

**JavaScript Example:**
```javascript
async function uploadAndGetResults(file, provider) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source_provider', provider); // "Azure" or "GCP"
  
  const response = await fetch('http://localhost:8000/migrate/json', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  const data = await response.json();
  
  // Display summary
  console.log(`Total Services: ${data.summary.total_services}`);
  console.log(`Current Cost: $${data.summary.total_current_cost}/mo`);
  console.log(`AWS Optimized: $${data.summary.total_aws_optimized_cost}/mo`);
  console.log(`Savings: $${data.summary.total_savings}/mo (${data.summary.savings_percent}%)`);
  
  // Display each service
  data.results.forEach(result => {
    console.log(`\n${result.input.service_name}:`);
    console.log(`  Current: ${result.input.instance_type} @ $${result.input.current_monthly_cost_usd}/mo`);
    console.log(`  AWS: ${result.optimised.instance_type} @ $${result.optimised.monthly_usd}/mo`);
    console.log(`  Savings: $${result.optimised.savings_vs_current}/mo`);
  });
  
  return data;
}

// Usage
const fileInput = document.getElementById('fileInput');
const provider = document.getElementById('providerSelect').value;
const results = await uploadAndGetResults(fileInput.files[0], provider);
```

---

## 4. Upload & Download Excel Report

**Endpoint:** `POST /migrate`

**Purpose:** Upload Excel file and download detailed Excel report with 5 sheets

**Request:**
- **Content-Type:** `multipart/form-data`
- **Parameters:**
  - `file` (required): Excel file (.xlsx or .xls)
  - `source_provider` (required): "Azure" or "GCP"

**Response:**
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File:** Excel file with 5 sheets:
  1. **Summary** - Best match + optimized costs per service
  2. **All Matches** - All AWS candidates with pricing
  3. **CSP Options** - All 6 Savings Plans + Spot pricing
  4. **Cost Comparison** - Current vs AWS costs
  5. **Mapping Details** - Parameters used for matching

**JavaScript Example:**
```javascript
async function uploadAndDownloadExcel(file, provider) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source_provider', provider); // "Azure" or "GCP"
  
  const response = await fetch('http://localhost:8000/migrate', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  // Download the Excel file
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `aws_estimate_${provider.toLowerCase()}_${file.name}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
  
  console.log('✅ Excel report downloaded');
}

// Usage
const fileInput = document.getElementById('fileInput');
const provider = document.getElementById('providerSelect').value;
await uploadAndDownloadExcel(fileInput.files[0], provider);
```

---

## 5. Async Upload (For Large Files)

**Endpoint:** `POST /migrate/async`

**Purpose:** Upload large files and get job ID for tracking progress

**Request:**
- **Content-Type:** `multipart/form-data`
- **Parameters:**
  - `file` (required): Excel file (.xlsx or .xls)
  - `source_provider` (required): "Azure" or "GCP"

**Response:**
```json
{
  "job_id": "e7330aa8-8f4b-4222-a824-25ffcc4d492f",
  "status": "pending",
  "progress": 0,
  "message": "Job queued for processing",
  "created_at": "2026-03-02T20:37:29.329075"
}
```

**JavaScript Example:**
```javascript
async function uploadAsync(file, provider) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source_provider', provider);
  
  const response = await fetch('http://localhost:8000/migrate/async', {
    method: 'POST',
    body: formData
  });
  
  const data = await response.json();
  return data.job_id;
}

// Usage
const jobId = await uploadAsync(fileInput.files[0], 'Azure');
console.log('Job ID:', jobId);
```

---

## 6. Check Job Status

**Endpoint:** `GET /jobs/{job_id}`

**Purpose:** Check progress of async job

**Request:** None (job_id in URL)

**Response:**
```json
{
  "job_id": "e7330aa8-8f4b-4222-a824-25ffcc4d492f",
  "status": "processing",
  "progress": 10,
  "message": "Processing migration...",
  "created_at": "2026-03-02T20:37:29.329075",
  "completed_at": null,
  "result_url": null,
  "error": null
}
```

**Status Values:**
- `pending` - Job is queued
- `processing` - Job is running
- `completed` - Job finished successfully
- `failed` - Job encountered an error

**JavaScript Example:**
```javascript
async function checkJobStatus(jobId) {
  const response = await fetch(`http://localhost:8000/jobs/${jobId}`);
  const data = await response.json();
  
  console.log(`Status: ${data.status}`);
  console.log(`Progress: ${data.progress}%`);
  
  return data;
}

// Poll until complete
async function waitForJob(jobId) {
  while (true) {
    const status = await checkJobStatus(jobId);
    
    if (status.status === 'completed') {
      console.log('✅ Job completed!');
      return status.result_url;
    } else if (status.status === 'failed') {
      throw new Error(status.error);
    }
    
    // Wait 2 seconds before checking again
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
```

---

## 7. Download Job Result

**Endpoint:** `GET /download/{job_id}`

**Purpose:** Download Excel result for completed async job

**Request:** None (job_id in URL)

**Response:**
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **File:** Excel file with results

**JavaScript Example:**
```javascript
async function downloadJobResult(jobId) {
  const response = await fetch(`http://localhost:8000/download/${jobId}`);
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }
  
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'aws_estimate.xlsx';
  a.click();
  window.URL.revokeObjectURL(url);
}
```

---

## Complete Workflow Examples

### Simple Workflow (Recommended for Most Cases)

```javascript
// 1. Check API health
const health = await fetch('http://localhost:8000/health');
console.log('API Status:', (await health.json()).status);

// 2. Upload and get results
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_provider', 'Azure');

const response = await fetch('http://localhost:8000/migrate/json', {
  method: 'POST',
  body: formData
});

const data = await response.json();

// 3. Display results
console.log(`Savings: $${data.summary.total_savings}/mo`);
data.results.forEach(r => {
  console.log(`${r.input.service_name}: $${r.optimised.monthly_usd}/mo`);
});
```

### Async Workflow (For Large Files)

```javascript
// 1. Upload file
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_provider', 'GCP');

const uploadResponse = await fetch('http://localhost:8000/migrate/async', {
  method: 'POST',
  body: formData
});

const { job_id } = await uploadResponse.json();

// 2. Poll for status
const pollInterval = setInterval(async () => {
  const statusResponse = await fetch(`http://localhost:8000/jobs/${job_id}`);
  const status = await statusResponse.json();
  
  console.log(`Progress: ${status.progress}%`);
  
  if (status.status === 'completed') {
    clearInterval(pollInterval);
    
    // 3. Download result
    window.location.href = `http://localhost:8000/download/${job_id}`;
  } else if (status.status === 'failed') {
    clearInterval(pollInterval);
    console.error('Job failed:', status.error);
  }
}, 2000); // Check every 2 seconds
```

---

## Error Handling

All endpoints return errors in this format:

```json
{
  "success": false,
  "error": "Invalid file type. Only .xlsx and .xls files are supported.",
  "status_code": 400,
  "timestamp": "2026-03-02T20:37:29.329075"
}
```

**Common Error Codes:**
- `400` - Bad request (invalid file type, invalid provider)
- `404` - Job not found
- `500` - Internal server error (processing failed)

**JavaScript Error Handling:**
```javascript
try {
  const response = await fetch('http://localhost:8000/migrate/json', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    
    if (error.detail.includes('file type')) {
      alert('Please upload an Excel file (.xlsx)');
    } else if (error.detail.includes('provider')) {
      alert('Please select Azure or GCP');
    } else {
      alert(`Error: ${error.detail}`);
    }
    return;
  }
  
  const data = await response.json();
  // Handle success
  
} catch (error) {
  console.error('Network error:', error);
  alert('Cannot connect to API. Is the server running?');
}
```

---

## Quick Reference Table

| Endpoint | Method | Purpose | Response Type |
|----------|--------|---------|---------------|
| `/health` | GET | Check API status | JSON |
| `/schema` | GET | Get input format | JSON |
| `/migrate/json` | POST | Upload & get JSON | JSON with results |
| `/migrate` | POST | Upload & download Excel | Excel file |
| `/migrate/async` | POST | Upload async | JSON with job_id |
| `/jobs/{job_id}` | GET | Check job status | JSON |
| `/download/{job_id}` | GET | Download result | Excel file |

---

## Testing

**Test with curl:**
```bash
# Health check
curl http://localhost:8000/health

# Upload and get JSON
curl -X POST "http://localhost:8000/migrate/json" \
  -F "file=@sample_services.xlsx" \
  -F "source_provider=Azure"

# Upload and download Excel
curl -X POST "http://localhost:8000/migrate" \
  -F "file=@sample_services.xlsx" \
  -F "source_provider=GCP" \
  -o result.xlsx
```

**Interactive API Docs:**
Visit `http://localhost:8000/docs` to test all endpoints in your browser with Swagger UI.
