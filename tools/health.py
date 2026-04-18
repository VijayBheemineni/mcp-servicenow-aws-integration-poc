import json
from botocore.exceptions import ClientError
from config import get_client


def create_health_queue() -> str:
    """
    Create SQS queue and EventBridge rule for AWS Health events.
    Queue name matches the default ServiceNow system property.
    """
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForHealthDashboardQueue"

    # Step 1: Create SQS queue (idempotent)
    try:
        queue_response = sqs.create_queue(QueueName=queue_name)
        queue_url = queue_response["QueueUrl"]
    except ClientError as e:
        return f"Error creating queue '{queue_name}': {e.response['Error']['Message']}"

    queue_arn = f"arn:aws:sqs:{region}:{account_id}:{queue_name}"

    # Step 2: Create EventBridge rule (idempotent)
    rule_name = "HealthEventsToServiceNow"
    try:
        events.put_rule(
            Name=rule_name,
            EventPattern=json.dumps({"source": ["aws.health"]}),
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

def cleanup_health_queue() -> str:
    """Delete the Health SQS queue and EventBridge rule."""
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForHealthDashboardQueue"
    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"
    rule_name = "HealthEventsToServiceNow"

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
