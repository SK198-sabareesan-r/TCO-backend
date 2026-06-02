# Frontend Team Handoff Document

## Quick Start

**API Base URL:** `http://localhost:8000`  
**API Documentation:** `http://localhost:8000/docs` (Interactive Swagger UI)  
**Status:** ✅ Ready for integration

---

## What You Need to Know

### 1. Core Endpoints (3 main ones)

#### Health Check
```
GET /health
```
Returns API status - use this to check if backend is ready.

#### Upload & Get Results (Recommended for most cases)
```
POST /migrate/json
```
- Upload Excel file
- Get JSON response with all cost data
- Best for displaying results in your UI

#### Upload & Download Excel
```
POST /migrate
```
- Upload Excel file  
- Download Excel file with 5 detailed sheets
- Best for "download report" feature

### 2. Request Format

All endpoints use `multipart/form-data`:

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);  // Excel file
formData.append('source_provider', 'Azure');   // or 'GCP'

const response = await fetch('http://localhost:8000/migrate/json', {
  method: 'POST',
  body: formData
});

const data = await response.json();
```

### 3. Response Format (JSON endpoint)

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
    "processing_time_seconds": 42.69
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
        "current_monthly_cost_usd": 450.00
      },
      "best_match": {
        "instance_type": "m5.xlarge",
        "vcpus": 4,
        "memory_gib": 16,
        "monthly_usd": 192.72
      },
      "optimised": {
        "instance_type": "m5.xlarge",
        "plan": "1yr_partial_upfront",
        "monthly_usd": 118.25,
        "savings_vs_current": 331.75,
        "savings_percent": 73.7
      }
    }
  ]
}
```

---

## Minimal Working Example (Copy & Paste)

```html
<!DOCTYPE html>
<html>
<head>
  <title>Cloud Migration Estimator</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
    .upload-section { border: 2px dashed #ccc; padding: 30px; text-align: center; }
    .results { margin-top: 30px; }
    .summary { background: #f0f0f0; padding: 20px; border-radius: 5px; }
    .service-card { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }
    .savings { color: green; font-weight: bold; }
  </style>
</head>
<body>
  <h1>☁️ Cloud Migration Cost Estimator</h1>
  
  <div class="upload-section">
    <h2>Upload Your Services</h2>
    <input type="file" id="fileInput" accept=".xlsx,.xls">
    <select id="providerSelect">
      <option value="Azure">Azure</option>
      <option value="GCP">GCP</option>
    </select>
    <button onclick="uploadFile()">Estimate Costs</button>
    <p id="status"></p>
  </div>
  
  <div id="results" class="results" style="display: none;">
    <div class="summary">
      <h2>💰 Cost Summary</h2>
      <p>Total Services: <strong id="totalServices"></strong></p>
      <p>Current Cost: <strong id="currentCost"></strong></p>
      <p>AWS Optimized Cost: <strong id="awsCost"></strong></p>
      <p class="savings">Total Savings: <span id="savings"></span> (<span id="savingsPercent"></span>%)</p>
    </div>
    
    <h3>Service Details</h3>
    <div id="serviceList"></div>
  </div>
  
  <script>
    async function uploadFile() {
      const fileInput = document.getElementById('fileInput');
      const provider = document.getElementById('providerSelect').value;
      const status = document.getElementById('status');
      
      if (!fileInput.files[0]) {
        alert('Please select a file');
        return;
      }
      
      status.textContent = '⏳ Processing... (this may take 30-60 seconds)';
      
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      formData.append('source_provider', provider);
      
      try {
        const response = await fetch('http://localhost:8000/migrate/json', {
          method: 'POST',
          body: formData
        });
        
        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'Upload failed');
        }
        
        const data = await response.json();
        displayResults(data);
        status.textContent = '✅ Complete!';
        
      } catch (error) {
        status.textContent = '❌ Error: ' + error.message;
        console.error(error);
      }
    }
    
    function displayResults(data) {
      // Show results section
      document.getElementById('results').style.display = 'block';
      
      // Display summary
      const summary = data.summary;
      document.getElementById('totalServices').textContent = summary.total_services;
      document.getElementById('currentCost').textContent = '$' + summary.total_current_cost.toFixed(2) + '/mo';
      document.getElementById('awsCost').textContent = '$' + summary.total_aws_optimized_cost.toFixed(2) + '/mo';
      document.getElementById('savings').textContent = '$' + summary.total_savings.toFixed(2) + '/mo';
      document.getElementById('savingsPercent').textContent = summary.savings_percent.toFixed(1);
      
      // Display services
      const serviceList = document.getElementById('serviceList');
      serviceList.innerHTML = '';
      
      data.results.forEach(result => {
        const card = document.createElement('div');
        card.className = 'service-card';
        
        const input = result.input;
        const optimised = result.optimised;
        const savings = input.current_monthly_cost_usd - optimised.monthly_usd;
        const savingsPercent = (savings / input.current_monthly_cost_usd * 100).toFixed(1);
        
        card.innerHTML = `
          <h4>${input.service_name || 'Service'}</h4>
          <p><strong>Current:</strong> ${input.instance_type} @ $${input.current_monthly_cost_usd}/mo</p>
          <p><strong>AWS Recommended:</strong> ${optimised.instance_type} (${optimised.plan}) @ $${optimised.monthly_usd.toFixed(2)}/mo</p>
          <p class="savings">Savings: $${savings.toFixed(2)}/mo (${savingsPercent}%)</p>
        `;
        
        serviceList.appendChild(card);
      });
    }
  </script>
</body>
</html>
```

