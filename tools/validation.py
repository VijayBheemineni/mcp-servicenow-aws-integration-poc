from botocore.exceptions import ClientError
from config import get_client, AGGREGATOR_NAME, SERVICENOW_PREFIX


def check_aggregator_status(
    aggregator_name: str = "",
) -> str:
    """
    Check if the Config aggregator exists and its configuration.

    Args:
        aggregator_name: Name of the aggregator to check.
            [Default: {SERVICENOW_PREFIX}Aggregator]
    """
    config = get_client("config")
    aggregator_name = aggregator_name or AGGREGATOR_NAME

    try:
        response = config.describe_configuration_aggregators(
            ConfigurationAggregatorNames=[aggregator_name],
        )
        agg = response["ConfigurationAggregators"][0]

        org_source = agg.get("OrganizationAggregationSource", {})
        regions = org_source.get("AwsRegions", ["All regions"])
        filters = agg.get("AggregatorFilters", {})
        resource_types = filters.get("ResourceType", {}).get("Value", ["All types"])

        return (
            f"Aggregator '{aggregator_name}' exists.\n"
            f"Regions: {', '.join(regions)}\n"
            f"Resource types: {', '.join(resource_types)}"
        )
    except ClientError as e:
        return f"Error: {e.response['Error']['Message']}"


def check_securityhub_queue() -> str:
    """Check SecurityHub SQS queue status — exists, message count, EventBridge rule."""
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForSecurityHubQueue"
    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"

    results = []

    # Check queue
    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        msg_count = attrs["Attributes"]["ApproximateNumberOfMessages"]
        results.append(f"Queue: OK ({msg_count} messages)")
    except ClientError:
        results.append("Queue: NOT FOUND")

    # Check EventBridge rule
    try:
        rule = events.describe_rule(Name="SecurityHubToServiceNow")
        results.append(f"EventBridge rule: {rule['State']}")
    except ClientError:
        results.append("EventBridge rule: NOT FOUND")

    return f"SecurityHub pipeline — {', '.join(results)}"


def check_health_queue() -> str:
    """Check Health SQS queue status — exists, message count, EventBridge rule."""
    sqs = get_client("sqs")
    events = get_client("events")
    sts = get_client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = sqs.meta.region_name
    queue_name = "AwsServiceManagementConnectorForHealthDashboardQueue"
    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"

    results = []

    # Check queue
    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        msg_count = attrs["Attributes"]["ApproximateNumberOfMessages"]
        results.append(f"Queue: OK ({msg_count} messages)")
    except ClientError:
        results.append("Queue: NOT FOUND")

    # Check EventBridge rule
    try:
        rule = events.describe_rule(Name="HealthEventsToServiceNow")
        results.append(f"EventBridge rule: {rule['State']}")
    except ClientError:
        results.append("EventBridge rule: NOT FOUND")

    return f"Health pipeline — {', '.join(results)}"

