
from mcp.server.fastmcp import FastMCP
from config import get_client
from tools.graph_connector import (
    setup_config_aggregator,
    cleanup_config_aggregator,
    create_cmdb_user,
    cleanup_cmdb_user,
    deploy_member_roles,
    check_stackset_status,
    cleanup_member_roles,
)
from tools.securityhub import (
    create_securityhub_user,
    create_securityhub_queue,
    generate_test_finding,
    cleanup_securityhub_user,
    cleanup_securityhub_queue
)
from tools.health import (
    create_health_queue,
    cleanup_health_queue
)

from tools.validation import (
    check_aggregator_status,
    check_securityhub_queue, check_health_queue,
)


mcp = FastMCP("servicenow-aws")

# Test Tool
@mcp.tool()
def ping() -> str:
    """Health check - verify the MCP server is running."""
    return "pong"

# Check with which AWS Identity the resources are being created
@mcp.tool()
def whoami() -> str:
    """Check which AWS account and identity the MCP server is using."""
    sts = get_client("sts")
    identity = sts.get_caller_identity()
    return f"Account: {identity['Account']}, ARN: {identity['Arn']}"

## Config
# Setup Config Aggregator for ServiceNow
mcp.tool()(setup_config_aggregator)

# Clean up Config Aggregator if not required
mcp.tool()(cleanup_config_aggregator)

# Create ServiceNow CMDB user
mcp.tool()(create_cmdb_user)

# Clean up ServiceNow CMDB user if not required
mcp.tool()(cleanup_cmdb_user)

# Deploy ServiceNow role to all org accounts via StackSet
mcp.tool()(deploy_member_roles)

# Check ServiceNow Role StackSet Status
mcp.tool()(check_stackset_status)

# Clean up ServiceNow role if not required
mcp.tool()(cleanup_member_roles)

## Security Hub
# Create SecurityHub ServiceNow user
mcp.tool()(create_securityhub_user)

# Create SQS Queue to which SecurityHub events will be published
mcp.tool()(create_securityhub_queue)

# Generate SecurityHub sample finding
mcp.tool()(generate_test_finding)

# Clean up SecurityHub ServiceNow user if not required
mcp.tool()(cleanup_securityhub_user)

# Clean up SecurityHub ServiceNow queue if not required
mcp.tool()(cleanup_securityhub_queue)

## AWS Health
# Create SQS Queue to which AWS Health events will be published
mcp.tool()(create_health_queue)

# Clean up AWS Health ServiceNow queue if not required
mcp.tool()(cleanup_health_queue)

## Validation
# Validate AWS Config ServiceNow Aggregator Status
mcp.tool()(check_aggregator_status)

# Validate SecurityHub Queue
mcp.tool()(check_securityhub_queue)

# Validate AWS Health Queue
mcp.tool()(check_health_queue)

# Cleanup all resources created for ServiceNow implementation
@mcp.tool()
def cleanup_all() -> str:
    """
    Delete ALL ServiceNow integration resources (except queues).

    NOTE:
    1. StackSet instance deletion is async. After this tool completes:
       - Run check_stackset_status until status is SUCCEEDED
       - Run cleanup_member_roles again to delete the StackSet definition
    2. SQS queues and EventBridge rules are NOT deleted by this tool.
       Queue names are ServiceNow defaults shared across integrations.
       Use cleanup_securityhub_queue and cleanup_health_queue individually
       only when you are certain no other integration depends on them.
    """
    results = []
    results.append(f"StackSet instances: {cleanup_member_roles()}")
    results.append(f"SecurityHub user: {cleanup_securityhub_user()}")
    results.append(f"CMDB user: {cleanup_cmdb_user()}")
    results.append(f"Config aggregator: {cleanup_config_aggregator()}")
    return "\n".join(results)


if __name__ == "__main__":
    mcp.run()