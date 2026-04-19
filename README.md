# ServiceNow AWS Integration MCP Server

> **⚠️ Proof of Concept** — This is a PoC to demonstrate how MCP can automate ServiceNow-AWS integration. Not production-ready. Review all code and test in a sandbox account before using in any environment.
>
> **🤖 AI-Assisted** — Parts of this code were generated with AI. All code was reviewed, tested, and validated against real AWS accounts.

An MCP server that automates the AWS-side setup for ServiceNow integration across a multi-account AWS Organization.

## What It Does

Instead of running 50+ CLI commands manually, this server provides tools that an AI assistant (or you via the MCP Inspector) can call to set up:

- **CMDB** — Config aggregator, cross-account IAM roles via StackSets, ServiceNow IAM user
- **SecurityHub Incidents** — IAM user, SQS queue, EventBridge rule
- **AWS Health Events** — SQS queue, EventBridge rule

All tools are idempotent — safe to re-run.

## Prerequisites

- Python 3.13+
- AWS CLI with SSO configured
- An AWS account that is delegated admin for both AWS Config and CloudFormation StackSets (or the management account)

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your AWS profile, region, and prefix

aws sso login --profile <your-profile>
hash -r
mcp dev server.py
```

Opens the MCP Inspector at http://localhost:6274 (port may vary).

## Connect to an IDE

Add below MCP server configuration:

```json
{
  "mcpServers": {
    "servicenow-aws": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

## Configuration

All resource names are derived from `SERVICENOW_PREFIX` in `.env`:

```
SERVICENOW_PREFIX=ServiceNow  →  ServiceNowAggregator, ServiceNowUser, ServiceNowMemberAccountRole
SERVICENOW_PREFIX=MyTest      →  MyTestAggregator, MyTestUser, MyTestMemberAccountRole
```

See `.env.example` for all options.

## Tools

| Tool | What it does |
|---|---|
| `setup_config_aggregator` | Create Config aggregator IAM role + aggregator with resource filters |
| `create_cmdb_user` | Create IAM user, group, assume-role policy |
| `deploy_member_roles` | Deploy cross-account role via StackSet to all org accounts |
| `create_securityhub_user` | Create IAM user with SecurityHub/SQS policies |
| `create_securityhub_queue` | Create SQS queue + EventBridge rule for SecurityHub |
| `create_health_queue` | Create SQS queue + EventBridge rule for Health events |
| `generate_test_finding` | Push a test SecurityHub finding |
| `check_stackset_status` | Check StackSet deployment progress |
| `check_aggregator_status` | Check aggregator config and resource types |
| `check_securityhub_queue` | Check queue status and message count |
| `check_health_queue` | Check Health queue status |
| `cleanup_all` | Delete all resources (except queues) |

Each tool also has a corresponding `cleanup_*` variant.

## Project Structure

```
├── server.py              # MCP server entry point
├── config.py              # AWS session management, .env loading
├── tools/
│   ├── graph_connector.py # CMDB tools (aggregator, user, StackSet)
│   ├── securityhub.py     # SecurityHub tools (user, queue, test finding)
│   ├── health.py          # Health tools (queue)
│   └── validation.py      # Status check tools
├── cloudformation/
│   └── servicenow-member-account-role.yaml
├── .env.example
└── requirements.txt
```
