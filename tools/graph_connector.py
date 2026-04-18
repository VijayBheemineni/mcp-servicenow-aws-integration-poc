import json
import os
from botocore.exceptions import ClientError
from config import (
    get_client, AGGREGATOR_ROLE_NAME, AGGREGATOR_NAME,
    CONFIG_RESOURCE_TYPES, CONFIG_REGIONS, SERVICENOW_PREFIX,
    STACKSET_NAME, MEMBER_ACCOUNT_ROLE_NAME, CMDB_USER_NAME,
    ORG_ROOT_OU_ID
)


def setup_config_aggregator(
    resource_types: str = "",
    regions: str = "",
    aggregator_name: str = "",
    role_name: str = "",
) -> str:
    """
    Create the Config aggregator IAM role and organization aggregator.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        resource_types: Comma-separated AWS Config resource types to aggregate.
            [Default: CONFIG_RESOURCE_TYPES from .env]
            Example: AWS::EC2::Instance, AWS::S3::Bucket, AWS::Lambda::Function,
            AWS::RDS::DBInstance, AWS::DynamoDB::Table, AWS::IAM::Role,
            AWS::EC2::SecurityGroup, AWS::KMS::Key, AWS::SNS::Topic,
            AWS::SQS::Queue, AWS::ApiGateway::RestApi, AWS::CloudFormation::Stack,
            AWS::EC2::VPC, AWS::EC2::Volume, AWS::ElasticLoadBalancingV2::LoadBalancer,
            AWS::Route53::HostedZone, AWS::CloudFront::Distribution,
            AWS::ECS::Service, AWS::ECS::TaskDefinition, AWS::ECS::Cluster,
            AWS::ElastiCache::CacheCluster, AWS::ElastiCache::ReplicationGroup
        regions: Comma-separated AWS regions to aggregate.
            [Default: CONFIG_REGIONS from .env]
            Example: us-west-2, us-east-1
        aggregator_name: Unique name for the Config aggregator.
            [Default: {SERVICENOW_PREFIX}Aggregator]
        role_name: IAM role name for the aggregator.
            [Default: {SERVICENOW_PREFIX}AggregatorRole]
    """
    iam = get_client("iam")
    config = get_client("config")
    sts = get_client("sts")

    aggregator_name = aggregator_name or AGGREGATOR_NAME
    role_name = role_name or AGGREGATOR_ROLE_NAME
    account_id = sts.get_caller_identity()["Account"]
    resource_type_list = [r.strip() for r in (resource_types or CONFIG_RESOURCE_TYPES).split(",")]
    region_list = [r.strip() for r in (regions or CONFIG_REGIONS).split(",")]

    # Step 1: Create IAM role (idempotent)
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "config.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })

    role_created = True
    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=trust_policy,
        )
    except iam.exceptions.EntityAlreadyExistsException:
        role_created = False
    except ClientError as e:
        return f"Error creating IAM role '{role_name}': {e.response['Error']['Message']}"

    # Step 2: Attach managed policy (idempotent)
    try:
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSConfigRoleForOrganizations",
        )
    except ClientError as e:
        return f"Error attaching policy to role '{role_name}': {e.response['Error']['Message']}"

    # Step 3: Create Config aggregator
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    org_source = {"RoleArn": role_arn}
    if region_list:
        org_source["AllAwsRegions"] = False
        org_source["AwsRegions"] = region_list
    else:
        org_source["AllAwsRegions"] = True

    kwargs = {
        "ConfigurationAggregatorName": aggregator_name,
        "OrganizationAggregationSource": org_source,
    }

    if resource_type_list:
        kwargs["AggregatorFilters"] = {
            "ResourceType": {
                "Type": "INCLUDE",
                "Value": resource_type_list,
            }
        }

    try:
        config.put_configuration_aggregator(**kwargs)
    except ClientError as e:
        return f"Error creating aggregator '{aggregator_name}': {e.response['Error']['Message']}"

    role_status = "created" if role_created else "already exists"
    return f"Done. Role '{role_name}' {role_status}. Aggregator '{aggregator_name}' configured in account {account_id}"


def cleanup_config_aggregator(
    aggregator_name: str = "",
    role_name: str = "",
) -> str:
    """
    Delete the Config aggregator and its IAM role.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        aggregator_name: Name of the Config aggregator to delete.
            [Default: {SERVICENOW_PREFIX}Aggregator]
        role_name: IAM role name to delete.
            [Default: {SERVICENOW_PREFIX}AggregatorRole]
    """
    iam = get_client("iam")
    config = get_client("config")

    aggregator_name = aggregator_name or AGGREGATOR_NAME
    role_name = role_name or AGGREGATOR_ROLE_NAME

    # Step 1: Delete aggregator
    try:
        config.delete_configuration_aggregator(
            ConfigurationAggregatorName=aggregator_name,
        )
    except config.exceptions.NoSuchConfigurationAggregatorException:
        pass
    except ClientError as e:
        return f"Error deleting aggregator '{aggregator_name}': {e.response['Error']['Message']}"

    # Step 2: Detach policy (required before role deletion)
    try:
        iam.detach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSConfigRoleForOrganizations",
        )
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error detaching policy from role '{role_name}': {e.response['Error']['Message']}"

    # Step 3: Delete role
    try:
        iam.delete_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting role '{role_name}': {e.response['Error']['Message']}"

    return f"Cleaned up. Aggregator '{aggregator_name}' and role '{role_name}' deleted."