**Save this as `test.html` and open in browser - it works immediately!**

---

## Input File Format

Users upload Excel files with these columns:

**Required:**
- `service_type`: ec2, rds, s3, vpc, lambda
- `current_provider`: Azure or GCP

**Common Optional:**
- `service_name`: Display name
- `instance_type`: Current instance (e.g., Standard_D4s_v3)
- `vcpus`: Number of CPUs
- `memory_gib`: RAM in GB
- `storage_gb`: Disk size
- `current_monthly_cost_usd`: Current cost for comparison

**Full schema available at:** `GET /schema`

---

## Processing Time

- **Small files (1-5 services):** 10-20 seconds
- **Medium files (5-15 services):** 30-60 seconds  
- **Large files (15+ services):** 1-3 minutes

Show a loading indicator during processing.

---

## Error Handling

```javascript
try {
  const response = await fetch('http://localhost:8000/migrate/json', {
    method: 'POST',
    body: formData
  });
  
  if (!response.ok) {
    const error = await response.json();
    
    // Common errors:
    if (error.detail.includes('file type')) {
      alert('Please upload an Excel file (.xlsx)');
    } else if (error.detail.includes('provider')) {
      alert('Please select Azure or GCP as source provider');
    } else {
      alert('Error: ' + error.detail);
    }
    return;
  }
  
  const data = await response.json();
  // Handle success
  
} catch (error) {
  alert('Network error. Is the API server running?');
  console.error(error);
}
```

---

## Testing

### 1. Check if API is running
```bash
curl http://localhost:8000/health
```

### 2. Generate test file
```bash
cd cloud_migration
python run_pipeline.py --create-sample
```
This creates `sample_services.xlsx` with 10 test services.

### 3. Test with curl
```bash
curl -X POST "http://localhost:8000/migrate/json" \
  -F "file=@sample_services.xlsx" \
  -F "source_provider=Azure" \
  | python -m json.tool
```

---

## Common UI Patterns

### Pattern 1: Simple Upload + Results
1. User uploads Excel file
2. Show loading spinner
3. Display cost summary + service list
4. Offer "Download Full Report" button (calls `/migrate` endpoint)

### Pattern 2: Multi-step Wizard
1. Upload file
2. Confirm detected services
3. Show processing progress
4. Display results with charts

### Pattern 3: Dashboard
1. Upload multiple files
2. Compare scenarios side-by-side
3. Export combined report

---

## CORS Note

The API has CORS enabled for all origins (`allow_origins=["*"]`). For production, this should be restricted to your frontend domain.

---

## Need Help?

1. **Interactive API Docs:** http://localhost:8000/docs
   - Try all endpoints directly in browser
   - See request/response formats
   - Test with sample data

2. **Full Integration Guide:** See `FRONTEND_INTEGRATION.md`
   - React examples
   - WebSocket for progress tracking
   - Advanced patterns

3. **Sample Files:** Run `python run_pipeline.py --create-sample`

4. **API Logs:** Check the terminal where `python api.py` is running

---

## Deployment Checklist (When Ready)

- [ ] Update CORS to specific frontend domain
- [ ] Add authentication (API keys)
- [ ] Set up HTTPS
- [ ] Configure file size limits
- [ ] Add rate limiting
- [ ] Set up monitoring

---

## Quick Reference

| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/health` | GET | Check API status | JSON status |
| `/schema` | GET | Get input format | JSON schema |
| `/migrate/json` | POST | Upload & get JSON | JSON results |
| `/migrate` | POST | Upload & download Excel | Excel file |
| `/docs` | GET | Interactive API docs | HTML page |

**That's it! You have everything you need to integrate. Start with the minimal example above and expand from there.**
