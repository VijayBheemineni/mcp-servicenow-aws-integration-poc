import json
from botocore.exceptions import ClientError
from config import get_client, SERVICENOW_PREFIX


def create_securityhub_user(
    user_name: str = "",
) -> str:
    """
    Create the ServiceNow IAM user for SecurityHub and Health integration.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        user_name: IAM user name for SecurityHub integration.
            [Default: {SERVICENOW_PREFIX}SecurityHubUser]
    """
    iam = get_client("iam")
    user_name = user_name or f"{SERVICENOW_PREFIX}SecurityHubUser"

    # Step 1: Create user (idempotent)
    user_created = True
    try:
        iam.create_user(UserName=user_name)
    except iam.exceptions.EntityAlreadyExistsException:
        user_created = False
    except ClientError as e:
        return f"Error creating user '{user_name}': {e.response['Error']['Message']}"

    # Step 2: Create inline policy with SecurityHub, SQS, Config, SSM permissions
    policy_doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SecurityHubAccess",
                "Effect": "Allow",
                "Action": [
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:DeleteMessageBatch",
                    "securityhub:BatchUpdateFindings",
                ],
                "Resource": "*",
            },
            {
                "Sid": "ConfigBiDirectional",
                "Effect": "Allow",
                "Action": [
                    "cloudformation:RegisterType",
                    "cloudformation:DescribeTypeRegistration",
                    "cloudformation:DeregisterType",
                    "config:PutResourceConfig",
                ],
                "Resource": "*",
            },
            {
                "Sid": "SSMAction",
                "Effect": "Allow",
                "Action": ["budgets:ViewBudget"],
                "Resource": "*",
            },
        ],
    })

    try:
        iam.put_user_policy(
            UserName=user_name,
            PolicyName=f"{user_name}Policy",
            PolicyDocument=policy_doc,
        )
    except ClientError as e:
        return f"Error creating policy for '{user_name}': {e.response['Error']['Message']}"

    # Step 3: Attach managed policies
    managed_policies = [
        "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess",
        "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole",
        "arn:aws:iam::aws:policy/AWSConfigUserAccess",
        "arn:aws:iam::aws:policy/AWSServiceCatalogAdminReadOnlyAccess",
    ]

    for policy_arn in managed_policies:
        try:
            iam.attach_user_policy(UserName=user_name, PolicyArn=policy_arn)
        except ClientError as e:
            return f"Error attaching policy '{policy_arn}': {e.response['Error']['Message']}"

    user_status = "created" if user_created else "already exists"
    return f"Done. User '{user_name}' {user_status} with SecurityHub/Health policies attached."

def create_securityhub_queue() -> str:
    """
    Create SQS queue and EventBridge rule for SecurityHub findings.
    Queue name matches the default ServiceNow system property.
    Only HIGH and CRITICAL severity findings are forwarded.
    """
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForSecurityHubQueue"

    # Step 1: Create SQS queue (idempotent)
    try:
        queue_response = sqs.create_queue(QueueName=queue_name)
        queue_url = queue_response["QueueUrl"]
    except ClientError as e:
        return f"Error creating queue '{queue_name}': {e.response['Error']['Message']}"

    queue_arn = f"arn:aws:sqs:{region}:{account_id}:{queue_name}"

    # Step 2: Create EventBridge rule (idempotent — put_rule is upsert)
    rule_name = "SecurityHubToServiceNow"
    try:
        events.put_rule(
            Name=rule_name,
            EventPattern=json.dumps({
                "source": ["aws.securityhub"],
                "detail": {
                    "findings": {
                        "Severity": {
                            "Label": ["HIGH", "CRITICAL"]
                        }
                    }
                }
            }),
            State="ENABLED",
        )
    except ClientError as e:
        return f"Error creating EventBridge rule '{rule_name}': {e.response['Error']['Message']}"

    rule_arn = f"arn:aws:events:{region}:{account_id}:rule/{rule_name}"

    # Step 3: Set SQS as EventBridge target (idempotent)
    try:
        events.put_targets(
            Rule=rule_name,
            Targets=[{"Id": "SQSTarget", "Arn": queue_arn}],
        )
    except ClientError as e:
        return f"Error setting EventBridge target: {e.response['Error']['Message']}"

    # Step 4: Set SQS resource policy allowing EventBridge
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": "sqs:SendMessage",
            "Resource": queue_arn,
            "Condition": {"ArnEquals": {"aws:SourceArn": rule_arn}},
        }]
    })

    try:
        sqs.set_queue_attributes(
            QueueUrl=queue_url,
            Attributes={"Policy": policy},
        )
    except ClientError as e:
        return f"Error setting queue policy: {e.response['Error']['Message']}"

    return f"Done. Queue '{queue_name}', rule '{rule_name}' created in {region}."

