# LLM fallback mapper using AWS Bedrock
"""
tools/llm_mapper.py
-------------------
LLM Fallback Mapping Tool using AWS Bedrock.

When SQL matching returns 0 results, this tool uses Claude via AWS Bedrock to:
1. Understand the foreign cloud service (GCP/Azure)
2. Map it to the closest AWS equivalent
3. Extract normalised spec parameters
4. Return structured mapping suggestions

The agent will then re-try SQL with LLM-suggested parameters.
"""

import json
import logging
import os
from dotenv import load_dotenv
from config.secrets import get_secret, get_aws_session
from utils.token_tracker import track_tokens

load_dotenv()
logger = logging.getLogger(__name__)

_bedrock_client = None


def _get_bedrock_client():
    """Get or create AWS Bedrock client (credentials via Secrets Manager → .env)."""
    global _bedrock_client
    if _bedrock_client is None:
        session = get_aws_session()
        _bedrock_client = session.client(
            service_name='bedrock-runtime',
            region_name=get_secret('AWS_REGION', 'us-east-1'),
        )
    return _bedrock_client


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER KNOWLEDGE BASE (Few-shot examples for the LLM)
# ─────────────────────────────────────────────────────────────────────────────

GCP_TO_AWS_EXAMPLES = """
GCP Instance  →  AWS Equivalent  |  vCPU  |  Memory
n1-standard-1 →  t3.small        |  1     |  3.75 GiB (≈4 GiB AWS)
n1-standard-2 →  t3.medium       |  2     |  7.5 GiB  (≈8 GiB AWS)
n1-standard-4 →  m5.xlarge       |  4     |  15 GiB   (≈16 GiB AWS)
n1-standard-8 →  m5.2xlarge      |  8     |  30 GiB   (≈32 GiB AWS)
n2-standard-4 →  m5.xlarge       |  4     |  16 GiB
n2-standard-8 →  m5.2xlarge      |  8     |  32 GiB
n2-highmem-4  →  r5.xlarge       |  4     |  32 GiB
n2-highcpu-8  →  c5.2xlarge      |  8     |  16 GiB
e2-medium     →  t3.medium       |  2     |  4 GiB
e2-standard-4 →  m5.xlarge       |  4     |  16 GiB
"""

AZURE_TO_AWS_EXAMPLES = """
Azure Instance    →  AWS Equivalent  |  vCPU  |  Memory
Standard_B1s      →  t3.micro        |  1     |  2 GiB
Standard_B2s      →  t3.small        |  2     |  4 GiB
Standard_D2s_v3   →  t3.medium       |  2     |  8 GiB
Standard_D4s_v3   →  m5.xlarge       |  4     |  16 GiB
Standard_D8s_v3   →  m5.2xlarge      |  8     |  32 GiB
Standard_D16s_v3  →  m5.4xlarge      |  16    |  64 GiB
Standard_E4s_v3   →  r5.xlarge       |  4     |  32 GiB
Standard_E8s_v3   →  r5.2xlarge      |  8     |  64 GiB
Standard_F4s_v2   →  c5.xlarge       |  4     |  8 GiB
Standard_F8s_v2   →  c5.2xlarge      |  8     |  16 GiB
Azure SQL Basic   →  db.t3.small     |  -     |  RDS equivalent
Azure SQL S3      →  db.m5.large     |  -     |  RDS equivalent
Azure Blob Storage→  S3 Standard     |  -     |  Object storage
Azure Functions   →  Lambda          |  -     |  Serverless
Azure VNet        →  VPC             |  -     |  Network
"""

SYSTEM_PROMPT = f"""You are an expert cloud infrastructure architect specialising in 
GCP-to-AWS and Azure-to-AWS migrations.

Your task is to analyse a cloud service specification and return a structured JSON mapping 
to the closest AWS equivalent.

Known mappings for reference:
{GCP_TO_AWS_EXAMPLES}
{AZURE_TO_AWS_EXAMPLES}

You MUST respond with ONLY valid JSON in this exact structure, no other text:
{{
  "service_type": "ec2|rds|s3|vpc|lambda",
  "suggested_instance_type": "e.g. m5.xlarge or null",
  "vcpus": <integer or null>,
  "memory_gib": <float or null>,
  "aws_region": "AWS display region name e.g. US East (N. Virginia)",
  "operating_system": "Linux|Windows",
  "tenancy": "Shared|Dedicated",
  "confidence": "high|medium|low"
}}

Keep response minimal - no reasoning or alternatives needed.
"""


