import dataclasses
import pathlib as pl
import logging
import time
import shlex
import random
import json
import datetime
from typing import List, Dict

import boto3
import botocore.exceptions

logger = logging.getLogger(__name__)


# All the instances created by this script will use this string in the name.
INSTANCE_NAME_STRING = "automated-agent-ci-cd"

MAX_PREFIX_LIST_UPDATE_ATTEMPTS = 20

# Age of the prefix entry ofter which it can be cleaned up.
PREFIX_LIST_ENTRY_REMOVE_THRESHOLD = 60 * 7  # Minutes

# We delete any old automated test nodes which are older than 4 hours
DELETE_OLD_NODES_TIMEDELTA = datetime.timedelta(hours=4)
DELETE_OLD_NODES_THRESHOLD_DT = datetime.datetime.utcnow() - DELETE_OLD_NODES_TIMEDELTA


@dataclasses.dataclass
class EC2DistroImage:
    """
    Simple specification of the ec2 AMI image.
    """
    image_id: str
    image_name: str
    size_id: str
    ssh_username: str


@dataclasses.dataclass
class AWSSettings:
    aws_access_key: str
    aws_secret_key: str
    private_key_path: str
    private_key_name: str
    region: str
    security_group: str
    security_groups_prefix_list_id: str
    ec2_objects_name_prefix: str


def create_ec2_instance_node(
        aws_settings: AWSSettings,
        ec2_image: EC2DistroImage,
        file_mappings: Dict = None,
        max_tries: int = 3,
        deploy_overall_timeout: int = 100,

        ec2_driver=None,
        boto3_client=None
):
    from libcloud.compute.types import Provider
    from libcloud.compute.base import NodeImage
    from libcloud.compute.base import NodeSize
    from libcloud.compute.base import DeploymentError
    from libcloud.compute.providers import get_driver
    from libcloud.compute.deployment import (
        FileDeployment,
        MultiStepDeployment,
    )
    import boto3

    if boto3_client is None:
        boto3_client = boto3.client(
            "ec2",
            aws_access_key_id=aws_settings.aws_access_key,
            aws_secret_access_key=aws_settings.aws_secret_key,
            region_name=aws_settings.region,
        )

    if ec2_driver is None:
        driver_cls = get_driver(Provider.EC2)
        ec2_driver = driver_cls(
            aws_settings.aws_access_key,
            aws_settings.aws_secret_key,
            region=aws_settings.region
        )

    cleanup_old_prefix_list_entries(
        boto3_client=boto3_client,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix
    )
    cleanup_old_ec2_test_instance(
        libcloud_ec2_driver=ec2_driver,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix
    )

    add_current_ip_to_prefix_list(
        client=boto3_client,
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix
    )


    size = NodeSize(
        id=ec2_image.size_id,
        name=ec2_image.size_id,
        ram=0,
        disk=0,
        bandwidth=0,
        price=0,
        driver=ec2_driver,
    )
    image = NodeImage(
        id=ec2_image.image_id, name=ec2_image.image_name, driver=ec2_driver
    )

    name = f"{INSTANCE_NAME_STRING}-{aws_settings.ec2_objects_name_prefix}-{ec2_image.image_name}"

    logger.info("Starting node provisioning ...")

    file_deployment_steps = []
    for source, dst in file_mappings.items():
        file_deployment_steps.append(FileDeployment(str(source), str(dst)))

    deployment = MultiStepDeployment(add=file_deployment_steps)

    try:
        return ec2_driver.deploy_node(
            name=name,
            image=image,
            size=size,
            ssh_key=aws_settings.private_key_path,
            ex_keyname=aws_settings.private_key_name,
            ex_security_groups=[aws_settings.security_group],
            ssh_username=ec2_image.ssh_username,
            ssh_timeout=20,
            max_tries=max_tries,
            wait_period=15,
            timeout=deploy_overall_timeout,
            deploy=deployment,
            at_exit_func=destroy_node_and_cleanup,
        )
    except DeploymentError as e:
        stdout = getattr(e.original_error, "stdout", None)
        stderr = getattr(e.original_error, "stderr", None)
        logger.exception(
            f"Deployment is not successful.\nStdout: {stdout}\nStderr: {stderr}"
        )
        raise


