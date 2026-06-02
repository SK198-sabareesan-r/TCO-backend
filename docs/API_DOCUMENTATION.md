# Cloud Migration Cost Estimator - API Documentation

## Overview

REST API for estimating AWS migration costs from Azure/GCP services. Upload an Excel file with your current cloud services and receive detailed AWS cost estimates with optimization recommendations.

**Base URL:** `http://localhost:8000`  
**API Version:** 2.0.0  
**Documentation:** `http://localhost:8000/docs` (Swagger UI)

---

## Quick Start

### 1. Start the API Server

```bash
cd cloud_migration
python api.py
```

Server will start on `http://localhost:8000`

### 2. Test Health Check

```bash
curl http://localhost:8000/health
```

### 3. Upload File for Migration

```bash
curl -X POST "http://localhost:8000/migrate" \
  -F "file=@azure_services.xlsx" \
  -F "source_provider=Azure" \
  -o aws_estimate.xlsx
```

---

## Authentication

Currently no authentication required. Add API keys or OAuth in production.

---

## Endpoints

### 1. Health Check

**GET** `/health`

Check API and database connectivity.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "components": {
    "api": "operational",
    "database": "connected",
    "llm": "operational"
  },
  "version": "2.0.0"
}
```

---

### 2. Get Input Schema

**GET** `/schema`

Get expected Excel file format and column definitions.

**Response:**
```json
{
  "description": "Expected columns in the input XLSX file",
  "source_providers": ["Azure", "GCP"],
  "target_provider": "AWS (fixed)",
  "required_columns": ["service_type", "current_provider"],
  "optional_columns": {
    "service_name": "Human-readable name",
    "service_type": "ec2 | rds | s3 | vpc | lambda",
    "vcpus": "Number of vCPUs",
    "memory_gib": "Memory in GiB",
    ...
  },
  "example_rows": [...]
}
```

---

### 3. Migrate (Synchronous - XLSX Output)

**POST** `/migrate`

Upload Excel file and download AWS estimate Excel file.

**Parameters:**
- `file` (form-data, required): XLSX file with cloud services
- `source_provider` (form-data, required): "Azure" or "GCP"

**Request Example (cURL):**
```bash
curl -X POST "http://localhost:8000/migrate" \
  -F "file=@azure_services.xlsx" \
  -F "source_provider=Azure" \
  -o aws_estimate.xlsx
```

**Request Example (JavaScript):**
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_provider', 'Azure');

const response = await fetch('http://localhost:8000/migrate', {
  method: 'POST',
  body: formData
});

const blob = await response.blob();
const url = window.URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = 'aws_estimate.xlsx';
a.click();
```

**Response:**
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- File: Excel with 5 sheets (Summary, All Matches, CSP Options, Cost Comparison, Mapping Details)

**Processing Time:** ~25-35 seconds per service

---

### 4. Migrate (Synchronous - JSON Output)

**POST** `/migrate/json`

Upload Excel file and receive JSON results.

**Parameters:**
- `file` (form-data, required): XLSX file with cloud services
- `source_provider` (form-data, required): "Azure" or "GCP"

**Request Example (JavaScript):**
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_provider', 'Azure');

const response = await fetch('http://localhost:8000/migrate/json', {
  method: 'POST',
  body: formData
});

