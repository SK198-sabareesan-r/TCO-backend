# AWS SSO Setup Guide for Claude Sonnet 4.5 Bedrock

This guide explains how to configure AWS SSO credentials to automatically authenticate with AWS Bedrock for Claude Sonnet 4.5.

## Prerequisites

- AWS CLI v2 installed ([Install Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html))
- AWS SSO account with access to Bedrock
- Python 3.8+ with boto3 installed

---

## Option 1: AWS SSO Profile (Recommended)

### Step 1: Configure AWS SSO

```bash
# Configure SSO
aws configure sso

# You'll be prompted for:
# SSO session name (e.g., my-company-sso)
# SSO start URL: https://your-org.awsapps.com/start
# SSO region: us-east-1
# Account and role selection
```

This will create a profile in `~/.aws/config`:

```ini
[profile your-sso-profile-name]
sso_session = my-company-sso
sso_account_id = 123456789012
sso_role_name = YourRoleName
region = us-east-1

[sso-session my-company-sso]
sso_start_url = https://your-org.awsapps.com/start
sso_region = us-east-1
sso_registration_scopes = sso:account:access
```

### Step 2: Login to AWS SSO

```bash
aws sso login --profile your-sso-profile-name
```

This will:
1. Open your browser for SSO authentication
2. Cache credentials locally (valid for hours/days depending on config)
3. Automatically refresh when needed

### Step 3: Configure `.env` File

```bash
# Copy the example file
cp .env.example .env

# Edit .env
nano .env  # or use your preferred editor
```

**Set these values in `.env`:**

```bash
# AWS SSO Profile (use the profile name from Step 1)
AWS_PROFILE=your-sso-profile-name

# AWS Region
AWS_REGION=us-east-1

# Bedrock Model for Claude Sonnet 4.5
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250514-v1:0

# PostgreSQL Database
DB_HOST=your-rds-hostname.region.rds.amazonaws.com
DB_PORT=5432
DB_NAME=aws_pricing
DB_USER=postgres
DB_PASSWORD=your-database-password

# Optional
ENABLE_CALCULATOR_LINKS=true
```

### Step 4: Verify Bedrock Access

Test your Bedrock access:

```bash
# Test with AWS CLI
aws bedrock list-foundation-models --profile your-sso-profile-name --region us-east-1

# Or test the Python app
python -c "
import boto3
import os
from dotenv import load_dotenv

load_dotenv()

session = boto3.Session(profile_name=os.getenv('AWS_PROFILE'))
bedrock = session.client('bedrock-runtime', region_name='us-east-1')
print('✅ Bedrock client initialized successfully')
"
```

### Step 5: Enable Claude Sonnet 4.5 in Bedrock

1. Go to [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Navigate to **Model access**
3. Click **Manage model access**
4. Enable: **Claude 3.5 Sonnet v2** (or latest Sonnet 4.5)
5. Wait for approval (usually instant)

### Step 6: Run Your Application

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Run the pipeline
python run_pipeline.py --input your_input.xlsx
```

---

## Option 2: Explicit Credentials (Not Recommended for SSO)

If you cannot use SSO profiles, you can use temporary credentials:

### Step 1: Get Temporary Credentials

```bash
# Login to SSO
aws sso login --profile your-sso-profile-name

# Get temporary credentials
aws configure export-credentials --profile your-sso-profile-name
```

This outputs:
```json
{
  "AccessKeyId": "ASIA...",
  "SecretAccessKey": "xxx...",
  "SessionToken": "xxx...",
  "Expiration": "2024-01-01T12:00:00Z"
}
```

### Step 2: Set Environment Variables

**In `.env`:**
```bash
# Comment out AWS_PROFILE
# AWS_PROFILE=your-sso-profile-name

# Use explicit credentials (expire in hours)
AWS_ACCESS_KEY_ID=ASIA...
AWS_SECRET_ACCESS_KEY=xxx...
AWS_SESSION_TOKEN=xxx...  # Add this for temporary credentials

AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250514-v1:0
```

⚠️ **Warning:** Temporary credentials expire (usually after 12 hours). You'll need to refresh them regularly.

---

## Option 3: AWS Secrets Manager (Production)

For production environments, store credentials in AWS Secrets Manager:

### Step 1: Store Credentials in Secrets Manager

```bash
aws secretsmanager create-secret \
  --name cloud-migration-app/credentials \
  --secret-string '{
    "AWS_PROFILE":"your-sso-profile-name",
    "AWS_REGION":"us-east-1",
    "BEDROCK_MODEL_ID":"us.anthropic.claude-sonnet-4-5-20250514-v1:0",
    "DB_HOST":"your-rds-hostname.region.rds.amazonaws.com",
    "DB_PORT":"5432",
    "DB_NAME":"aws_pricing",
    "DB_USER":"postgres",
    "DB_PASSWORD":"your-database-password"
  }' \
  --profile your-sso-profile-name
