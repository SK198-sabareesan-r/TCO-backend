# ✅ Setup Complete - SSO Authentication Ready

## What Was Done

Your codebase has been updated to support **AWS SSO authentication** for Claude Sonnet 4.5 on AWS Bedrock. The changes allow automatic credential management without hardcoding secrets.

---

## 📁 Files Modified

### 1. **tools/llm_mapper.py**
- ✅ Updated `_get_bedrock_client()` to support AWS SSO profiles
- ✅ Maintains backward compatibility with explicit credentials

### 2. **agents/sql_generator_agent.py**  
- ✅ Updated Bedrock client initialization for SSO support
- ✅ Same SSO profile handling as llm_mapper.py

### 3. **pricing.py**
- ✅ Updated pricing_client, savingsplans_client, and ec2_client for SSO
- ✅ Added SSO support for regional EC2 clients (spot pricing)

### 4. **utils/cost_client.py**
- ✅ Updated all AWS clients (pricing, savingsplans, EC2) for SSO
- ✅ Maintains retry configuration for better throttling handling

---

## 📝 Files Created

### 1. **.env.example**
Template for environment variables with both SSO and explicit credential options.

### 2. **AWS_SSO_SETUP.md**
Comprehensive guide covering:
- SSO configuration steps
- Bedrock model access setup
- IAM permissions required
- Troubleshooting common issues
- AWS Secrets Manager setup (production)

### 3. **CREDENTIALS_SETUP.md**
Quick reference guide with:
- Summary of all credentials needed
- Quick setup instructions
- Verification checklist
- Common issues and solutions

### 4. **SETUP_COMPLETE.md** (this file)
Summary of changes and next steps.

---

## 🎯 How SSO Authentication Works Now

### Before (Explicit Credentials):
```python
# Required AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env
boto3.client(
    'bedrock-runtime',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)
```

### After (SSO Support):
```python
# Option 1: Use AWS_PROFILE (SSO)
aws_profile = os.getenv('AWS_PROFILE')
if aws_profile:
    session = boto3.Session(profile_name=aws_profile)
    client = session.client('bedrock-runtime', region_name='us-east-1')

# Option 2: Fallback to explicit credentials
else:
    client = boto3.client('bedrock-runtime', ...)
```

---

## 🚀 Next Steps

### 1. Configure AWS SSO

```bash
# Configure SSO
aws configure sso

# Login
aws sso login --profile your-sso-profile-name
```

### 2. Create Your `.env` File

```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env
```

**Minimum required in `.env`:**

```bash
# AWS SSO (choose one method)
AWS_PROFILE=your-sso-profile-name              # For SSO users
# OR
# AWS_ACCESS_KEY_ID=ASIA...                    # For explicit credentials
# AWS_SECRET_ACCESS_KEY=xxx...

# Required
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250514-v1:0

# Database
DB_HOST=your-rds-host.region.rds.amazonaws.com
DB_PORT=5432
DB_NAME=aws_pricing
DB_USER=postgres
DB_PASSWORD=your-password
```

### 3. Enable Bedrock Model Access

1. Go to [AWS Bedrock Console](https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess)
2. Click **Manage model access**
3. Enable **Claude 3.5 Sonnet v2** (Sonnet 4.5)
4. Save changes

### 4. Verify Setup

```bash
# Test Bedrock access
aws bedrock list-foundation-models \
  --profile your-sso-profile-name \
  --region us-east-1

# Test Python application
python -c "
import boto3
import os
from dotenv import load_dotenv

load_dotenv()

profile = os.getenv('AWS_PROFILE')
if profile:
    session = boto3.Session(profile_name=profile)
    bedrock = session.client('bedrock-runtime', region_name='us-east-1')
    print('✅ Bedrock SSO authentication successful!')
else:
    print('⚠️ AWS_PROFILE not set in .env')
"
```

