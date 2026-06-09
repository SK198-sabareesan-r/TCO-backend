"""
agents/sql_generator_agent.py
------------------------------
SQL Generator Agent - Uses LLM (Bedrock) to generate SQL queries based on KPI mappings and schema.

This agent is responsible for:
1. Reading KPI mappings (defined by user in kpi_mappings.json)
2. Reading schema definitions (defined in data/schema.py)
3. Using LLM to generate SQL queries based on service parameters
4. Executing queries against PostgreSQL RDS
5. Returning matched AWS instances
6. Falling back to LLM normalization if no matches found

The LLM generates SQL queries that:
- Use ONLY fields defined in KPI mapping_fields
- Follow schema structure from data/schema.py
- Apply appropriate filters and tolerances
- Return best matching AWS instances
"""

import logging
import json
import os
import boto3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from dotenv import load_dotenv

from config.secrets import get_secret, get_aws_session
from utils.db import execute_query
from utils.kpi_loader import (
    get_instance_mapping,
    get_query_parameters,
    normalize_region_from_kpi,
    get_tolerance_for_service,
    get_max_results,
    should_prefer_current_generation
)
from data.schema import (
    get_schema,
    get_table_name,
    get_columns,
    get_matching_fields,
    get_select_fields
)
from tools.llm_mapper import llm_fallback_tool
from utils.token_tracker import track_tokens

load_dotenv()
logger = logging.getLogger(__name__)

# Bedrock client for LLM-based SQL generation
_bedrock_client = None

# Regional availability validation
MUMBAI_AVAILABLE_EC2_FAMILIES = {'t3', 't3a', 'm5', 'm5a', 'm6i', 'c5', 'c6i', 'r5', 'r6i'}
MUMBAI_AVAILABLE_RDS_FAMILIES = {'db.t3', 'db.t4g', 'db.m5', 'db.m6i', 'db.r5', 'db.r6i'}
MUMBAI_AVOID_SUFFIXES = {'gd', 'gn', 'dn'}  # Avoid instances with these suffixes in Mumbai


def validate_instance_for_region(instance_type: str, region: str, service_type: str) -> tuple[bool, str]:
    """
    Validate if an instance type is likely to have pricing in the given region.
    
    Args:
        instance_type: AWS instance type (e.g., "t3.large", "db.c6gd.medium")
        region: AWS region (e.g., "ap-south-1", "Asia Pacific (Mumbai)")
        service_type: Service type ("ec2", "rds")
    
    Returns:
        tuple: (is_valid, warning_message)
    """
    if not instance_type or not region:
        return True, ""
    
    # Check if Mumbai region
    is_mumbai = "mumbai" in region.lower() or "ap-south-1" in region.lower()
    
    if not is_mumbai:
        return True, ""  # Only validate Mumbai for now
    
    # Extract family from instance type
    # EC2: "t3.large" -> "t3"
    # RDS: "db.c6gd.medium" -> "db.c6gd"
    parts = instance_type.split('.')
    if len(parts) < 2:
        return True, ""
    
    if service_type == "rds":
        # RDS: db.family.size -> check db.family
        family = f"{parts[0]}.{parts[1]}"  # e.g., "db.c6gd"
        
        # Check if family is in available list
        if family not in MUMBAI_AVAILABLE_RDS_FAMILIES:
            # Check for avoid suffixes
            family_base = parts[1]  # e.g., "c6gd"
            if any(family_base.endswith(suffix) for suffix in MUMBAI_AVOID_SUFFIXES):
                return False, f"⚠️ RDS instance {instance_type} uses '{family_base}' family which has limited/no pricing in Mumbai. Recommend: db.t3, db.m5, db.m6i, db.r5, db.r6i"
            return False, f"⚠️ RDS instance {instance_type} may not be available in Mumbai. Recommend: {', '.join(sorted(MUMBAI_AVAILABLE_RDS_FAMILIES))}"
    
    elif service_type == "ec2":
        # EC2: family.size -> check family
        family = parts[0]  # e.g., "t3", "c6gd"
        
        # Check if family is in available list
        if family not in MUMBAI_AVAILABLE_EC2_FAMILIES:
            # Check for avoid suffixes
            if any(family.endswith(suffix) for suffix in MUMBAI_AVOID_SUFFIXES):
                return False, f"⚠️ EC2 instance {instance_type} uses '{family}' family which has limited/no pricing in Mumbai. Recommend: t3, m5, m6i, c5, c6i, r5, r6i"
            return False, f"⚠️ EC2 instance {instance_type} may not be available in Mumbai. Recommend: {', '.join(sorted(MUMBAI_AVAILABLE_EC2_FAMILIES))}"
    
    return True, ""


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


def _load_kpi_mapping_fields() -> Dict[str, Set[str]]:
    """
    Load the mapping_fields from KPI JSON to know which fields are allowed for each service.
    Returns a dict mapping service_type to set of allowed field names.
    """
    kpi_path = Path(__file__).parent.parent / "data" / "kpi_mappings.json"
    with open(kpi_path, 'r') as f:
        kpi_data = json.load(f)
    
    mapping_fields = {}
    for service_type, config in kpi_data.get("mapping_fields", {}).items():
        required = config.get("required_fields", [])
        mapping_fields[service_type] = set(required)
    
    return mapping_fields


# Load KPI mapping fields at module level
KPI_ALLOWED_FIELDS = _load_kpi_mapping_fields()