def run_ec2_instance(
    ec2_image: EC2DistroImage,
    command: List[str],
    private_key_path: str,
    private_key_name: str,
    access_key: str,
    secret_key: str,
    region: str,
    security_group: str,
    security_groups_prefix_list_id: str,
    max_tries: int = 3,
    deploy_overall_timeout: int = 100,
    file_mappings: Dict = None,
    unique_id: str = None,
):
    import paramiko
    from libcloud.compute.types import Provider
    from libcloud.compute.base import NodeImage
    from libcloud.compute.base import NodeSize
    from libcloud.compute.base import DeploymentError
    from libcloud.compute.providers import get_driver
    from libcloud.compute.deployment import (
        FileDeployment,
        MultiStepDeployment,
    )
    import boto3  # pylint: disable=import-error

    def prepare_node():

        size = NodeSize(
            id=ec2_image.size_id,
            name=ec2_image.size_id,
            ram=0,
            disk=0,
            bandwidth=0,
            price=0,
            driver=driver,
        )
        image = NodeImage(
            id=ec2_image.image_id, name=ec2_image.image_name, driver=driver
        )

        workflow_suffix = unique_id or ""
        name = f"{INSTANCE_NAME_STRING}-{workflow_suffix}-{ec2_image.image_name}"

        logger.info("Starting node provisioning ...")

        file_deployment_steps = []
        for source, dst in file_mappings.items():
            file_deployment_steps.append(FileDeployment(str(source), str(dst)))

        deployment = MultiStepDeployment(add=file_deployment_steps)

        try:
            return driver.deploy_node(
                name=name,
                image=image,
                size=size,
                ssh_key=private_key_path,
                ex_keyname=private_key_name,
                ex_security_groups=[security_group],
                ssh_username=ec2_image.ssh_username,
                ssh_timeout=20,
                max_tries=max_tries,
                wait_period=15,
                timeout=deploy_overall_timeout,
                deploy=deployment,
                at_exit_func=destroy_node_and_cleanup,
            )
        except DeploymentError as e:
            stdout = getattr(e.original_error, "stdout", None)
            stderr = getattr(e.original_error, "stderr", None)
            logger.exception(
                f"Deployment is not successful.\nStdout: {stdout}\nStderr: {stderr}"
            )
            raise

    def run_command():

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=node.public_ips[0],
            port=22,
            username=ec2_image.ssh_username,
            key_filename=str(private_key_path),
        )

        final_command = ["/tmp/test_runner", "-s", *command]

        command_str = shlex.join(final_command)  # pylint: disable=no-member
        stdin, stdout, stderr = ssh.exec_command(
            command=f"TEST_RUNS_REMOTELY=1 sudo -E {command_str} 2>&1",
        )

        logger.info(f"stdout: {stdout.read().decode()}")

        return_code = stdout.channel.recv_exit_status()

        ssh.close()

        if return_code != 0:
            raise Exception(
                f"Remote execution of test in ec2 instance has failed and returned {return_code}."
            )

    file_mappings = file_mappings or {}
    start_time = int(time.time())

    driver_cls = get_driver(Provider.EC2)
    driver = driver_cls(access_key, secret_key, region=region)

    # Add current public IP to security group's prefix list.
    # We have to update that prefix list each time because there are to many GitHub actions public IPs, and
    # it is not possible to whitelist all of them in the AWS prefix list.
    # NOTE: Take in mind that you may want to remove that IP in order to prevent prefix list from reaching its
    # size limit. For GitHub actions end-to-end tests we run a finalizer job that clears prefix list.
    boto_client = boto3.client(
        "ec2",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    add_current_ip_to_prefix_list(
        client=boto_client,
        prefix_list_id=security_groups_prefix_list_id,
        workflow_id=unique_id,
    )

    time.sleep(5)

    node = None
    try:
        node = prepare_node()
        run_command()
    finally:
        if node:
            destroy_node_and_cleanup(driver=driver, node=node)

    duration = int(time.time()) - start_time

    print(f"Succeeded! Duration: {duration} seconds")


def add_current_ip_to_prefix_list(client, prefix_list_id: str, ec2_objects_name_prefix: str = None):
    """
    Add new CIDR entry with current public IP in to the prefix list. We also additionally store json object in the
        Description of the prefix list entry. This json object has required field called 'time' with timestamp
        which is used by the cleanup script to remove old prefix lists.

    We have to add current IP to the prefix list in order to provide access for the runner to ec2 instances and have
        to do it every time because there are too many IPs for the GitHub actions and AWS prefix lists can not store
        so many.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    :param ec2_objects_name_prefix: Optional filed to add to the json object that is stored in the Description
        filed of the entry.
    """

    import botocore.exceptions  # pylint: disable=import-error
    import requests

    # Get current public IP.
    with requests.Session() as s:
        attempts = 10
        while True:
            try:
                resp = s.get("https://api.ipify.org")
                resp.raise_for_status()
                break
            except requests.HTTPError:
                if attempts == 0:
                    raise
                attempts -= 1
                time.sleep(1)

    public_ip = resp.content.decode()

    new_cidr = f"{public_ip}/32"

    attempts = 0
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=client, prefix_list_id=prefix_list_id
            )

            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                AddEntries=[
                    {
                        "Cidr": new_cidr,
                        "Description": json.dumps(
                            {"time": time.time(), "ec2_objects_name_prefix": ec2_objects_name_prefix}
                        ),
                    },
                ],
            )
            break
        except botocore.exceptions.ClientError as e:
            if attempts >= MAX_PREFIX_LIST_UPDATE_ATTEMPTS:
                logger.exception(
                    f"Can not add new entry to the prefix list {prefix_list_id}"
                )
                raise e

            attempts += 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))

    return new_cidr