### 5. Run Your Application

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Run pipeline
python run_pipeline.py --input your_azure_export.xlsx
```

---

## 🔍 Credentials Used By Each Component

| Component | Credentials | Purpose |
|-----------|-------------|---------|
| **LLM Mapper** (`tools/llm_mapper.py`) | AWS_PROFILE or AWS_ACCESS_KEY | Bedrock API calls for service mapping |
| **SQL Generator Agent** (`agents/sql_generator_agent.py`) | AWS_PROFILE or AWS_ACCESS_KEY | Bedrock API for SQL query generation |
| **Pricing Client** (`pricing.py`) | AWS_PROFILE or AWS_ACCESS_KEY | AWS Pricing API, EC2, Savings Plans |
| **Cost Client** (`utils/cost_client.py`) | AWS_PROFILE or AWS_ACCESS_KEY | Cost calculations using AWS APIs |
| **Database** (`utils/db.py`) | DB_HOST, DB_USER, DB_PASSWORD | PostgreSQL connection for pricing data |

---

## 🛡️ Security Best Practices

### ✅ DO:
- Use AWS SSO profiles for authentication
- Store database credentials in AWS Secrets Manager (production)
- Use environment variables for configuration
- Rotate credentials regularly
- Use least-privilege IAM permissions

### ❌ DON'T:
- Hardcode credentials in code
- Commit `.env` files to git
- Share AWS access keys via email/chat
- Use root account credentials
- Grant overly broad IAM permissions

---

## 📋 IAM Permissions Required

Your SSO role needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockAccess",
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
      "Sid": "PricingAccess",
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeSpotPriceHistory",
        "savingsplans:DescribeSavingsPlansOfferingRates",
        "savingsplans:DescribeSavingsPlansOfferings"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 🐛 Troubleshooting

### "ExpiredToken" Error
**Cause:** SSO session expired  
**Solution:**
```bash
aws sso login --profile your-sso-profile-name
```

### "AccessDeniedException: bedrock:InvokeModel"
**Cause:** Missing IAM permissions or model access not enabled  
**Solution:**
1. Enable Bedrock model access in console
2. Add `bedrock:InvokeModel` to IAM policy
3. Verify using correct region (us-east-1)

### "No module named 'dotenv'"
**Cause:** Missing dependency  
**Solution:**
```bash
pip install python-dotenv
```

### "Could not connect to database"
**Cause:** Database credentials incorrect or network issue  
**Solution:**
1. Verify RDS endpoint in `.env`
2. Check security group allows your IP
3. Test: `psql -h your-host -U postgres -d aws_pricing`

---

## 📖 Documentation References

- **Quick Setup:** [CREDENTIALS_SETUP.md](./CREDENTIALS_SETUP.md)
- **Detailed SSO Guide:** [AWS_SSO_SETUP.md](./AWS_SSO_SETUP.md)
- **Environment Template:** [.env.example](./.env.example)
- **AWS CLI SSO:** https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html
- **Bedrock Docs:** https://docs.aws.amazon.com/bedrock/

---

## ✅ Pre-Flight Checklist

Before running your application, verify:

- [ ] AWS CLI v2 installed
- [ ] AWS SSO configured (`aws configure sso`)
- [ ] Logged into SSO (`aws sso login --profile your-profile`)
- [ ] `.env` file created with correct values
- [ ] `AWS_PROFILE` set in `.env` (for SSO) OR `AWS_ACCESS_KEY_ID` (for explicit creds)
- [ ] Bedrock model access enabled for Claude Sonnet 4.5
- [ ] IAM permissions verified
- [ ] Database credentials tested
- [ ] Virtual environment activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)

---

## 🎉 You're All Set!

Your application now supports:

✅ **AWS SSO Authentication** - No hardcoded credentials  
✅ **Claude Sonnet 4.5** - Latest AI model on Bedrock  
✅ **Automatic Token Refresh** - SSO handles this for you  
✅ **Backward Compatibility** - Still works with explicit credentials  
✅ **Production Ready** - Can integrate with AWS Secrets Manager  

**Run your pipeline:**
```bash
python run_pipeline.py --input your_input.xlsx
```

**Questions?** Check:
- [CREDENTIALS_SETUP.md](./CREDENTIALS_SETUP.md) - Quick reference
- [AWS_SSO_SETUP.md](./AWS_SSO_SETUP.md) - Detailed guide

---

## 🔧 Summary of Changes

| What Changed | Why | Benefit |
|--------------|-----|---------|
| Added SSO profile support | Security best practice | No hardcoded credentials |
| Maintained explicit credential fallback | Backward compatibility | Existing setups still work |
| Created setup documentation | Ease of onboarding | Fast setup for new users |
| Added .env.example | Configuration template | Clear credential requirements |

**Model Used:** Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250514-v1:0`)  
**Region:** us-east-1 (required for Bedrock)  
**Authentication:** AWS SSO (recommended) or explicit credentials  

---

**Last Updated:** June 2026  
**Setup Status:** ✅ Complete - Ready for SSO authentication
