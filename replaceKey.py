"""
Replace a SSH private key in a EC2 backed by a EBS volume
"""
import argparse
import sys
import logging
import subprocess
import boto3.ec2

IMAGE_ID = 'ami-c91624b0'
INSTANCE_TYPE = 't2.micro'
KEY_NAME = ''
MAX_COUNT=1
MIN_COUNT=1

ec2 = boto3.resource('ec2')
client = boto3.client('ec2')

def get_instance_root_volume(instance_id):
    instance = ec2.Instance(instance_id)
    blocks = list(instance.block_device_mappings)

    for block in blocks:
        if block['DeviceName'] == instance.root_device_name:
            volume = block['Ebs']['VolumeId']

    return volume

def get_worker_instance(availabilityZone, subnetId):
    response = client.run_instances(
        ImageId=IMAGE_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        MaxCount=MAX_COUNT,
        MinCount=MIN_COUNT,
        Placement={
            'AvailabilityZone': availabilityZone
        },
        SubnetId=subnetId
    )

    worker_id = response['Instances'][0]['InstanceId']
    worker_instance = ec2.Instance(worker_id)

    filters = [{
        'Name': 'instance-id',
        'Values': [worker_id]
    }]

    logging.info("Waiting for worker instance %s to start....", worker_id)
    worker_instance.wait_until_running(Filters=filters)

    return worker_instance


def main(cmd_args):
    logging.info("Getting a list of block devices for instance: %s", cmd_args.instance)

    instance_root_volume = get_instance_root_volume(cmd_args.instance)
    logging.info("Root volume ID: %s", instance_root_volume)

    instance = ec2.Instance(cmd_args.instance)

    filters = [{
        'Name': 'instance-id',
        'Values': [instance.id]
    }]

    logging.info("Stopping instance ID: %s", cmd_args.instance)
    instance.stop()
    instance.wait_until_stopped(Filters=filters)
    logging.info("Instance stoped")

    logging.info("Detaching volume ID: %s", instance_root_volume)
    instance.detach_volume(VolumeId=instance_root_volume)

    logging.info("Launching a new worker instance.....")
    az = instance.placement.values()[2]
    subnet = instance.subnet_id
    worker_instance = get_worker_instance(az, subnet)

    logging.info("Attaching volume to worker instance")
    worker_instance.attach_volume(
        Device='/dev/xvdz',
        VolumeId=instance_root_volume
    )

    logging.info("Replacing SSH key in the volume")
    subprocess.call(["./script.sh", "-k", cmd_args.bastion_key, "-i", cmd_args.bastion_ip, "-u", cmd_args.bastion_user, "-K", cmd_args.instance_key, "-I", worker_instance.private_ip_address, "-U", cmd_args.instance_user])

    logging.info("Terminating worker instance")
    client.terminate_instances(InstanceIds=[worker_instance.id])

    filters = [{
        'Name': 'instance-id',
        'Values': [worker_instance.id]
    }]

    worker_instance.wait_until_terminated(Filters=filters)
    logging.info("Worker instance terminated")

    logging.info("Attaching volume %s back to original instance %s", instance_root_volume, instance.id)
    instance.attach_volume(Device=instance.root_device_name, InstanceId=instance.id, VolumeId=instance_root_volume)

    filters = [{
        'Name': 'instance-id',
        'Values': [instance.id]
    }]

    logging.info("Starting back original instance %s", instance.id)
    instance.start()
    instance.wait_until_running(Filters=filters)
    logging.info("Instance started")


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help()
        sys.stderr.write('error: %s\n' % message)
        sys.exit(2)

def command():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(levelname)s:%(message)s')

    parser = CommandParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""description:
  Replace a SSH private key in a EC2 backed by a EBS volume

example: main.py -i instance"
  """
    )
    parser.add_argument(
        "-k", "--bastion-key",
        dest="bastion_key",
        help="[REQUIRED] Bastion key",
        required=True
    )
    parser.add_argument(
        "-i", "--bastion-ip",
        dest="bastion_ip",
        help="[REQUIRED] Bastion IP",
        required=True
    )
    parser.add_argument(
        "-u", "--bastion-user",
        dest="bastion_user",
        help="[REQUIRED] Bastion user",
        required=True
    )
    parser.add_argument(
        "-K", "--instance-key",
        dest="instance_key",
        help="[REQUIRED] EC2 Instance key",
        required=True
    )
    parser.add_argument(
        "-I", "--instance",
        dest="instance",
        help="[REQUIRED] EC2 Instance ID",
        required=True
    )
    parser.add_argument(
        "-U", "--instance-user",
        dest="instance_user",
        help="[REQUIRED] EC2 Instance user",
        required=True
    )

    cmd_args = parser.parse_args()

    main(cmd_args)


if __name__ == "__main__":
    command()
