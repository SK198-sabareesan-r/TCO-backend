"""
utils/kpi_loader.py
-------------------
KPI Loader utility for loading and accessing cloud migration KPI mappings.
Provides centralized access to region mappings, instance mappings, and query parameters.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Global KPI cache
_kpi_cache: Optional[Dict[str, Any]] = None
_kpi_file_path = Path(__file__).parent.parent / "data" / "kpi_mappings.json"


def load_kpi() -> Dict[str, Any]:
    """
    Load KPI mappings from JSON file.
    Uses caching to avoid repeated file reads.
    
    Returns:
        dict: Complete KPI mappings structure
    """
    global _kpi_cache
    
    if _kpi_cache is not None:
        return _kpi_cache
    
    try:
        with open(_kpi_file_path, 'r', encoding='utf-8') as f:
            _kpi_cache = json.load(f)
        logger.info(f"Loaded KPI mappings from {_kpi_file_path}")
        return _kpi_cache
    except FileNotFoundError:
        logger.error(f"KPI file not found: {_kpi_file_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in KPI file: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading KPI file: {e}")
        return {}


def reload_kpi() -> Dict[str, Any]:
    """Force reload KPI from file (clears cache)."""
    global _kpi_cache
    _kpi_cache = None
    return load_kpi()


def get_region_mapping(provider: str, source_region: str) -> Optional[Dict[str, str]]:
    """
    Get AWS region mapping for a given provider and source region.
    
    Args:
        provider: Source cloud provider (gcp, azure, aws)
        source_region: Source region code (e.g., us-central1, eastus)
    
    Returns:
        dict with aws_region, aws_region_code, latency_zone or None
    """
    kpi = load_kpi()
    region_mappings = kpi.get("region_mappings", [])
    
    # region_mappings is an array of objects with aws/gcp/azure region info
    provider_lower = provider.lower()
    source_region_lower = source_region.lower() if source_region else ""
    
    for mapping in region_mappings:
        if provider_lower == "aws":
            # Check AWS region code or name
            if (mapping.get("aws_region_code", "").lower() == source_region_lower or
                mapping.get("aws_region_name", "").lower() == source_region_lower):
                return {
                    "aws_region": mapping.get("aws_region_name"),
                    "aws_region_code": mapping.get("aws_region_code"),
                    "aws_location": mapping.get("aws_location")
                }
        elif provider_lower == "gcp":
            # Check GCP region
            if mapping.get("gcp_region", "").lower() == source_region_lower:
                return {
                    "aws_region": mapping.get("aws_region_name"),
                    "aws_region_code": mapping.get("aws_region_code"),
                    "aws_location": mapping.get("aws_location"),
                    "gcp_region": mapping.get("gcp_region"),
                    "gcp_location": mapping.get("gcp_location")
                }
        elif provider_lower == "azure":
            # Check Azure region or programmatic name
            if (mapping.get("azure_region", "").lower() == source_region_lower or
                mapping.get("azure_programmatic_name", "").lower() == source_region_lower):
                return {
                    "aws_region": mapping.get("aws_region_name"),
                    "aws_region_code": mapping.get("aws_region_code"),
                    "aws_location": mapping.get("aws_location"),
                    "azure_region": mapping.get("azure_region"),
                    "azure_programmatic_name": mapping.get("azure_programmatic_name")
                }
    
    return None


def get_instance_mapping(
    service_type: str,
    provider: str,
    instance_type: str
) -> Optional[Dict[str, Any]]:
    """
    Get AWS instance mapping for a given service type, provider, and instance type.
    
    Args:
        service_type: Service type (ec2, rds, s3, lambda, vpc)
        provider: Source cloud provider (gcp, azure)
        instance_type: Source instance type (e.g., n2-standard-4, Standard_D4s_v3)
    
    Returns:
        dict with aws_instance_type, vcpus, memory_gib, confidence or None
    """
    kpi = load_kpi()
    instance_maps = kpi.get("instance_mappings", {})
    
    # instance_mappings is structured as: { "ec2": [], "rds": [], ... }
    # Each array contains mapping objects
    service_mappings = instance_maps.get(service_type.lower(), [])
    
    # If it's a list (array), search through it
    if isinstance(service_mappings, list):
        for mapping in service_mappings:
            # Check if this mapping matches the provider and instance type
            provider_field = f"{provider.lower()}_instance_type"
            if mapping.get(provider_field) == instance_type:
                return mapping
        return None
    
    # Legacy format: nested dictionaries
    provider_maps = service_mappings.get(provider.lower(), {})
    return provider_maps.get(instance_type)


def get_query_parameters(service_type: str) -> Dict[str, Any]:
    """
    Get query parameters for a specific service type.
    
    Args:
        service_type: Service type (ec2, rds, s3, lambda, vpc)
    
    Returns:
        dict with query parameters (tolerance, max_results, defaults, etc.)
    """
    kpi = load_kpi()
    params = kpi.get("query_parameters", {}).get(service_type.lower(), {})
    
    # Provide defaults if not found
    if not params:
        return {
            "vcpu_tolerance_percent": 20,
            "memory_tolerance_percent": 20,
            "max_results": 3,  # Return only top 3 matches for faster processing
            "prefer_current_generation": True
        }
    
    return params


def get_cost_parameters() -> Dict[str, Any]:
    """
    Get cost calculation parameters including savings plans and spot discounts.
    
    Returns:
        dict with cost calculation parameters
    """
    kpi = load_kpi()
    return kpi.get("cost_calculation_parameters", {})


def normalize_region_from_kpi(provider: str, source_region: str) -> str:
    """
    Normalize a region using KPI mappings.
    Falls back to default if not found.
    
    Args:
        provider: Source cloud provider (gcp, azure, aws)
        source_region: Source region code
    
    Returns:
        AWS region code (e.g., "us-east-1")
    """
    if not source_region:
        return "us-east-1"
    
    mapping = get_region_mapping(provider, source_region)
    if mapping:
        return mapping.get("aws_region_code", "us-east-1")
    
    # Fallback: if it looks like an AWS region code, return as-is
    if source_region and "-" in source_region and not "(" in source_region:
        return source_region.lower()
    
    logger.warning(f"No KPI mapping for {provider} region '{source_region}', using default us-east-1")
    return "us-east-1"
    return "US East (N. Virginia)"


def get_all_instance_mappings(service_type: str) -> Dict[str, Dict[str, Any]]:
    """
    Get all instance mappings for a service type across all providers.
    
    Args:
        service_type: Service type (ec2, rds, s3, lambda, vpc)
    
    Returns:
        dict with provider -> instance mappings
    """
    kpi = load_kpi()
    return kpi.get("instance_mappings", {}).get(service_type.lower(), {})


def get_kpi_version() -> str:
    """Get KPI version string."""
    kpi = load_kpi()
    return kpi.get("version", "unknown")


def get_kpi_description() -> str:
    """Get KPI description."""
    kpi = load_kpi()
    return kpi.get("description", "")


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE NAME NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def normalize_service_name(service_name: str, provider: str = None) -> Optional[str]:
    """
    Normalize a service name to AWS service type.
    
    Args:
        service_name: Service name (e.g., "Compute Engine", "Virtual Machines", "EC2")
        provider: Cloud provider (gcp, azure, aws) - optional, helps with disambiguation
    
    Returns:
        Normalized AWS service type (ec2, s3, rds, vpc, lambda) or None
    
    Examples:
        normalize_service_name("Compute Engine", "gcp") -> "ec2"
        normalize_service_name("Blob Storage", "azure") -> "s3"
        normalize_service_name("Cloud SQL", "gcp") -> "rds"
    """
    if not service_name:
        return None
    
    kpi = load_kpi()
    service_mappings = kpi.get("service_name_mappings", {})
    
    # Normalize input
    service_name_lower = service_name.strip().lower()
    provider_lower = provider.lower() if provider else None
    
    # Search through all service types
    for service_type, mappings in service_mappings.items():
        # If provider specified, check that provider's names first
        if provider_lower:
            provider_key = f"{provider_lower}_names"
            if provider_key in mappings:
                for name in mappings[provider_key]:
                    if name.lower() == service_name_lower:
                        logger.debug(f"Normalized '{service_name}' ({provider}) → {service_type}")
                        return service_type
        
        # Check all providers' names
        for provider_key in ["aws_names", "gcp_names", "azure_names"]:
            if provider_key in mappings:
                for name in mappings[provider_key]:
                    if name.lower() == service_name_lower:
                        logger.debug(f"Normalized '{service_name}' → {service_type}")
                        return service_type
    
    logger.warning(f"Could not normalize service name: '{service_name}' (provider: {provider})")
    return None


def get_service_names_for_provider(service_type: str, provider: str) -> list[str]:
    """
    Get all service names for a specific service type and provider.
    
    Args:
        service_type: AWS service type (ec2, s3, rds, vpc, lambda)
        provider: Cloud provider (gcp, azure, aws)
    
    Returns:
        List of service names for that provider
    
    Example:
        get_service_names_for_provider("ec2", "gcp") -> ["Compute Engine", "GCE", ...]
    """
    kpi = load_kpi()
    service_mappings = kpi.get("service_name_mappings", {})
    
    if service_type not in service_mappings:
        return []
    
    provider_key = f"{provider.lower()}_names"
    return service_mappings[service_type].get(provider_key, [])


def get_all_service_mappings() -> Dict[str, Dict[str, list]]:
    """
    Get all service name mappings.
    
    Returns:
        dict with service_type -> provider -> list of names
    """
    kpi = load_kpi()
    return kpi.get("service_name_mappings", {})


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS FOR SQL GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def get_tolerance_for_service(service_type: str) -> tuple[float, float]:
    """
    Get vcpu and memory tolerance percentages for a service type.
    
    Returns:
        tuple: (vcpu_tolerance, memory_tolerance) as decimals (e.g., 0.20 for 20%)
    """
    params = get_query_parameters(service_type)
    vcpu_tol = params.get("vcpu_tolerance_percent", 20) / 100.0
    mem_tol = params.get("memory_tolerance_percent", 20) / 100.0
    return vcpu_tol, mem_tol


def should_prefer_current_generation(service_type: str) -> bool:
    """Check if current generation instances should be preferred."""
    params = get_query_parameters(service_type)
    return params.get("prefer_current_generation", True)


def get_max_results(service_type: str) -> int:
    """Get maximum number of results to return for a service type."""
    params = get_query_parameters(service_type)
    return params.get("max_results", 10)


def get_storage_class_mapping(service_type: str, provider: str, storage_sku: str) -> Optional[str]:
    """
    Map cloud provider storage SKU/class to AWS S3 storage class.
    
    Args:
        service_type: Service type (s3)
        provider: Source cloud provider (azure, gcp)
        storage_sku: Source storage SKU (e.g., standard_lrs, premium_lrs)
    
    Returns:
        AWS S3 storage class (e.g., "Standard", "Standard-IA", "Glacier")
    
    Examples:
        get_storage_class_mapping("s3", "azure", "standard_lrs") -> "Standard"
        get_storage_class_mapping("s3", "gcp", "nearline") -> "Standard-IA"
    """
    if not storage_sku:
        return None
    
    kpi = load_kpi()
    storage_mappings = kpi.get("storage_class_mappings", {})
    
    if service_type not in storage_mappings:
        return None
    
    provider_key = f"{provider.lower()}_to_aws"
    provider_mappings = storage_mappings[service_type].get(provider_key, {})
    
    # Normalize storage SKU (lowercase, strip)
    storage_sku_lower = storage_sku.strip().lower()
    
    # Try exact match first
    if storage_sku_lower in provider_mappings:
        return provider_mappings[storage_sku_lower]
    
    # Try without underscores/hyphens
    storage_sku_normalized = storage_sku_lower.replace("_", "").replace("-", "")
    for key, value in provider_mappings.items():
        key_normalized = key.replace("_", "").replace("-", "")
        if storage_sku_normalized == key_normalized:
            return value
    
    logger.warning(f"No storage class mapping for {provider} SKU '{storage_sku}', defaulting to General Purpose")
    return "General Purpose"
