"""
data/schema.py
--------------
Database schemas for AWS pricing tables.

This file contains the table schemas for:
1. EC2 (Elastic Compute Cloud)
2. RDS (Relational Database Service)
3. S3 (Simple Storage Service)
4. Lambda (Serverless Functions)
5. VPC (Virtual Private Cloud)

Each schema includes:
- table_name: Name of the table in PostgreSQL
- columns: List of column names
- matching_fields: Fields used for matching/filtering
- select_fields: Fields to return in query results
"""

# ============================================================================
# EC2 PRICING SCHEMA
# ============================================================================

EC2_SCHEMA = {
    "table_name": "ec2_pricing",
    
    "columns": [
        "sku", "instancesku", "productfamily", "servicecode", "servicename",
        "resourcetype", "producttype", "location", "locationtype", "regioncode",
        "availabilityzone", "instancetype", "instancefamily", "currentgeneration",
        "capacitystatus", "tenancy", "marketoption", "vcpu", "physicalcores",
        "physicalprocessor", "clockspeed", "processorarchitecture", "processorfeatures",
        "ecu", "normalizationsizefactor", "memory", "storage", "storagemedia",
        "volumetype", "volumeapiname", "maxvolumesize", "maxiopsvolume",
        "maxiopsburstperformance", "maxthroughputvolume", "provisioned", "ebsoptimized",
        "networkperformance", "enhancednetworkingsupported", "dedicatedebsthroughput",
        "dedicatedebsthroughputdescription", "vpcnetworkingsupport", "classicnetworkingsupport",
        "operatingsystem", "licensemodel", "preinstalledsw", "intelavxavailable",
        "intelavx2available", "intelturboavailable", "gpu", "gpumemory",
        "elasticgraphicstype", "usagetype", "operation", "group", "groupdescription",
        "transfertype", "fromlocation", "fromlocationtype", "tolocation", "tolocationtype",
        "fromregioncode", "toregioncode", "snapshotarchivefeetype", "instancecapacity_medium",
        "instancecapacity_large", "instancecapacity_xlarge", "instancecapacity_2xlarge",
        "instancecapacity_4xlarge", "instancecapacity_8xlarge", "instancecapacity_9xlarge",
        "instancecapacity_10xlarge", "instancecapacity_12xlarge", "instancecapacity_16xlarge",
        "instancecapacity_18xlarge", "instancecapacity_24xlarge", "instancecapacity_32xlarge",
        "instancecapacity_metal", "instance"
    ],
    
    "matching_fields": [
        "vcpu", "memory", "regioncode", "tenancy", "operatingsystem", "currentgeneration"
    ],
    
    "select_fields": [
        "instancetype", "instancefamily", "vcpu", "memory", "location", "regioncode",
        "tenancy", "operatingsystem", "storage", "networkperformance", "physicalprocessor",
        "currentgeneration"
    ]
}




RDS_SCHEMA = {
    "table_name": "rds_pricing",
    
    "columns": [
        "sku", "productfamily", "servicecode", "servicename", "location",
        "locationtype", "regioncode", "instancetype", "instancetypefamily",
        "instancefamily", "currentgeneration", "normalizationsizefactor", "vcpu",
        "physicalprocessor", "clockspeed", "processorarchitecture", "processorfeatures",
        "enhancednetworkingsupported", "memory", "storage", "storagemedia",
        "volumetype", "volumename", "minvolumesize", "maxvolumesize",
        "dedicatedebsthroughput", "networkperformance", "enginecode",
        "databaseengine", "databaseedition", "enginemajorversion", "enginemediatype",
        "deploymentoption", "deploymentmodel", "licensemodel", "unbundledlicensing",
        "windowslicensemultiplier", "usagetype", "operation", "group",
        "groupdescription", "extendedsupportpricingyear", "limitlesspreview", "acu"
    ],
    
    "matching_fields": [
        "vcpu", "memory", "regioncode", "databaseengine", "deploymentoption", "currentgeneration"
    ],
    
    "select_fields": [
        "instancetype", "instancefamily", "vcpu", "memory", "location", "regioncode",
        "databaseengine", "databaseedition", "deploymentoption", "storage",
        "networkperformance", "currentgeneration"
    ]
}



S3_SCHEMA = {
    "table_name": "s3_pricing",
    
    "columns": [
        "sku", "productfamily", "servicecode", "servicename", "location",
        "locationtype", "regioncode", "transfertype", "fromlocation",
        "fromlocationtype", "tolocation", "tolocationtype", "fromregioncode",
        "toregioncode", "storageclass", "volumetype", "availability",
        "durability", "usagetype", "operation", "feecode", "feedescription",
        "group", "groupdescription", "overhead"
    ],
    
    "matching_fields": [
        "regioncode", "storageclass", "volumetype"
    ],
    
    "select_fields": [
        "sku", "location", "regioncode", "storageclass", "volumetype",
        "availability", "durability", "usagetype"
    ]
}




LAMBDA_SCHEMA = {
    "table_name": "lambda_pricing",
    
    "columns": [
        "sku", "productfamily", "servicecode", "servicename", "location",
        "locationtype", "regioncode", "usagetype", "operation", "group",
        "groupdescription", "lambdamanagedinstancetype", "lambdamanagedinstances_requesttype"
    ],
    
    "matching_fields": [
        "regioncode", "lambdamanagedinstancetype"
    ],
    
    "select_fields": [
        "sku", "location", "regioncode", "usagetype", "lambdamanagedinstancetype",
        "lambdamanagedinstances_requesttype", "productfamily"
    ]
}




VPC_SCHEMA = {
    "table_name": "vpc_pricing",
    
    "columns": [
        "sku", "productfamily", "servicecode", "servicename", "location",
        "locationtype", "regioncode", "endpointtype", "vpntype", "attachmenttype",
        "trafficdirection", "transfertype", "fromlocation", "fromlocationtype",
        "tolocation", "tolocationtype", "fromregioncode", "toregioncode",
        "usagetype", "operation", "group", "groupdescription"
    ],
    
    "matching_fields": [
        "regioncode", "endpointtype", "attachmenttype"
    ],
    
    "select_fields": [
        "sku", "location", "regioncode", "endpointtype", "vpntype",
        "attachmenttype", "trafficdirection", "usagetype"
    ]
}



SCHEMAS = {
    "ec2": EC2_SCHEMA,
    "rds": RDS_SCHEMA,
    "s3": S3_SCHEMA,
    "lambda": LAMBDA_SCHEMA,
    "vpc": VPC_SCHEMA
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_schema(service_type: str) -> dict:
    """Get schema for a specific service type."""
    return SCHEMAS.get(service_type.lower())


def get_table_name(service_type: str) -> str:
    """Get table name for a specific service type."""
    schema = get_schema(service_type)
    return schema["table_name"] if schema else None


def get_columns(service_type: str) -> list:
    """Get columns for a specific service type."""
    schema = get_schema(service_type)
    return schema["columns"] if schema else []


def get_matching_fields(service_type: str) -> list:
    """Get matching fields for a specific service type."""
    schema = get_schema(service_type)
    return schema["matching_fields"] if schema else []


def get_select_fields(service_type: str) -> list:
    """Get select fields for a specific service type."""
    schema = get_schema(service_type)
    return schema["select_fields"] if schema else []


def get_all_table_names() -> list:
    """Get all table names."""
    return [schema["table_name"] for schema in SCHEMAS.values()]