def generate_test_finding(
    severity: str = "HIGH",
) -> str:
    """
    Generate a test SecurityHub finding to validate the pipeline.

    Args:
        severity: Finding severity — CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL.
            [Default: HIGH]
    """
    sts = get_client("sts")
    securityhub = get_client("securityhub")

    account_id = sts.get_caller_identity()["Account"]
    region = securityhub.meta.region_name

    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    finding_id = f"mcp-test-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    try:
        securityhub.batch_import_findings(
            Findings=[{
                "SchemaVersion": "2018-10-08",
                "Id": finding_id,
                "ProductArn": f"arn:aws:securityhub:{region}:{account_id}:product/{account_id}/default",
                "GeneratorId": "mcp-test-generator",
                "AwsAccountId": account_id,
                "Types": ["Software and Configuration Checks/AWS Security Best Practices"],
                "CreatedAt": now,
                "UpdatedAt": now,
                "Severity": {"Label": severity.upper()},
                "Title": f"MCP Test Finding - {severity.upper()} Severity",
                "Description": "Test finding generated by MCP server to validate ServiceNow SecurityHub integration.",
                "Resources": [{
                    "Type": "AwsS3Bucket",
                    "Id": f"arn:aws:s3:::mcp-test-bucket-{finding_id}",
                    "Region": region,
                }],
                "Workflow": {"Status": "NEW"},
                "RecordState": "ACTIVE",
                "Compliance": {"Status": "FAILED"},
                "Sample": True,
            }]
        )
    except ClientError as e:
        return f"Error generating finding: {e.response['Error']['Message']}"

    return f"Done. Test finding '{finding_id}' with severity {severity.upper()} created in {region}."

def cleanup_securityhub_user(
    user_name: str = "",
) -> str:
    """
    Delete the SecurityHub IAM user and its policies.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        user_name: IAM user name to delete.
            [Default: {SERVICENOW_PREFIX}SecurityHubUser]
    """
    iam = get_client("iam")
    user_name = user_name or f"{SERVICENOW_PREFIX}SecurityHubUser"
    policy_name = f"{user_name}Policy"

    # Step 1: Delete inline policy
    try:
        iam.delete_user_policy(UserName=user_name, PolicyName=policy_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting inline policy: {e.response['Error']['Message']}"

    # Step 2: Detach managed policies
    managed_policies = [
        "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess",
        "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole",
        "arn:aws:iam::aws:policy/AWSConfigUserAccess",
        "arn:aws:iam::aws:policy/AWSServiceCatalogAdminReadOnlyAccess",
    ]
    for policy_arn in managed_policies:
        try:
            iam.detach_user_policy(UserName=user_name, PolicyArn=policy_arn)
        except iam.exceptions.NoSuchEntityException:
            pass
        except ClientError as e:
            return f"Error detaching policy '{policy_arn}': {e.response['Error']['Message']}"

    # Step 3: Delete user
    try:
        iam.delete_user(UserName=user_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting user '{user_name}': {e.response['Error']['Message']}"

    return f"Cleaned up. User '{user_name}' and policies deleted."


def cleanup_securityhub_queue() -> str:
    """Delete the SecurityHub SQS queue and EventBridge rule."""
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForSecurityHubQueue"
    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"
    rule_name = "SecurityHubToServiceNow"

    # Step 1: Remove targets from rule
    try:
        events.remove_targets(Rule=rule_name, Ids=["SQSTarget"])
    except ClientError:
        pass

    # Step 2: Delete rule
    try:
        events.delete_rule(Name=rule_name)
    except ClientError:
        pass

    # Step 3: Delete queue
    try:
        sqs.delete_queue(QueueUrl=queue_url)
    except ClientError:
        pass

    return f"Cleaned up. Queue '{queue_name}' and rule '{rule_name}' deleted."