class SQLGeneratorAgent:
    """
    Agent responsible for generating and executing SQL queries using LLM (Bedrock).
    
    Uses LLM to generate SQL queries based on:
    - KPI mappings (user-defined service/region/instance mappings)
    - Database schema (table structure and columns)
    - Service parameters (vcpus, memory, region, etc.)
    """
    
    def __init__(self):
        """Initialize the SQL Generator Agent."""
        self.name = "SQL Generator Agent (LLM-Powered)"
        logger.info(f"{self.name} initialized")
    
    def generate_sql_with_llm(
        self,
        service_type: str,
        provider: str,
        instance_type: Optional[str] = None,
        vcpus: Optional[int] = None,
        memory_gib: Optional[float] = None,
        region: Optional[str] = None,
        tenancy: Optional[str] = None,
        operating_system: Optional[str] = None,
        database_engine: Optional[str] = None
    ) -> Tuple[str, List[Any], Dict[str, Any]]:
        """
        Use LLM (Bedrock) to generate SQL query based on KPI mappings and schema.
        
        Args:
            service_type: Type of service (ec2, rds, s3, vpc, lambda)
            provider: Source cloud provider (gcp, azure, aws)
            instance_type: Source instance type
            vcpus: Number of vCPUs
            memory_gib: Memory in GiB
            region: Source region
            tenancy: Tenancy (Shared/Dedicated)
            operating_system: OS (Linux/Windows)
            database_engine: Database engine for RDS
        
        Returns:
            tuple: (sql_query, params_list, metadata)
        """
        logger.info(f"Using LLM to generate SQL for {service_type} ({provider})")
        
        # Get schema information
        schema = get_schema(service_type)
        if not schema:
            logger.error(f"No schema found for service type: {service_type}")
            raise ValueError(f"No schema defined for service type: {service_type}")
        
        table_name = schema["table_name"]
        matching_fields = schema["matching_fields"]
        select_fields = schema["select_fields"]
        all_columns = schema["columns"]
        
        # Get KPI parameters
        query_params = get_query_parameters(service_type)
        vcpu_tolerance, mem_tolerance = get_tolerance_for_service(service_type)
        max_results = get_max_results(service_type)
        
        # Get KPI allowed fields for this service
        allowed_fields = KPI_ALLOWED_FIELDS.get(service_type, set())
        
        # Check for direct instance mapping in KPI
        kpi_instance_mapping = None
        if instance_type and provider.lower() != "aws":
            kpi_instance_mapping = get_instance_mapping(service_type, provider, instance_type)
            if kpi_instance_mapping:
                logger.info(f"✅ Found KPI instance mapping: {instance_type} → {kpi_instance_mapping.get('aws_instance_type')}")
                # Override specs with KPI values
                vcpus = kpi_instance_mapping.get("vcpus", vcpus)
                memory_gib = kpi_instance_mapping.get("memory_gib", memory_gib)
        
        # Normalize region using KPI
        aws_region = normalize_region_from_kpi(provider, region) if region else None
        
        # For S3, map Azure/GCP storage type to AWS storage class
        aws_storage_class = None
        if service_type == "s3" and instance_type and provider.lower() != "aws":
            from utils.kpi_loader import get_storage_class_mapping
            aws_storage_class = get_storage_class_mapping(service_type, provider, instance_type)
            if aws_storage_class:
                logger.info(f"✅ Mapped {provider} storage '{instance_type}' → AWS storage class '{aws_storage_class}'")
        
        # Load KPI mappings for context
        kpi_path = Path(__file__).parent.parent / "data" / "kpi_mappings.json"
        with open(kpi_path, 'r') as f:
            kpi_data = json.load(f)
        
        # Get relevant KPI sections
        service_name_mappings = kpi_data.get("service_name_mappings", {}).get(service_type, {})
        mapping_fields_config = kpi_data.get("mapping_fields", {}).get(service_type, {})
        
        # Build comprehensive LLM prompt with KPI and schema context
        system_prompt = f"""You are an expert SQL query generator for AWS pricing databases.

Your task is to generate a PostgreSQL query to find matching AWS instances based on the given parameters, KPI mappings, and database schema.

=== DATABASE SCHEMA ===
Table Name: {table_name}
Total Columns: {len(all_columns)}
Key Columns for Matching: {', '.join(matching_fields)}
Columns to Return: {', '.join(select_fields)}

Column Details:
- vcpu: Stored as TEXT, must CAST to INTEGER for comparison (EC2, RDS only)
- memory: Stored as TEXT like "8 GiB", "16 GiB", use LIKE pattern matching (EC2, RDS only)
- regioncode: AWS region code (e.g., "us-east-1", "ap-south-1") (ALL services)
- operatingsystem: Values like "Linux", "Windows", "RHEL", "SUSE" (EC2 only)
- tenancy: Values like "Shared", "Dedicated", "Host" (EC2 only)
- currentgeneration: "Yes" or "No" (prefer "Yes") (EC2, RDS only)
- instancetype: AWS instance type (e.g., "t3.large", "db.t3.large") (EC2, RDS only - NOT S3/Lambda/VPC)
- storageclass: S3 storage class (e.g., "General Purpose") (S3 only)
- **CRITICAL**: instancetype column exists ONLY for EC2 and RDS
- **CRITICAL**: For EC2/RDS: Always filter WHERE "instancetype" IS NOT NULL AND "instancetype" != ''
- **CRITICAL**: For S3/Lambda/VPC: DO NOT use instancetype filter (column doesn't exist)

=== KPI CONFIGURATION ===
Service Type: {service_type}
Allowed Fields for WHERE Clause: {', '.join(allowed_fields) if allowed_fields else 'All fields allowed'}

**CRITICAL - ONLY USE KPI ALLOWED FIELDS**:
The KPI configuration defines which fields you can use in the WHERE clause.
You MUST ONLY use fields from the "Allowed Fields" list above.
DO NOT use any other fields like tenancy, currentgeneration, instancefamily, etc. unless they are in the allowed list.

Mapping Fields Configuration:
{json.dumps(mapping_fields_config, indent=2)}

Service Name Mappings:
{json.dumps(service_name_mappings, indent=2)}

=== QUERY PARAMETERS ===
Tolerances:
- vCPU Tolerance: ±{vcpu_tolerance*100}%
- Memory Tolerance: ±{mem_tolerance*100}%

Max Results: {max_results}

Query Preferences:
- Prefer current generation instances (currentgeneration = 'Yes')
- Prefer widely available instance families (t3, m5, m6i, c5, c6i, r5, r6i)
- AVOID limited availability families (m8i, c7g, r7g, g5, p4, etc.)
- For RDS: Prefer General Purpose and Memory Optimized families
- For EC2: Prefer T3, M5, M6i families (widely available)
- Order by closest match (vCPU and memory)
- Use parameterized queries (%s placeholders)

=== REGIONAL AVAILABILITY NOTES ===
For Asia Pacific (Mumbai) / ap-south-1:
- EC2 AVAILABLE: t3, t3a, m5, m5a, m6i, c5, c6i, r5, r6i (widely available)
- EC2 LIMITED: m6a, c6a, r6a (may not be available)
- EC2 AVOID: m8i, c7g, r7g, g5, p4, inf1, c6gd, m6gd, r6gd (not available or limited)

For RDS in Mumbai:
- RDS AVAILABLE: db.t3, db.t4g, db.m5, db.m6i, db.r5, db.r6i
- RDS AVOID: db.c6gd, db.m6gd, db.r6gd, db.c7g, db.r7g (limited availability)

**CRITICAL FOR MUMBAI**: If region is ap-south-1 or "Asia Pacific (Mumbai)":
- EC2: ONLY use t3, t3a, m5, m5a, m6i, c5, c6i, r5, r6i families
- RDS: ONLY use db.t3, db.t4g, db.m5, db.m6i, db.r5, db.r6i families
- DO NOT use any "gd" suffix instances (c6gd, m6gd, r6gd) - they have NO pricing in Mumbai

=== RULES ===
1. **CRITICAL**: Use ONLY fields listed in "Allowed Fields" for WHERE clause - NO OTHER FIELDS
2. Always use parameterized queries (never hardcode values)
3. Cast text columns to appropriate types for comparison
4. Apply tolerance ranges for vCPU and memory
5. **DO NOT** use fields like tenancy, currentgeneration, instancefamily unless they are in KPI Allowed Fields
6. **CRITICAL**: Prefer widely available instance families (t3, m5, m6i, c5, c6i, r5, r6i) - but ONLY if instancefamily is in Allowed Fields
7. Order results by best match (closest vCPU and memory)
8. Limit results to {max_results}
9. **CRITICAL**: When using LIKE patterns with wildcards, escape % as %% in SQL string (e.g., 'db.t3.%%' not 'db.t3.%')
10. **CRITICAL**: OR put LIKE patterns in params array (e.g., WHERE instancetype LIKE %s with params=['db.t3.%'])
11. **CRITICAL**: For memory comparison in ORDER BY, use simple CAST: CAST(REPLACE("memory", ' GiB', '') AS FLOAT)
12. **CRITICAL**: DO NOT use EXTRACT(NUMERIC FROM ...) - this is invalid PostgreSQL syntax
13. **CRITICAL**: Keep ORDER BY simple - just compare vCPU and memory numerically
14. **CRITICAL**: For EC2/RDS: Always include WHERE "instancetype" IS NOT NULL AND "instancetype" != ''
15. **CRITICAL**: For S3/Lambda/VPC: DO NOT use instancetype filter (column doesn't exist)
16. **CRITICAL**: Always filter out "NA" values BEFORE casting: AND "memory" != 'NA' AND "memory" IS NOT NULL
17. **CRITICAL**: Same for vcpu: AND "vcpu" != 'NA' AND "vcpu" IS NOT NULL

=== OUTPUT FORMAT ===
Return ONLY valid JSON (no markdown, no explanations):
{{
  "sql": "SELECT ... FROM ... WHERE ... ORDER BY ... LIMIT ...",
  "params": [param1, param2, ...]
}}

**CRITICAL - JSON ONLY**:
- Do NOT add any text before or after the JSON
- Do NOT add explanations outside the JSON object
- Do NOT use markdown code fences (```json)
- Return ONLY the JSON object starting with {{ and ending with }}
- Keep response minimal - only sql and params fields

**CRITICAL - SELECT Clause**:
- ALWAYS use: "instancetype" AS instance_type (with alias)
- ALWAYS use: CAST("vcpu" AS INTEGER) AS vcpus (with alias and cast)
- ALWAYS use: "memory" AS memory_gib (with alias)
- The alias is REQUIRED for the application to read the results correctly

Example SQL structure for EC2 (using ONLY KPI allowed fields):
SELECT "instancetype" AS instance_type, CAST("vcpu" AS INTEGER) AS vcpus, "memory" AS memory_gib
FROM {table_name}
WHERE "instancetype" IS NOT NULL
  AND "instancetype" != ''
  AND "vcpu" != 'NA' AND "vcpu" IS NOT NULL
  AND "memory" != 'NA' AND "memory" IS NOT NULL
  AND CAST("vcpu" AS INTEGER) BETWEEN %s AND %s
  AND "memory" LIKE %s
  AND "regioncode" = %s
  AND "operatingsystem" = %s
ORDER BY ABS(CAST("vcpu" AS INTEGER) - %s) ASC,
         ABS(CAST(REPLACE("memory", ' GiB', '') AS FLOAT) - %s) ASC
LIMIT %s

Example SQL structure for RDS (using ONLY KPI allowed fields):
SELECT "instancetype" AS instance_type, CAST("vcpu" AS INTEGER) AS vcpus, "memory" AS memory_gib
FROM rds_pricing
WHERE "instancetype" IS NOT NULL 
  AND "instancetype" != ''
  AND "regioncode" = %s
  AND "databaseengine" = %s
ORDER BY CAST("vcpu" AS INTEGER) ASC
LIMIT %s

Example SQL structure for S3 (using ONLY KPI allowed fields):
SELECT sku, location, regioncode, storageclass, volumetype, availability, durability, usagetype
FROM s3_pricing
WHERE "regioncode" = %s
  AND "storageclass" = %s
ORDER BY sku ASC
LIMIT %s

**IMPORTANT - S3 does NOT have instancetype column**:
- Do NOT add "instancetype" IS NOT NULL filter for S3
- Do NOT select "instancetype" for S3
- S3 uses storageclass instead of instancetype

IMPORTANT: If you need to filter by instance family prefix (e.g., only t3 instances), use:
- Option 1: WHERE "instancefamily" = 'General purpose' (ONLY if instancefamily is in KPI Allowed Fields)
- Option 2: WHERE "instancetype" LIKE %s with params containing 't3.%%' (escape % as %%)
- DO NOT use: WHERE "instancetype" LIKE 't3.%' (this will cause parameter mismatch error)

CRITICAL - ORDER BY clause:
- For vCPU: ABS(CAST("vcpu" AS INTEGER) - %s)
- For memory: ABS(CAST(REPLACE("memory", ' GiB', '') AS FLOAT) - %s)
- DO NOT use EXTRACT(NUMERIC FROM ...) - this is invalid syntax
- DO NOT use REGEXP_REPLACE in ORDER BY - use simple REPLACE"""

        user_message = f"""Generate SQL query to find AWS {service_type} instances matching these specifications:

=== INPUT PARAMETERS ===
Service Type: {service_type}
Source Provider: {provider}
Source Instance Type: {instance_type or 'Not specified'}
AWS Storage Class (mapped): {aws_storage_class or 'Not specified' if service_type == 's3' else 'N/A'}
vCPUs: {vcpus or 'Not specified'}
Memory (GiB): {memory_gib or 'Not specified'}
Source Region: {region or 'Not specified'}
AWS Region (mapped): {aws_region or 'Not specified'}
Tenancy: {tenancy or 'Shared'}
Operating System: {operating_system or 'Linux'}
Database Engine: {database_engine or 'Not specified' if service_type == 'rds' else 'N/A'}

=== KPI INSTANCE MAPPING ===
{json.dumps(kpi_instance_mapping, indent=2) if kpi_instance_mapping else 'No direct KPI mapping found'}

=== CONTEXT ===
- If KPI instance mapping exists, use the mapped AWS specs (vcpus, memory_gib)
- Apply tolerance ranges: vCPU ±{vcpu_tolerance*100}%, Memory ±{mem_tolerance*100}%
- Normalize OS: Map Linux variants (Ubuntu, CentOS, etc.) to "Linux"
- Normalize OS: Map Windows variants to "Windows"
- For RDS: Filter by database engine if specified
- For S3: Filter by storage class using the mapped AWS Storage Class above
- For S3: Use "storageclass" column to filter (e.g., WHERE "storageclass" = 'General Purpose')
- Prefer current generation instances (currentgeneration = 'Yes')

=== REQUIRED OUTPUT ===
Generate a PostgreSQL query that:
1. Uses ONLY the allowed fields from KPI configuration
2. Applies appropriate filters based on input parameters
3. Uses parameterized queries (%s placeholders)
4. Orders by best match (closest vCPU and memory)
5. Limits to {max_results} resultsReturn the SQL query, parameters array, and explanation in JSON format."""

        try:
            client = _get_bedrock_client()
            
            # Prepare request for Bedrock (Claude 3 Sonnet)
            # Note: Prompt caching not supported in Claude 3 Sonnet
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "system": system_prompt,  # Simple string format for Claude 3
                "messages": [
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            }
            
            # Call Bedrock
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
                    operation="sql_generation",
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
                
                logger.info(f"🔢 Token usage - SQL Generation: {input_tokens} in{cache_info}, {output_tokens} out, {input_tokens + output_tokens} total")
            
            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = "\n".join(raw_text.split("\n")[1:-1])
            
            # Extract JSON from response (handle cases where LLM adds explanation before JSON)
            # Look for the first { and last }
            json_start = raw_text.find('{')
            json_end = raw_text.rfind('}')
            
            if json_start != -1 and json_end != -1:
                json_text = raw_text[json_start:json_end+1]
            else:
                json_text = raw_text
            
            # Parse JSON response
            llm_result = json.loads(json_text)
            
            sql = llm_result.get("sql", "")
            params = llm_result.get("params", [])
            
            # Post-process SQL to fix common issues
            # Fix 1: Escape % in LIKE patterns that are hardcoded in SQL
            # Replace patterns like "LIKE 'db.t3.%'" with "LIKE 'db.t3.%%'"
            # Also handle patterns like "LIKE '%8 GiB%'" -> "LIKE '%%8 GiB%%'"
            import re
            # Replace all % inside single quotes after LIKE with %%
            def escape_like_pattern(match):
                pattern = match.group(1)
                # Replace all % with %%
                escaped = pattern.replace('%', '%%')
                return f"LIKE '{escaped}'"
            
            sql = re.sub(r"LIKE\s+'([^']*)'", escape_like_pattern, sql)
            
            # Fix 2: Replace invalid EXTRACT(NUMERIC FROM ...) with CAST(REPLACE(...) AS FLOAT)
            # Pattern: EXTRACT(NUMERIC FROM REGEXP_REPLACE("memory", '[^0-9.]', '', 'g'))
            # Replace with: CAST(REPLACE("memory", ' GiB', '') AS FLOAT)
            sql = re.sub(
                r'EXTRACT\s*\(\s*NUMERIC\s+FROM\s+REGEXP_REPLACE\s*\(\s*"memory"\s*,\s*\'[^\']+\'\s*,\s*\'\'\s*,?\s*\'?g?\'?\s*\)\s*\)',
                'CAST(REPLACE("memory", \' GiB\', \'\') AS FLOAT)',
                sql,
                flags=re.IGNORECASE
            )
            
            # Fix 3: Also handle simpler EXTRACT(NUMERIC FROM "memory") patterns
            sql = re.sub(
                r'EXTRACT\s*\(\s*NUMERIC\s+FROM\s+"memory"\s*\)',
                'CAST(REPLACE("memory", \' GiB\', \'\') AS FLOAT)',
                sql,
                flags=re.IGNORECASE
            )
            
            # Fix 4: Ensure instancetype IS NOT NULL filter is present
            # Note: Only add for services that have instancetype column (EC2, RDS)
            # S3, Lambda, VPC don't have instancetype column
            services_with_instancetype = ['ec2', 'rds']
            
            if service_type in services_with_instancetype:
                # Check if the filter already exists
                if '"instancetype" IS NOT NULL' not in sql and 'instancetype IS NOT NULL' not in sql:
                    # Add it after the WHERE clause
                    # Find WHERE and add the filter as the first condition
                    if 'WHERE' in sql:
                        sql = sql.replace('WHERE', 'WHERE "instancetype" IS NOT NULL AND "instancetype" != \'\' AND', 1)
                        logger.info("✅ Added instancetype IS NOT NULL filter to SQL")
            
            # Fix 5: Ensure SELECT clause has correct alias for instancetype
            # Only for services that have instancetype column
            if service_type in services_with_instancetype:
                # Check if we're selecting instancetype without alias
                if '"instancetype"' in sql and 'AS instance_type' not in sql and 'as instance_type' not in sql:
                    # Replace "instancetype" with "instancetype" AS instance_type in SELECT clause only
                    # Find the SELECT clause (from SELECT to FROM)
                    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
                    if select_match:
                        select_clause = select_match.group(1)
                        # Replace "instancetype" with "instancetype" AS instance_type
                        new_select = select_clause.replace('"instancetype"', '"instancetype" AS instance_type')
                        sql = sql.replace(select_clause, new_select, 1)
                        logger.info("✅ Added instance_type alias to SELECT clause")
            
            logger.info(f"✅ LLM generated SQL query")
            logger.debug(f"SQL (after fixes): {sql}")
            logger.debug(f"Params: {params}")
            
            metadata = {
                "method": "LLM_SQL_GENERATION",
                "token_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens
                },
                "schema_used": {
                    "table_name": table_name,
                    "matching_fields": matching_fields,
                    "select_fields": select_fields,
                    "total_columns": len(all_columns)
                },
                "kpi_used": {
                    "allowed_fields": list(allowed_fields),
                    "instance_mapping": kpi_instance_mapping,
                    "vcpu_tolerance": vcpu_tolerance,
                    "memory_tolerance": mem_tolerance,
                    "max_results": max_results
                },
                "region_mapping": {
                    "source_region": region,
                    "aws_region": aws_region
                }
            }
            
            return sql, params, metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"LLM returned non-JSON: {e}")
            logger.error(f"Raw response: {raw_text}")
            # Fallback to manual SQL generation
            return self._fallback_manual_sql(
                service_type, provider, instance_type, vcpus, memory_gib,
                region, tenancy, operating_system, database_engine
            )
        except Exception as e:
            logger.error(f"LLM SQL generation error: {e}", exc_info=True)
            # Fallback to manual SQL generation
            return self._fallback_manual_sql(
                service_type, provider, instance_type, vcpus, memory_gib,
                region, tenancy, operating_system, database_engine
            )
    
    def _fallback_manual_sql(
        self,
        service_type: str,
        provider: str,
        instance_type: Optional[str],
        vcpus: Optional[int],
        memory_gib: Optional[float],
        region: Optional[str],
        tenancy: Optional[str],
        operating_system: Optional[str],
        database_engine: Optional[str]
    ) -> Tuple[str, List[Any], Dict[str, Any]]:
        """
        Fallback to manual SQL generation if LLM fails.
        This is the original logic from the previous implementation.
        """
        logger.warning("Falling back to manual SQL generation")
        
        # Get schema
        schema = get_schema(service_type)
        table_name = schema["table_name"]
        select_fields = schema["select_fields"]
        
        # Get tolerances
        vcpu_tolerance, mem_tolerance = get_tolerance_for_service(service_type)
        max_results = get_max_results(service_type)
        
        # Build WHERE conditions
        # Note: Only add instancetype filter for services that have this column (EC2, RDS)
        # S3, Lambda, VPC don't have instancetype column
        services_with_instancetype = ['ec2', 'rds']
        
        if service_type in services_with_instancetype:
            conditions = ['"instancetype" IS NOT NULL', '"instancetype" != \'\'']
        else:
            conditions = []
        
        params = []
        
        if vcpus is not None:
            vcpu_min = max(1, int(vcpus * (1 - vcpu_tolerance)))
            vcpu_max = int(vcpus * (1 + vcpu_tolerance))
            conditions.append('CAST("vcpu" AS INTEGER) BETWEEN %s AND %s')
            params.extend([vcpu_min, vcpu_max])
        
        if memory_gib is not None:
            conditions.append('"memory" LIKE %s')
            params.append(f'%{int(memory_gib)} GiB%')
        
        if region:
            aws_region = normalize_region_from_kpi(provider, region)
            conditions.append('"regioncode" = %s')
            params.append(aws_region)
        
        # Only add operating_system filter for EC2 (RDS doesn't have this column)
        if operating_system and service_type == "ec2":
            normalized_os = operating_system
            os_lower = operating_system.lower()
            if "windows" in os_lower:
                normalized_os = "Windows"
            elif "rhel" in os_lower or "red hat" in os_lower:
                normalized_os = "RHEL"
            elif "suse" in os_lower:
                normalized_os = "SUSE"
            else:
                normalized_os = "Linux"
            conditions.append('LOWER("operatingsystem") = LOWER(%s)')
            params.append(normalized_os)
        
        # Add database_engine filter for RDS
        if database_engine and service_type == "rds":
            conditions.append('"databaseengine" = %s')
            params.append(database_engine)
        
        # Note: We do NOT add instancefamily or currentgeneration filters here
        # because they are not in the KPI required_fields
        # We only use fields defined in KPI mappings.json
        
        where_clause = " AND ".join(conditions)
        
        # Build SELECT clause
        select_aliases = []
        for field in select_fields:
            if field == "instancetype":
                select_aliases.append('"instancetype" AS instance_type')
            elif field == "vcpu":
                select_aliases.append('CAST("vcpu" AS INTEGER) AS vcpus')
            elif field == "memory":
                select_aliases.append('"memory" AS memory_gib')
            else:
                select_aliases.append(f'"{field}"')
        
        select_clause = ", ".join(select_aliases)
        
        # Build SQL
        if service_type in ["ec2", "rds"]:
            sql = f"""
            SELECT {select_clause}
            FROM {table_name}
            WHERE {where_clause}
                AND "vcpu" IS NOT NULL 
                AND "vcpu" != 'NA' 
                AND "vcpu" != ''
                AND "memory" IS NOT NULL 
                AND "memory" != 'NA' 
                AND "memory" != ''
            ORDER BY
                ABS(CAST("vcpu" AS INTEGER) - %s) ASC,
                ABS(CAST(REPLACE("memory", ' GiB', '') AS FLOAT) - %s) ASC
            LIMIT %s
            """
            params.append(int(vcpus or 0))
            params.append(float(memory_gib or 0))
            params.append(max_results)
        else:
            sql = f"""
            SELECT {select_clause}
            FROM {table_name}
            WHERE {where_clause}
            LIMIT %s
            """
            params.append(max_results)
        
        metadata = {
            "method": "MANUAL_SQL_FALLBACK",
            "explanation": "LLM SQL generation failed, using manual fallback"
        }
        
        return sql, params, metadata
    def execute_query(
        self,
        service_type: str,
        provider: str,
        instance_type: Optional[str] = None,
        vcpus: Optional[int] = None,
        memory_gib: Optional[float] = None,
        region: Optional[str] = None,
        tenancy: Optional[str] = None,
        operating_system: Optional[str] = None,
        database_engine: Optional[str] = None,
        use_llm_fallback: bool = True  # DEFAULT: Smart fallback enabled
    ) -> Dict[str, Any]:
        """
        Generate SQL using LLM and execute query, return results.
        If no results and use_llm_fallback=True:
        - LLM normalizes unusual specs to next higher standard AWS specs
        - Retry SQL with corrected specs
        - Return SQL results if found
        
        Args:
            use_llm_fallback: If True, uses LLM to fix query and retry SQL when no match found (DEFAULT: True)
        
        Returns:
            dict with:
                - matches: list of matching AWS instances
                - match_count: number of matches
                - sql_used: SQL query string
                - metadata: Generation method and token usage
                - method: execution method (LLM_SQL, LLM_FALLBACK, FAILED)
        """
        logger.info(f"Executing SQL query for {service_type} ({provider})")
        
        # Log input parameters for debugging
        logger.info(f"📊 Input params: instance_type={instance_type}, vcpus={vcpus}, memory_gib={memory_gib}, region={region}, os={operating_system}")
        
        # Generate SQL using LLM
        sql, params, metadata = self.generate_sql_with_llm(
            service_type=service_type,
            provider=provider,
            instance_type=instance_type,
            vcpus=vcpus,
            memory_gib=memory_gib,
            region=region,
            tenancy=tenancy,
            operating_system=operating_system,
            database_engine=database_engine
        )
        
        logger.info(f"🔍 Generated SQL with {len(params)} parameters")
        logger.debug(f"SQL: {sql}")
        logger.debug(f"Params: {params}")

        # CRITICAL FIX: Add NA filter to prevent CAST errors
        if '"vcpu"' in sql and 'vcpu" != \'NA\'' not in sql:
            # Add NA filters right after the WHERE clause
            if 'WHERE "instancetype" IS NOT NULL' in sql:
                sql = sql.replace(
                    'WHERE "instancetype" IS NOT NULL',
                    'WHERE "vcpu" != \'NA\' AND "vcpu" IS NOT NULL AND "memory" != \'NA\' AND "memory" IS NOT NULL AND "instancetype" IS NOT NULL'
                )
                logger.debug("✅ Added NA filters to SQL")
            elif 'WHERE "instancetype"' in sql:
                sql = sql.replace(
                    'WHERE "instancetype"',
                    'WHERE "vcpu" != \'NA\' AND "vcpu" IS NOT NULL AND "memory" != \'NA\' AND "memory" IS NOT NULL AND "instancetype"'
                )
                logger.debug("✅ Added NA filters to SQL")

        try:
            # Execute query
            rows = execute_query(sql, tuple(params))
            
            logger.info(f"📊 SQL executed: returned {len(rows)} rows")
            
            if rows:
                # Validate instances for regional availability
                validated_rows = []
                services_with_instancetype = ['ec2', 'rds']
                
                for row in rows:
                    instance_type = row.get("instance_type")
                    
                    # Debug: Log what we got (only for services that should have instance_type)
                    if not instance_type and service_type in services_with_instancetype:
                        logger.warning(f"⚠️ Row returned with empty instance_type. Row keys: {list(row.keys())}, Row values sample: {dict(list(row.items())[:5])}")
                    
                    # Only validate regional availability for services with instance_type
                    if service_type in services_with_instancetype:
                        is_valid, warning = validate_instance_for_region(instance_type, region, service_type)
                        if not is_valid:
                            logger.warning(warning)
                            # Add warning to row metadata
                            row["availability_warning"] = warning
                    
                    validated_rows.append(row)
                
                logger.info(f"✅ SQL query found {len(validated_rows)} matches")
                return {
                    "matches": validated_rows,
                    "match_count": len(validated_rows),
                    "sql_used": sql,
                    "metadata": metadata,
                    "specs_used": {
                        "service_type": service_type,
                        "provider": provider,
                        "instance_type": instance_type,
                        "vcpus": vcpus,
                        "memory_gib": memory_gib,
                        "region": region,
                        "tenancy": tenancy,
                        "operating_system": operating_system,
                        "database_engine": database_engine
                    },
                    "method": metadata.get("method", "LLM_SQL"),
                    "agent": self.name
                }
            
            # No matches - try LLM fallback if enabled
            if not use_llm_fallback:
                logger.warning(f"⚠️ SQL query returned no matches (LLM fallback disabled)")
                return {
                    "matches": [],
                    "match_count": 0,
                    "sql_used": sql,
                    "metadata": metadata,
                    "method": "LLM_SQL_NO_MATCH",
                    "agent": self.name
                }
            
            logger.info(f"⚠️ SQL returned 0 matches. Trying LLM fallback...")
            return self._llm_fallback(
                service_type=service_type,
                provider=provider,
                instance_type=instance_type,
                vcpus=vcpus,
                memory_gib=memory_gib,
                region=region,
                tenancy=tenancy,
                operating_system=operating_system,
                database_engine=database_engine,
                kpi_metadata=metadata
            )
        
        except Exception as e:
            logger.error(f"SQL execution error: {e}", exc_info=True)
            return {
                "matches": [],
                "match_count": 0,
                "sql_used": sql,
                "metadata": metadata,
                "error": str(e),
                "method": "FAILED",
                "agent": self.name
            }
    
    def _llm_fallback(
        self,
        service_type: str,
        provider: str,
        instance_type: Optional[str],
        vcpus: Optional[int],
        memory_gib: Optional[float],
        region: Optional[str],
        tenancy: Optional[str],
        operating_system: Optional[str],
        database_engine: Optional[str],
        kpi_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use LLM to normalize unusual specs to next higher standard AWS specs and retry SQL.
        
        SMART FALLBACK FLOW:
        1. LLM analyzes unusual specs (e.g., 7 GiB memory)
        2. LLM suggests next higher standard AWS specs (e.g., 8 GiB memory)
        3. Retry SQL with corrected specs
        4. Return SQL results (NEVER return synthetic LLM-only matches)
        
        This ensures:
        - Unusual specs (7 GiB, 14 GiB) are mapped to standard AWS specs (8 GiB, 16 GiB)
        - All matches come from SQL database (real AWS instances)
        - LLM only fixes the query parameters, doesn't generate matches
        """
        logger.info("🔄 LLM Fallback: Normalizing unusual specs to standard AWS specs...")
        
        # Call LLM to normalize specs to next higher standard AWS specs
        llm_result = llm_fallback_tool(
            service_type=service_type,
            current_provider=provider,
            instance_type=instance_type,
            vcpus=vcpus,
            memory_gib=memory_gib,
            region=region,
            operating_system=operating_system,
            extra_context="Map to NEXT HIGHER standard AWS specs. For unusual memory (7 GiB, 14 GiB, 28 GiB), round UP to standard AWS sizes (8 GiB, 16 GiB, 32 GiB)."
        )
        
        if "error" in llm_result:
            logger.error(f"❌ LLM fallback failed: {llm_result['error']}")
            return {
                "matches": [],
                "match_count": 0,
                "kpi_metadata": kpi_metadata,
                "llm_suggestion": llm_result,
                "method": "FAILED",
                "notes": f"SQL returned 0 matches. LLM normalization failed: {llm_result['error']}",
                "agent": self.name
            }
        
        # Extract LLM-corrected specs
        corrected_vcpus = llm_result.get("vcpus", vcpus)
        corrected_memory = llm_result.get("memory_gib", memory_gib)
        corrected_region = llm_result.get("aws_region", region)
        
        logger.info(
            f"✅ LLM normalized specs: "
            f"{vcpus}vCPU/{memory_gib}GiB → {corrected_vcpus}vCPU/{corrected_memory}GiB"
        )
        
        # Retry SQL with LLM-corrected specs
        logger.info(f"🔄 Retrying SQL with corrected specs...")
        
        sql, params, retry_metadata = self.generate_sql_with_llm(
            service_type=llm_result.get("service_type", service_type),
            provider="aws",  # LLM returns AWS specs
            instance_type=llm_result.get("suggested_instance_type"),
            vcpus=corrected_vcpus,
            memory_gib=corrected_memory,
            region=corrected_region,
            tenancy=llm_result.get("tenancy", tenancy),
            operating_system=llm_result.get("operating_system", operating_system),
            database_engine=database_engine
        )
        
        try:
            rows = execute_query(sql, tuple(params))
            
            if rows:
                logger.info(f"✅ LLM fallback successful: SQL found {len(rows)} matches with corrected specs")
                return {
                    "matches": rows,
                    "match_count": len(rows),
                    "sql_used": sql,
                    "kpi_metadata": retry_metadata,
                    "llm_suggestion": llm_result,
                    "method": "LLM_FALLBACK",
                    "notes": (
                        f"Original SQL returned 0 matches. "
                        f"LLM normalized {vcpus}vCPU/{memory_gib}GiB to {corrected_vcpus}vCPU/{corrected_memory}GiB. "
                        f"Retry SQL found {len(rows)} matches. "
                        f"Confidence: {llm_result.get('confidence', 'N/A')}"
                    ),
                    "agent": self.name
                }
            
            # Even LLM-corrected SQL returned 0 matches
            logger.warning(f"⚠️ LLM-corrected SQL still returned 0 matches")
            return {
                "matches": [],
                "match_count": 0,
                "sql_used": sql,
                "kpi_metadata": retry_metadata,
                "llm_suggestion": llm_result,
                "method": "FAILED",
                "notes": (
                    f"Original SQL returned 0 matches. "
                    f"LLM normalized {vcpus}vCPU/{memory_gib}GiB to {corrected_vcpus}vCPU/{corrected_memory}GiB. "
                    f"Retry SQL still returned 0 matches. "
                    f"No AWS instances found matching these specs in {corrected_region}."
                ),
                "agent": self.name
            }
        
        except Exception as e:
            logger.error(f"LLM retry SQL execution error: {e}", exc_info=True)
            return {
                "matches": [],
                "match_count": 0,
                "kpi_metadata": retry_metadata,
                "llm_suggestion": llm_result,
                "error": str(e),
                "method": "FAILED",
                "notes": f"SQL retry failed after LLM normalization: {str(e)}",
                "agent": self.name
            }


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

_sql_agent_instance = None


def get_sql_generator_agent() -> SQLGeneratorAgent:
    """Get or create the SQL Generator Agent singleton instance."""
    global _sql_agent_instance
    if _sql_agent_instance is None:
        _sql_agent_instance = SQLGeneratorAgent()
    return _sql_agent_instance


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def generate_and_execute_sql(
    service_type: str,
    provider: str,
    instance_type: Optional[str] = None,
    vcpus: Optional[int] = None,
    memory_gib: Optional[float] = None,
    region: Optional[str] = None,
    tenancy: Optional[str] = None,
    operating_system: Optional[str] = None,
    database_engine: Optional[str] = None,
    use_llm_fallback: bool = True  # DEFAULT: Smart fallback enabled (LLM fixes query and retries SQL)
) -> Dict[str, Any]:
    """
    Convenience function to generate and execute SQL query using the agent.
    
    This is the main entry point for SQL generation and execution.
    The agent will:
    1. Use KPI mappings (defined by user in kpi_mappings.json)
    2. Generate and execute SQL
    3. If no match and use_llm_fallback=True:
       - LLM normalizes unusual specs to next higher standard AWS specs
       - Retry SQL with corrected specs
       - Return SQL results if found
    
    Args:
        use_llm_fallback: If True, uses LLM to fix query and retry SQL when no KPI match found (DEFAULT: True)
    """
    agent = get_sql_generator_agent()
    return agent.execute_query(
        service_type=service_type,
        provider=provider,
        instance_type=instance_type,
        vcpus=vcpus,
        memory_gib=memory_gib,
        region=region,
        tenancy=tenancy,
        operating_system=operating_system,
        database_engine=database_engine,
        use_llm_fallback=use_llm_fallback
    )
