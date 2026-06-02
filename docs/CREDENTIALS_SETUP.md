# Credentials Setup - Quick Reference

## 🎯 What You Need to Set Up

### 1. **AWS Credentials** (for Bedrock Claude Sonnet 4.5)
### 2. **PostgreSQL Database** (for AWS pricing data)
### 3. **Optional: AWS Secrets Manager** (for production)

---

## 📝 Summary of Credentials

| Credential | Purpose | Where Used |
|------------|---------|------------|
| `AWS_PROFILE` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS Bedrock (Claude LLM) | `tools/llm_mapper.py`, `pricing.py`, `agents/sql_generator_agent.py` |
| `AWS_REGION` | AWS region for Bedrock | All AWS API calls |
| `BEDROCK_MODEL_ID` | Claude Sonnet 4.5 model identifier | `tools/llm_mapper.py:163`, `agents/sql_generator_agent.py:458` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL RDS connection | `utils/db.py` |

---

## ⚡ Quick Setup (SSO Method - Recommended)

### Step 1: Configure AWS SSO

```bash
# Configure SSO
aws configure sso

# Follow prompts to set up your SSO profile
```

### Step 2: Login

```bash
aws sso login --profile your-sso-profile-name
```

### Step 3: Create `.env` File

```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env
```

**Your `.env` should look like:**

```bash
# AWS SSO Profile
AWS_PROFILE=your-sso-profile-name
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250514-v1:0

# PostgreSQL Database
DB_HOST=your-db-host.region.rds.amazonaws.com
DB_PORT=5432
DB_NAME=aws_pricing
DB_USER=postgres
DB_PASSWORD=your-secure-password

# Optional
ENABLE_CALCULATOR_LINKS=true
```

### Step 4: Enable Bedrock Model Access

1. Go to [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Click **Model access** → **Manage model access**
3. Enable **Claude 3.5 Sonnet v2** (Claude Sonnet 4.5)
4. Click **Save changes**

### Step 5: Verify

```bash
# Test Bedrock access
aws bedrock list-foundation-models --profile your-sso-profile-name --region us-east-1

# Test database connection
python -c "from utils.db import test_connection; from dotenv import load_dotenv; load_dotenv(); print('✅ DB Connected' if test_connection() else '❌ DB Connection Failed')"
```

### Step 6: Run Your Application

```bash
python run_pipeline.py --input your_input.xlsx
```

---

## 🔐 How SSO Works with This Application

### Before Changes (Old Method):
```python
# Required explicit credentials in .env
boto3.client(
    'bedrock-runtime',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)
```

### After Changes (New Method - SSO Support):
```python
# Can use AWS_PROFILE for SSO
if os.getenv('AWS_PROFILE'):
    session = boto3.Session(profile_name=os.getenv('AWS_PROFILE'))
    client = session.client('bedrock-runtime', region_name='us-east-1')
else:
    # Fallback to explicit credentials
    client = boto3.client('bedrock-runtime', ...)
```

**Benefits:**
- ✅ No hardcoded credentials
- ✅ Automatic token refresh
- ✅ Follows AWS security best practices
- ✅ Works with MFA/2FA

---

## 🏭 Production Setup (AWS Secrets Manager)

### Store Secrets

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
  }'
```

### Retrieve in Code

```python
import boto3
import json
import os

def get_secrets():
    client = boto3.client('secretsmanager', region_name='us-east-1')
    secret = client.get_secret_value(SecretId='cloud-migration-app/credentials')
    return json.loads(secret['SecretString'])

# Load secrets into environment
secrets = get_secrets()
for key, value in secrets.items():
    os.environ[key] = str(value)
```

---

## 🔍 Files Modified for SSO Support

| File | Changes |
|------|---------|
| `tools/llm_mapper.py` | Added SSO profile support in `_get_bedrock_client()` |
| `pricing.py` | Added SSO profile support for pricing, EC2, and savings plans clients |
| `.env.example` | Created template with all required credentials |
| `AWS_SSO_SETUP.md` | Comprehensive SSO setup guide |

---

## 🛡️ Required IAM Permissions

Your SSO role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeSpotPriceHistory",
        "savingsplans:DescribeSavingsPlansOfferingRates"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## ❓ Common Issues

### "ExpiredToken" Error
```bash
# Solution: Re-login to SSO
aws sso login --profile your-profile
```

### "AccessDeniedException: bedrock:InvokeModel"
1. Check Bedrock model access is enabled in console
2. Verify IAM permissions include `bedrock:InvokeModel`
3. Confirm you're in the correct region (`us-east-1`)

### "No module named 'dotenv'"
```bash
pip install python-dotenv
```

### Database Connection Failed
1. Check security group allows your IP
2. Verify RDS endpoint is correct
3. Test with: `psql -h your-host -U postgres -d aws_pricing`

---

## 📚 Additional Resources

- **Full SSO Setup Guide:** [AWS_SSO_SETUP.md](./AWS_SSO_SETUP.md)
- **AWS CLI Configuration:** https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html
- **Bedrock Documentation:** https://docs.aws.amazon.com/bedrock/
- **boto3 Session Guide:** https://boto3.amazonaws.com/v1/documentation/api/latest/guide/session.html

---

## ✅ Verification Checklist

Before running your application:

- [ ] AWS SSO configured and logged in
- [ ] `.env` file created with correct values
- [ ] Bedrock model access enabled (Claude Sonnet 4.5)
- [ ] Database credentials tested
- [ ] IAM permissions verified
- [ ] boto3/botocore updated to latest version
- [ ] Test run successful: `python run_pipeline.py --input sample.xlsx`

---

## 🎉 You're Ready!

Once all credentials are set up, your application will:

1. **Automatically authenticate** with AWS using SSO
2. **Connect to Bedrock** using Claude Sonnet 4.5
3. **Query PostgreSQL** for AWS pricing data
4. **Process your cloud migration** cost estimates

**No manual credential rotation needed!** 🚀
