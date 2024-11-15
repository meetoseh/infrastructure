"""This module allows creating a redis cluster (using redis sentinel)"""
from typing import List, Optional
from remote_executor import RemoteExecution, RemoteExecutionInputs
from vpc import VirtualPrivateCloud
import pulumi_aws as aws
import pulumi


class RedisCluster:
    """Describes a redis cluster with one server on each subnet"""

    def __init__(
        self,
        resource_name: str,
        vpc: VirtualPrivateCloud,
        allow_maintenance_subnet_idx: Optional[int] = None,
        maintenance_counter: Optional[int] = None,
        main_ip: Optional[str] = None,
    ) -> None:
        """Creates a new rqlite cluster running on the private subnets
        of the given virtual private cloud.

        Args:
            resource_name (str): the resource name prefix to use for resources
                created by this instance
            vpc (VirtualPrivateCloud): the virtual private cloud to construct
                the rqlite cluster within
            allow_maintenance_subnet_id (int): the subnet id to allow maintenance
                on. On other instances we will ignore standard maintenance for
                replacing the instance, e.g., ami. If None, no maintenance will
                be allowed. Typically this should be set to 0, the first subnet -
                and when we detect maintenance (a diff on ami, for example), it
                should be cycled one at a time through the subnets until all are
                updated, before returning to 1
            maintenance_counter (int, None): If specified, added as a tag to the
                instances, forcing them to be recreated if maintenance is enabled.
                Helpful when testing maintenance.
            main_ip (str, None): If specified, the IP address of the main redis
                instance right now. Should be used whenever replacing an instance
                using allow_maintenance_subnet_id, otherwise we will get split
                head syndrome. Should never replace the main instance directly;
                always force a failover first.
        """
        if allow_maintenance_subnet_idx is not None and main_ip is None:
            raise Exception(
                "main_ip must be specified if allow_maintenance_subnet_idx is specified"
            )

        self.resource_name: str = resource_name
        """the resource name prefix to use for resources created by this instance"""

        self.vpc: VirtualPrivateCloud = vpc
        """the virtual private cloud the cluster is within"""

        self.security_group: aws.ec2.SecurityGroup = aws.ec2.SecurityGroup(
            f"{resource_name}-security-group",
            description="allows incoming 6379 tcp (redis) and 26379 (sentinel) + ssh from bastion",
            vpc_id=self.vpc.vpc.id,
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=6379,
                    to_port=6379,
                    protocol="tcp",
                    cidr_blocks=["0.0.0.0/0"],
                ),
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=26379,
                    to_port=26379,
                    protocol="tcp",
                    cidr_blocks=["0.0.0.0/0"],
                ),
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=22,
                    to_port=22,
                    protocol="tcp",
                    cidr_blocks=[
                        self.vpc.bastion.private_ip.apply(lambda ip: f"{ip}/32")
                    ],
                ),
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0, to_port=0, protocol="-1", cidr_blocks=["0.0.0.0/0"]
                )
            ],
            tags={"Name": f"{resource_name} redis"},
        )

        self.instances: List[aws.ec2.Instance] = [
            aws.ec2.Instance(
                f"{resource_name}-instance-{idx}",
                ami=self.vpc.amazon_linux_amd64.id,
                associate_public_ip_address=False,
                instance_type="t3a.nano",
                subnet_id=subnet.id,
                key_name=self.vpc.key.key_pair.key_name,
                vpc_security_group_ids=[self.security_group.id],
                iam_instance_profile=self.vpc.standard_instance_profile.name,
                root_block_device=aws.ec2.InstanceRootBlockDeviceArgs(
                    iops=3000, throughput=125, volume_size=4, volume_type="gp3"
                ),
                tags={
                    "Name": f"{resource_name} {vpc.availability_zones[idx]} [{idx}]",
                    **(
                        dict()
                        if maintenance_counter is None
                        else {"maintenance": str(maintenance_counter)}
                    ),
                },
                opts=pulumi.ResourceOptions(
                    ignore_changes=(
                        ["ami", "instance_type", "tags"]
                        if allow_maintenance_subnet_idx != idx
                        else []
                    ),
                    replace_on_changes=(
                        [] if allow_maintenance_subnet_idx != idx else ["tags"]
                    ),
                ),
            )
            for idx, subnet in enumerate(self.vpc.private_subnets)
        ]
        """the instances within this cluster"""

        self.remote_executions: List[RemoteExecution] = []
        """the remote executions required to bootstrap and maintain the cluster"""

        for idx_outer, instance in enumerate(self.instances):

            def generate_file_substitutions(args):
                main_ip = args[-1]
                idx: int = args[-2]
                instance_ips: List[str] = args[:-2]
                my_ip = instance_ips[idx]
                quorum = (len(self.instances) // 2) + 1

                return {
                    "config.sh": {
                        "MY_IP": my_ip,
                        "MAIN_IP": main_ip,
                        "QUORUM": str(quorum),
                    },
                    "redis.conf": {"MY_IP": my_ip},
                    "sentinel.conf": {
                        "MY_IP": my_ip,
                        "MAIN_IP": main_ip,
                        "QUORUM": str(quorum),
                    },
                }

            self.remote_executions.append(
                RemoteExecution(
                    f"{resource_name}-remote-execution-{idx_outer}",
                    props=RemoteExecutionInputs(
                        script_name="setup-scripts/redis",
                        file_substitutions=pulumi.Output.all(
                            *[i.private_ip for i in self.instances],
                            idx_outer,
                            main_ip
                            if main_ip is not None
                            else self.instances[0].private_ip,
                        ).apply(generate_file_substitutions),
                        host=instance.private_ip,
                        private_key=self.vpc.key.private_key_path,
                        bastion=self.vpc.bastion.public_ip,
                        shared_script_name="setup-scripts/shared",
                    ),
                    opts=pulumi.ResourceOptions(
                        ignore_changes=[
                            "bastion",
                            *(
                                [
                                    "file_substitutions",
                                    "script_name",
                                    "shared_script_name",
                                ]
                                if allow_maintenance_subnet_idx != idx_outer
                                else []
                            ),
                        ]
                    ),
                )
            )