def create_cmdb_user(
    user_name: str = "",
    member_role_name: str = "",
) -> str:
    """
    Create the ServiceNow IAM user with a group and policy to assume the member account role.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        user_name: IAM user name for ServiceNow CMDB integration.
            [Default: {SERVICENOW_PREFIX}User]
        member_role_name: Member account role name the user will assume.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
    """
    iam = get_client("iam")

    user_name = user_name or CMDB_USER_NAME
    member_role_name = member_role_name or MEMBER_ACCOUNT_ROLE_NAME

    # Step 1: Create IAM user (idempotent)
    user_created = True
    try:
        iam.create_user(UserName=user_name)
    except iam.exceptions.EntityAlreadyExistsException:
        user_created = False
    except ClientError as e:
        return f"Error creating user '{user_name}': {e.response['Error']['Message']}"

    user_status = "created" if user_created else "already exists"

    # Step 2: Create IAM group (idempotent)
    group_name = f"{user_name}Group"
    try:
        iam.create_group(GroupName=group_name)
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    except ClientError as e:
        return f"Error creating group '{group_name}': {e.response['Error']['Message']}"

    # Step 3: Create assume-role policy
    account_id = get_client("sts").get_caller_identity()["Account"]
    policy_name = f"{user_name}AssumeRolePolicy"
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

    policy_doc = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": f"arn:aws:iam::*:role/{member_role_name}",
        }]
    })

    try:
        iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=policy_doc,
        )
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    except ClientError as e:
        return f"Error creating policy '{policy_name}': {e.response['Error']['Message']}"

    # Step 4: Attach policy to group (idempotent)
    try:
        iam.attach_group_policy(
            GroupName=group_name,
            PolicyArn=policy_arn,
        )
    except ClientError as e:
        return f"Error attaching policy to group: {e.response['Error']['Message']}"

    # Step 5: Add user to group (idempotent)
    try:
        iam.add_user_to_group(
            GroupName=group_name,
            UserName=user_name,
        )
    except ClientError as e:
        return f"Error adding user to group: {e.response['Error']['Message']}"

    user_status = "created" if user_created else "already exists"
    return f"Done. User '{user_name}' {user_status}, group '{group_name}', policy '{policy_name}' configured."