const data = await response.json();
console.log(data.summary);
console.log(data.results);
```

**Response:**
```json
{
  "success": true,
  "source_provider": "Azure",
  "target_provider": "AWS",
  "summary": {
    "total_services": 10,
    "total_current_cost": 5000.00,
    "total_aws_ondemand_cost": 3200.00,
    "total_aws_optimized_cost": 1800.00,
    "total_savings": 3200.00,
    "savings_percent": 64.0,
    "processing_time_seconds": 285.5,
    "token_usage": {
      "total_input_tokens": 11400,
      "total_output_tokens": 15000,
      "total_cost_usd": 0.18
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
        "current_monthly_cost_usd": 450.00
      },
      "best_match": {
        "instance_type": "t3a.xlarge",
        "vcpus": 4,
        "memory_gib": "16 GiB",
        "regioncode": "ap-south-1"
      },
      "optimised": {
        "instance_type": "t3a.xlarge",
        "plan_label": "CSP 3yr All Upfront",
        "monthly_usd": 65.70,
        "annual_usd": 788.40,
        "discount_percent": 60
      },
      "comparison": {
        "current_provider": {"monthly_usd": 450.00},
        "aws_ondemand": {"monthly_usd": 140.16},
        "aws_optimised": {"monthly_usd": 65.70},
        "savings": {
          "monthly_usd": 384.30,
          "annual_usd": 4611.60,
          "percent": 85.4,
          "verdict": "🟢 Great savings"
        }
      },
      "calculator_link": "https://calculator.aws/#/estimate?id=abc123"
    }
  ],
  "timestamp": "2024-01-15T10:35:00Z"
}
```

---

### 5. Migrate (Asynchronous - Background Processing)

**POST** `/migrate/async`

Upload Excel file and get job ID for tracking. Use for large files or long-running migrations.

**Parameters:**
- `file` (form-data, required): XLSX file with cloud services
- `source_provider` (form-data, required): "Azure" or "GCP"

**Request Example:**
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_provider', 'Azure');

const response = await fetch('http://localhost:8000/migrate/async', {
  method: 'POST',
  body: formData
});

const data = await response.json();
const jobId = data.job_id;

// Poll for status
const checkStatus = async () => {
  const statusResponse = await fetch(`http://localhost:8000/jobs/${jobId}`);
  const status = await statusResponse.json();
  
  if (status.status === 'completed') {
    // Download result
    window.location.href = `http://localhost:8000/download/${jobId}`;
  } else if (status.status === 'failed') {
    console.error('Migration failed:', status.error);
  } else {
    // Still processing, check again in 5 seconds
    setTimeout(checkStatus, 5000);
  }
};

checkStatus();
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "progress": 0,
  "message": "Job queued for processing",
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

### 6. Get Job Status

**GET** `/jobs/{job_id}`

Get status of an async migration job.