```

### Step 2: Add Secret Retrieval to Your Code

Create `utils/secrets.py`:

```python
import boto3
import json
import os
from functools import lru_cache

@lru_cache(maxsize=1)
def get_secrets():
    """Retrieve secrets from AWS Secrets Manager."""
    secret_name = os.getenv('SECRET_NAME', 'cloud-migration-app/credentials')
    region = os.getenv('AWS_REGION', 'us-east-1')
    
    # Create session with SSO profile
    profile = os.getenv('AWS_PROFILE')
    if profile:
        session = boto3.Session(profile_name=profile)
        client = session.client('secretsmanager', region_name=region)
    else:
        client = boto3.client('secretsmanager', region_name=region)
    
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except Exception as e:
        print(f"Error retrieving secrets: {e}")
        return {}

def load_secrets_to_env():
    """Load secrets from Secrets Manager into environment variables."""
    secrets = get_secrets()
    for key, value in secrets.items():
        if key not in os.environ:
            os.environ[key] = str(value)
```

### Step 3: Update Your Application Entry Point

In `run_pipeline.py` or `main.py`, add at the top:

```python
from utils.secrets import load_secrets_to_env

# Load secrets before anything else
load_secrets_to_env()
```

---

## IAM Permissions Required

Ensure your SSO role has these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListFoundationModels"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeSpotPriceHistory",
        "savingsplans:DescribeSavingsPlansOfferingRates",
        "savingsplans:DescribeSavingsPlansOfferings"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:cloud-migration-app/*"
    }
  ]
}
```

---

## Troubleshooting

### Issue: "ExpiredToken" error

**Solution:** Re-authenticate with SSO:
```bash
aws sso login --profile your-sso-profile-name
```

### Issue: "AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel"

**Solutions:**
1. Check IAM permissions (see above)
2. Verify Bedrock model access is enabled in the console
3. Ensure you're using the correct region (us-east-1 for Bedrock)

### Issue: "Could not connect to the endpoint URL"

**Solution:** Check the model ID and region:
```bash
# List available models
aws bedrock list-foundation-models --region us-east-1 --profile your-sso-profile-name

# Verify model ID
# For Claude Sonnet 4.5, use:
# us.anthropic.claude-sonnet-4-5-20250514-v1:0
```

### Issue: boto3 doesn't recognize AWS_PROFILE

**Solution:** Update boto3:
```bash
pip install --upgrade boto3 botocore
```

---

## Quick Start Checklist

- [ ] AWS CLI v2 installed
- [ ] AWS SSO configured (`aws configure sso`)
- [ ] Logged into SSO (`aws sso login --profile your-profile`)
- [ ] `.env` file created with `AWS_PROFILE` set
- [ ] Bedrock model access enabled for Claude Sonnet 4.5
- [ ] IAM permissions verified
- [ ] Database credentials added to `.env`
- [ ] Test Bedrock connection successful

---

## Support

For issues:
1. Check AWS CloudTrail logs for permission errors
2. Verify SSO session is active: `aws sts get-caller-identity --profile your-profile`
3. Test Bedrock directly: `aws bedrock list-foundation-models --profile your-profile`

---

**Next Steps:** Once configured, run your pipeline with:

```bash
python run_pipeline.py --input your_azure_export.xlsx
```

The application will automatically use your SSO credentials to authenticate with AWS Bedrock!