def cleanup_cmdb_user(
    user_name: str = "",
    member_role_name: str = "",
) -> str:
    """
    Delete the ServiceNow CMDB IAM user, group, and policy.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        user_name: IAM user name to delete.
            [Default: {SERVICENOW_PREFIX}User]
        member_role_name: Used to derive policy name.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
    """
    iam = get_client("iam")

    user_name = user_name or CMDB_USER_NAME
    member_role_name = member_role_name or MEMBER_ACCOUNT_ROLE_NAME
    group_name = f"{user_name}Group"
    policy_name = f"{user_name}AssumeRolePolicy"
    account_id = get_client("sts").get_caller_identity()["Account"]
    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

    # Step 1: Remove user from group
    try:
        iam.remove_user_from_group(GroupName=group_name, UserName=user_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error removing user from group: {e.response['Error']['Message']}"

    # Step 2: Detach policy from group
    try:
        iam.detach_group_policy(GroupName=group_name, PolicyArn=policy_arn)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error detaching policy from group: {e.response['Error']['Message']}"

    # Step 3: Delete policy
    try:
        iam.delete_policy(PolicyArn=policy_arn)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting policy '{policy_name}': {e.response['Error']['Message']}"

    # Step 4: Delete group
    try:
        iam.delete_group(GroupName=group_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting group '{group_name}': {e.response['Error']['Message']}"

    # Step 5: Delete user
    try:
        iam.delete_user(UserName=user_name)
    except iam.exceptions.NoSuchEntityException:
        pass
    except ClientError as e:
        return f"Error deleting user '{user_name}': {e.response['Error']['Message']}"

    return f"Cleaned up. User '{user_name}', group '{group_name}', policy '{policy_name}' deleted."


def deploy_member_roles(
    stackset_name: str = "",
    member_role_name: str = "",
    servicenow_user_name: str = "",
) -> str:
    """
    Deploy ServiceNow integration role to all org accounts via CloudFormation StackSet.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        stackset_name: Name for the CloudFormation StackSet.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
        member_role_name: IAM role name to create in each member account.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
        servicenow_user_name: ServiceNow IAM user name that will assume the role.
            [Default: {SERVICENOW_PREFIX}User]
    """
    cfn = get_client("cloudformation")
    sts = get_client("sts")

    stackset_name = stackset_name or STACKSET_NAME
    member_role_name = member_role_name or MEMBER_ACCOUNT_ROLE_NAME
    servicenow_user_name = servicenow_user_name or CMDB_USER_NAME
    account_id = sts.get_caller_identity()["Account"]

    # Read CloudFormation template
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "cloudformation", "servicenow-member-account-role.yaml"
    )
    with open(template_path, "r") as f:
        template_body = f.read()

    # Step 1: Create StackSet (idempotent)
    stackset_created = True
    try:
        cfn.create_stack_set(
            StackSetName=stackset_name,
            Description=f"Deploys {member_role_name} to all org accounts for ServiceNow integration",
            TemplateBody=template_body,
            Parameters=[
                {"ParameterKey": "DelegatedAccountId", "ParameterValue": account_id},
                {"ParameterKey": "ServiceNowUserName", "ParameterValue": servicenow_user_name},
                {"ParameterKey": "RoleName", "ParameterValue": member_role_name},
            ],
            Capabilities=["CAPABILITY_NAMED_IAM"],
            PermissionModel="SERVICE_MANAGED",
            AutoDeployment={
                "Enabled": True,
                "RetainStacksOnAccountRemoval": False,
            },
            CallAs="DELEGATED_ADMIN",
        )
    except cfn.exceptions.NameAlreadyExistsException:
        stackset_created = False
    except ClientError as e:
        return f"Error creating StackSet '{stackset_name}': {e.response['Error']['Message']}"

    stackset_status = "created" if stackset_created else "already exists"

    # Step 2: Create stack instances across the org
    try:
        response = cfn.create_stack_instances(
            StackSetName=stackset_name,
            DeploymentTargets={"OrganizationalUnitIds": [ORG_ROOT_OU_ID]},
            Regions=["us-west-2"],
            CallAs="DELEGATED_ADMIN",
        )
        operation_id = response.get("OperationId", "unknown")
    except ClientError as e:
        error_msg = e.response['Error']['Message']
        if "already running" in error_msg.lower():
            return f"StackSet '{stackset_name}' {stackset_status}. Stack instances deployment already in progress."
        return f"Error deploying stack instances: {error_msg}"

    stackset_status = "created" if stackset_created else "already exists"
    return f"Done. StackSet '{stackset_name}' {stackset_status}. Deploying to org. Operation ID: {operation_id}"

def check_stackset_status(
    stackset_name: str = "",
) -> str:
    """
    Check the deployment status of a CloudFormation StackSet.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        stackset_name: Name of the StackSet to check.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
    """
    cfn = get_client("cloudformation")
    stackset_name = stackset_name or STACKSET_NAME

    try:
        ops = cfn.list_stack_set_operations(
            StackSetName=stackset_name,
            CallAs="DELEGATED_ADMIN",
        )
        if not ops.get("Summaries"):
            return f"No operations found for StackSet '{stackset_name}'"

        latest = ops["Summaries"][0]
        status = latest.get("Status", "UNKNOWN")
        operation_id = latest.get("OperationId", "unknown")
        action = latest.get("Action", "unknown")

        return f"StackSet '{stackset_name}' — Latest operation: {action}, Status: {status}, Operation ID: {operation_id}"

    except ClientError as e:
        return f"Error checking StackSet '{stackset_name}': {e.response['Error']['Message']}"

def cleanup_member_roles(
    stackset_name: str = "",
) -> str:
    """
    Delete the StackSet and all stack instances from member accounts.
    All parameters are optional — defaults derived from SERVICENOW_PREFIX in .env.

    Args:
        stackset_name: Name of the StackSet to delete.
            [Default: {SERVICENOW_PREFIX}MemberAccountRole]
    """
    cfn = get_client("cloudformation")
    stackset_name = stackset_name or STACKSET_NAME

    from config import ORG_ROOT_OU_ID

    # Step 1: Try to delete the StackSet directly (works if no instances remain)
    try:
        cfn.delete_stack_set(
            StackSetName=stackset_name,
            CallAs="DELEGATED_ADMIN",
        )
        return f"StackSet '{stackset_name}' deleted."
    except cfn.exceptions.StackSetNotEmptyException:
        pass  # Instances still exist, need to delete them first
    except cfn.exceptions.OperationInProgressException:
        return f"StackSet '{stackset_name}' has an operation in progress. Run check_stackset_status and try again."
    except ClientError as e:
        error_msg = e.response['Error']['Message']
        if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
            return f"StackSet '{stackset_name}' not found. Nothing to clean up."
        return f"Error deleting StackSet: {error_msg}"

    # Step 2: Delete all stack instances first
    try:
        cfn.delete_stack_instances(
            StackSetName=stackset_name,
            DeploymentTargets={"OrganizationalUnitIds": [ORG_ROOT_OU_ID]},
            Regions=["us-west-2"],
            RetainStacks=False,
            CallAs="DELEGATED_ADMIN",
        )
    except ClientError as e:
        return f"Error deleting stack instances: {e.response['Error']['Message']}"

    return f"Stack instances deletion initiated for '{stackset_name}'. Run check_stackset_status to monitor. Once SUCCEEDED, re-run this tool to delete the StackSet."