def get_prefix_list_version(client, prefix_list_id: str):
    """
    Get version of the prefix list.
    :param client: ec2 boto3 client.
    :param prefix_list_id: ID of the prefix list.
    """
    resp = client.describe_managed_prefix_lists(
        Filters=[
            {"Name": "prefix-list-id", "Values": [prefix_list_id]},
        ],
    )
    found = resp["PrefixLists"]
    assert (
        len(found) == 1
    ), f"Number of found prefix lists has to be 1, got {len(found)}"
    prefix_list = found[0]
    return int(prefix_list["Version"])


def destroy_node_and_cleanup(driver, node):
    """
    Destroy the provided node and cleanup any left over EBS volumes.
    """

    assert (
        INSTANCE_NAME_STRING in node.name
    ), "Refusing to delete node without %s in the name" % (INSTANCE_NAME_STRING)

    print("")
    print(('Destroying node "%s"...' % (node.name)))

    try:
        node.destroy()
    except Exception as e:
        if "does not exist" in str(e):
            # Node already deleted, likely by another concurrent run. This error is not fatal so we
            # just ignore it.
            print(
                "Failed to delete node, likely node was already deleted, ignoring error..."
            )
            print(str(e))
        else:
            raise e

    volumes = driver.list_volumes(node=node)

    assert len(volumes) <= 1
    print("Cleaning up any left-over EBS volumes for this node...")

    # Wait for the volumes to become detached from the node
    remaining_volumes = volumes[:]

    timeout = time.time() + 100
    while remaining_volumes:
        if time.time() >= timeout:
            raise TimeoutError("Could not wait for all volumes being detached")
        time.sleep(1)
        remaining_volumes = driver.list_volumes(node=node)

    for volume in volumes:
        # Additional safety checks
        if volume.extra.get("instance_id", None) != node.id:
            continue

        if volume.size not in [8, 30]:
            # All the volumes we use are 8 GB EBS volumes
            # Special case is Windows 2019 with 30 GB volume
            continue

        destroy_volume_with_retry(driver=driver, volume=volume)


def destroy_volume_with_retry(driver, volume, max_retries=12, retry_sleep_delay=5):
    """
    Destroy the provided volume retrying up to max_retries time if destroy fails because the volume
    is still attached to the node.
    """
    retry_count = 0
    destroyed = False

    while not destroyed and retry_count < max_retries:
        try:
            try:
                driver.destroy_volume(volume=volume)
            except Exception as e:
                if "InvalidVolume.NotFound" in str(e):
                    pass
                else:
                    raise e
            destroyed = True
        except Exception as e:
            if "VolumeInUse" in str(e):
                # Retry in 5 seconds
                print(
                    "Volume in use, re-attempting destroy in %s seconds (attempt %s/%s)..."
                    % (retry_sleep_delay, retry_count + 1, max_retries)
                )

                retry_count += 1
                time.sleep(retry_sleep_delay)
            else:
                raise e

    if destroyed:
        print("Volume %s successfully destroyed." % (volume.id))
    else:
        print(
            "Failed to destroy volume %s after %s attempts." % (volume.id, max_retries)
        )

    return True