**Parameters:**
- `job_id` (path, required): Job ID from /migrate/async

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 45,
  "message": "Processing service 5 of 10",
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null,
  "result_url": null
}
```

**Status Values:**
- `pending`: Job queued
- `processing`: Job in progress
- `completed`: Job finished successfully
- `failed`: Job failed with error

---

### 7. Download Result

**GET** `/download/{job_id}`

Download result Excel file for completed job.

**Parameters:**
- `job_id` (path, required): Job ID from /migrate/async

**Response:**
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- File: Excel with migration results

---

### 8. Delete Job

**DELETE** `/jobs/{job_id}`

Delete job and cleanup temporary files.

**Parameters:**
- `job_id` (path, required): Job ID to delete

**Response:**
```json
{
  "message": "Job 550e8400-e29b-41d4-a716-446655440000 deleted successfully"
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "success": false,
  "error": "Error message",
  "status_code": 400,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

**Common Error Codes:**
- `400`: Bad Request (invalid file type, invalid provider)
- `404`: Not Found (job not found)
- `500`: Internal Server Error (pipeline failure, database error)

---

## Excel File Format

### Input File Structure

**Option 1: Single Sheet**
```
Sheet: Services
┌──────────────┬────────────────┬──────┬────────┬──────────────┬──────┐
│ service_name │ service_type   │ vCPUs│ Memory │ region       │ ...  │
├──────────────┼────────────────┼──────┼────────┼──────────────┼──────┤
│ Web Server   │ ec2            │ 4    │ 16     │ Central India│ ...  │
│ Database     │ rds            │ 8    │ 32     │ Central India│ ...  │
└──────────────┴────────────────┴──────┴────────┴──────────────┴──────┘
```

**Option 2: Multi-Sheet (Azure Export)**
```
Sheet: Virtual Machines
┌──────────────┬────────────────┬──────┬────────┬──────────────┐
│ Name         │ Size           │ vCPU │ Memory │ Location     │
├──────────────┼────────────────┼──────┼────────┼──────────────┤
│ web-server-1 │ Standard_D4s_v3│ 4    │ 16     │ Central India│
└──────────────┴────────────────┴──────┴────────┴──────────────┘

Sheet: SQL DBs
┌──────────────┬────────┬──────────┬──────────────┐
│ Name         │ SKU    │ Capacity │ DataMaxSizeGB│
├──────────────┼────────┼──────────┼──────────────┤
│ prod-db      │ GP_Gen5│ 4        │ 100          │
└──────────────┴────────┴──────────┴──────────────┘
```

### Output File Structure

**5 Sheets:**

1. **Summary**: One row per service with best match and savings
2. **All Matches**: All AWS candidates with pricing
3. **CSP Options**: All 6 Savings Plans + Spot pricing
4. **Cost Comparison**: Current vs AWS OnDemand vs Optimized
5. **Mapping Details**: Parameters used for matching

---

## Frontend Integration Examples

### React Example

```jsx
import React, { useState } from 'react';

function MigrationUpload() {
  const [file, setFile] = useState(null);
  const [provider, setProvider] = useState('Azure');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_provider', provider);

    try {
      const response = await fetch('http://localhost:8000/migrate/json', {
        method: 'POST',
        body: formData
      });

      const data = await response.json();
      setResult(data);
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input
          type="file"
          accept=".xlsx,.xls"
          onChange={(e) => setFile(e.target.files[0])}
        />
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="Azure">Azure</option>
          <option value="GCP">GCP</option>
        </select>
        <button type="submit" disabled={!file || loading}>
          {loading ? 'Processing...' : 'Estimate Costs'}
        </button>
      </form>

      {result && (
        <div>
          <h2>Summary</h2>
          <p>Total Services: {result.summary.total_services}</p>
          <p>Current Cost: ${result.summary.total_current_cost}/mo</p>
          <p>AWS Optimized: ${result.summary.total_aws_optimized_cost}/mo</p>
          <p>Savings: ${result.summary.total_savings}/mo ({result.summary.savings_percent}%)</p>
        </div>
      )}
    </div>
  );
}
```

### Vue.js Example

```vue
<template>
  <div>
    <form @submit.prevent="uploadFile">
      <input type="file" @change="handleFileChange" accept=".xlsx,.xls" />
      <select v-model="provider">
        <option value="Azure">Azure</option>
        <option value="GCP">GCP</option>
      </select>
      <button type="submit" :disabled="!file || loading">
        {{ loading ? 'Processing...' : 'Estimate Costs' }}
      </button>
    </form>

    <div v-if="result">
      <h2>Summary</h2>
      <p>Total Services: {{ result.summary.total_services }}</p>
      <p>Current Cost: ${{ result.summary.total_current_cost }}/mo</p>
      <p>AWS Optimized: ${{ result.summary.total_aws_optimized_cost }}/mo</p>
      <p>Savings: ${{ result.summary.total_savings }}/mo ({{ result.summary.savings_percent }}%)</p>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      file: null,
      provider: 'Azure',
      loading: false,
      result: null
    };
  },
  methods: {
    handleFileChange(event) {
      this.file = event.target.files[0];
    },
    async uploadFile() {
      this.loading = true;

      const formData = new FormData();
      formData.append('file', this.file);
      formData.append('source_provider', this.provider);

      try {
        const response = await fetch('http://localhost:8000/migrate/json', {
          method: 'POST',
          body: formData
        });

        this.result = await response.json();
      } catch (error) {
        console.error('Error:', error);
      } finally {
        this.loading = false;
      }
    }
  }
};
</script>
```

---

## CORS Configuration

The API has CORS enabled for all origins in development. For production, configure specific origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Rate Limiting

Currently no rate limiting. Implement in production using:
- `slowapi` library
- API Gateway rate limiting
- Redis-based rate limiting

---

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - DB_HOST=${DB_HOST}
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
    volumes:
      - ./:/app
```

---

## Support

For questions or issues:
- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`
- Contact: development-team@example.com

---

## Changelog

### v2.0.0 (2024-01-15)
- Added async migration endpoint
- Added job tracking and progress
- Enhanced error handling
- Added CORS support
- Improved JSON response format
- Added token usage tracking

### v1.0.0 (2024-01-01)
- Initial release
- Synchronous migration endpoints
- XLSX and JSON output formats