# ─────────────────────────────────────────────────────────────────────────────
# CORE LLM FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def llm_map_service(
    service_type: str,
    current_provider: str,
    instance_type: str = None,
    vcpus: int = None,
    memory_gib: float = None,
    region: str = None,
    operating_system: str = None,
    extra_context: str = None,
) -> dict:
    """
    Use Claude via AWS Bedrock to map a foreign cloud service to AWS equivalent specs.
    Returns a structured dict with suggested AWS parameters.
    """
    user_message = f"""
Map this {current_provider.upper()} service to AWS:

Provider:     {current_provider}
Service Type: {service_type}
Instance:     {instance_type or 'Not specified'}
vCPUs:        {vcpus or 'Not specified'}
Memory (GiB): {memory_gib or 'Not specified'}
Region:       {region or 'Not specified'}
OS:           {operating_system or 'Linux'}
Extra Info:   {extra_context or 'None'}

Return ONLY the JSON mapping structure.
"""

    try:
        client = _get_bedrock_client()
        
        # Prepare request for Bedrock with prompt caching
        # Cache the system prompt (static content: GCP/Azure examples, JSON structure)
        # This reduces input tokens by ~1100 tokens per call after the first call
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "system": [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}  # Cache system prompt
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        }
        
        # Call Bedrock with model ID from environment
        model_id = get_secret('BEDROCK_MODEL_ID', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body)
        )
        
        # Parse response
        response_body = json.loads(response['body'].read())
        raw_text = response_body['content'][0]['text'].strip()
        
        # Track token usage (including cache metrics)
        usage = response_body.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
        cache_read_tokens = usage.get('cache_read_input_tokens', 0)
        
        # Log cache performance
        if cache_creation_tokens > 0:
            logger.info(f"📝 Cache write: {cache_creation_tokens} tokens cached")
        if cache_read_tokens > 0:
            logger.info(f"⚡ Cache hit: {cache_read_tokens} tokens read from cache (90% discount!)")
        
        if input_tokens or output_tokens:
            track_tokens(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                operation="llm_fallback_mapping",
                model=model_id,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens
            )
            # Enhanced logging with cache information
            cache_info = ""
            if cache_read_tokens > 0:
                cache_info = f" ({cache_read_tokens} cached)"
            elif cache_creation_tokens > 0:
                cache_info = f" [CACHE WRITE: {cache_creation_tokens}]"
            
            logger.info(f"🔢 Token usage - LLM Fallback: {input_tokens} in{cache_info}, {output_tokens} out, {input_tokens + output_tokens} total")

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = "\n".join(raw_text.split("\n")[1:-1])

        mapping = json.loads(raw_text)
        mapping["source"] = "llm_fallback_bedrock"
        mapping["token_usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
            "total_tokens": input_tokens + output_tokens
        }
        logger.info(f"LLM mapping (Bedrock): {instance_type or service_type} → {mapping.get('suggested_instance_type')} (confidence: {mapping.get('confidence')})")
        return mapping

    except json.JSONDecodeError as e:
        logger.error(f"LLM returned non-JSON: {e}")
        return {"error": "LLM returned invalid JSON", "source": "llm_fallback_bedrock"}
    except Exception as e:
        logger.error(f"LLM mapping error (Bedrock): {e}")
        return {"error": str(e), "source": "llm_fallback_bedrock"}


# ─────────────────────────────────────────────────────────────────────────────
# STRANDS TOOL WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

def llm_fallback_tool(
    service_type: str,
    current_provider: str,
    instance_type: str = None,
    vcpus: int = None,
    memory_gib: float = None,
    region: str = None,
    operating_system: str = "Linux",
    extra_context: str = None,
) -> dict:
    """
    Use LLM (Claude via AWS Bedrock) to map a GCP/Azure service to AWS equivalent.
    Called when SQL matching returns no results.

    Args:
        service_type: Type of service (ec2, rds, s3, vpc, lambda)
        current_provider: Source cloud provider (GCP, Azure)
        instance_type: Source instance type name (e.g. n2-standard-4)
        vcpus: Number of vCPUs (if known)
        memory_gib: Memory in GiB (if known)
        region: Source region name
        operating_system: OS (Linux/Windows)
        extra_context: Any additional context about the service

    Returns:
        dict with suggested AWS parameters for re-querying SQL
    """
    result = llm_map_service(
        service_type=service_type,
        current_provider=current_provider,
        instance_type=instance_type,
        vcpus=vcpus,
        memory_gib=memory_gib,
        region=region,
        operating_system=operating_system,
        extra_context=extra_context,
    )
    return result