def cleanup_old_prefix_list_entries(
    boto3_client, prefix_list_id: str, ec2_objects_name_prefix: str = None
):
    """
    Cleanup ec2 test related prefix lists entries.
    :param boto3_client: boto3 client.
    :param prefix_list_id: Prefix list ID.
    :param ec2_objects_name_prefix: Workflow id to filter workflow related entries.
    :return:
    """
    resp = boto3_client.get_managed_prefix_list_entries(PrefixListId=prefix_list_id)
    entries = resp["Entries"]

    entries_to_remove = {}

    current_time = time.time()

    # Remove old prefix list entries.
    for entry in entries:
        timestamp = _parse_entry_timestamp(entry)
        if timestamp <= current_time - PREFIX_LIST_ENTRY_REMOVE_THRESHOLD:
            entries_to_remove[entry["Cidr"]] = entry

    # If workflow provided, then we also remove entries that have matching workflow_id field in
    # their Description field.
    if ec2_objects_name_prefix:
        for entry in entries:
            description = _parse_entry_description(entry)
            if description["workflow_id"] and description["workflow_id"] == ec2_objects_name_prefix:
                entries_to_remove[entry["Cidr"]] = entry

    if not entries_to_remove:
        return

    print(f"Removing entries: {entries_to_remove}")
    _remove_entries(
        client=boto3_client,
        entries=list(entries_to_remove.values()),
        prefix_list_id=prefix_list_id,
    )


def cleanup_old_ec2_test_instance(libcloud_ec2_driver, ec2_objects_name_prefix: str = None):
    """
    Cleanup old ec2 test instances.
    """
    from libcloud.utils.iso8601 import parse_date

    nodes = libcloud_ec2_driver.list_nodes()

    print("Looking for and deleting old running automated test nodes...")

    nodes_to_delete = []

    for node in nodes:
        if INSTANCE_NAME_STRING not in node.name:
            continue

        # Re remove instances which are created by the current workflow immediately.
        if ec2_objects_name_prefix in node.name:
            nodes_to_delete.append(node)
            continue

        launch_time = node.extra.get("launch_time", None)

        if not launch_time:
            continue

        launch_time_dt = parse_date(launch_time).replace(tzinfo=None)
        if launch_time_dt >= DELETE_OLD_NODES_THRESHOLD_DT:
            continue

        print(('Found node "%s" for deletion.' % (node.name)))

        nodes_to_delete.append(node)

    # TODO: For now we only print the node names to ensure script doesn't incorrectly delete
    # wrong nodes. We should uncomment out deletion once we are sure the script is correct.
    for node in nodes_to_delete:
        assert INSTANCE_NAME_STRING in node.name
        print("")
        destroy_node_and_cleanup(driver=driver, node=node)

    print("")
    print("Destroyed %s old nodes" % (len(nodes_to_delete)))



def _parse_entry_description(entry: Dict):
    """
    Parse json object from the description of the prefix list entry.
    Conventionally, we store useful information in it.
    """
    return json.loads(entry["Description"])


def _parse_entry_timestamp(entry: Dict) -> float:
    """
    Parse creation timestamp of the prefix list entry.
    """
    return float(_parse_entry_description(entry)["time"])


def _remove_entries(client, entries: List, prefix_list_id: str):
    """
    Remove specified entries from prefix list.
    :param client: boto3 client.
    :param entries: List of entries to remove.
    :param prefix_list_id: Prefix list ID.
    :return:
    """
    attempts = 20
    # Since there may be multiple running ec2 tests, we have to add the retry
    # logic to overcome the prefix list concurrent access issues.
    while True:
        try:
            version = get_prefix_list_version(
                client=client, prefix_list_id=prefix_list_id
            )
            client.modify_managed_prefix_list(
                PrefixListId=prefix_list_id,
                CurrentVersion=version,
                RemoveEntries=[{"Cidr": e["Cidr"]} for e in entries],
            )
            break
        except botocore.exceptions.ClientError as e:
            keep_trying = False
            if "The prefix list has the incorrect version number" in str(e):
                keep_trying = True

            if "The request cannot be completed while the prefix" in str(e):
                keep_trying = True

            if attempts == 0 or not keep_trying:
                raise

            attempts -= 1
            print(f"Can not modify prefix list, retry. Reason: {str(e)}")
            time.sleep(random.randint(1, 5))