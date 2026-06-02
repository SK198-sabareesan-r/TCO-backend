# How to Start the API Server

## Quick Start

### Option 1: Using Python directly
```bash
# Make sure you're in the cloud_migration directory
cd cloud_migration

# Activate virtual environment (if using one)
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Start the API server
python api.py
```

### Option 2: Using uvicorn directly
```bash
cd cloud_migration
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

## What You Should See

When the server starts successfully, you'll see:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

## Access Points

Once the server is running:
- **API Base URL**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs (Swagger UI)
- **Alternative Docs**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Testing the API

### 1. Test Health Check
```bash
curl http://localhost:8000/health
```

### 2. Run the Test Suite
```bash
# In a new terminal (keep the API server running)
python test_api.py
```

### 3. Upload a File
```bash
curl -X POST "http://localhost:8000/migrate" \
  -F "file=@sample_services.xlsx" \
  -F "source_provider=Azure" \
  -o aws_estimate.xlsx
```

## Troubleshooting

### Port Already in Use
If you see "Address already in use", change the port:
```bash
python api.py --port 8001
```

Or kill the process using port 8000:
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Linux/Mac
lsof -ti:8000 | xargs kill -9
```

### Module Not Found
Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### Database Connection Error
Check your .env file has correct database credentials:
```
DB_HOST=your_rds_endpoint
DB_PORT=5432
DB_NAME=aws_pricing
DB_USER=your_user
DB_PASSWORD=your_password
```

## Development Mode

For development with auto-reload:
```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

## Production Mode

For production deployment:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
```

## Stopping the Server

Press `CTRL+C` in the terminal where the server is running.
