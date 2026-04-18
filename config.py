import os
import boto3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
AWS_PROFILE = os.getenv("AWS_PROFILE")
ORG_ROOT_OU_ID = os.getenv("ORG_ROOT_OU_ID")
CONFIG_RESOURCE_TYPES = os.getenv("CONFIG_RESOURCE_TYPES", "AWS::EC2::Instance")
CONFIG_REGIONS = os.getenv("CONFIG_REGIONS", "us-west-2")

# Prefix for all ServiceNow resource names
SERVICENOW_PREFIX = os.getenv("SERVICENOW_PREFIX", "ServiceNow")

# Derived resource names
AGGREGATOR_ROLE_NAME = f"{SERVICENOW_PREFIX}AggregatorRole"
AGGREGATOR_NAME = f"{SERVICENOW_PREFIX}Aggregator"
MEMBER_ACCOUNT_ROLE_NAME = f"{SERVICENOW_PREFIX}MemberAccountRole"
STACKSET_NAME = f"{SERVICENOW_PREFIX}MemberAccountRole"
CMDB_USER_NAME = f"{SERVICENOW_PREFIX}User"

_session = None

def get_session():
    """Get or create a shared boto3 session using the current AWS credentials."""
    global _session
    if _session is None:
        _session = boto3.Session(
            profile_name=AWS_PROFILE,
            region_name=AWS_REGION,
        )
    return _session

def get_client(service: str, region: str = None):
    """Get a boto3 client for a service using the shared session."""
    session = get_session()
    return session.client(service, region_name=region or AWS_REGION)
