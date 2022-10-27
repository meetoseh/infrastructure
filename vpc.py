"""Constructs the virtual private cloud and subnets for the infrsstructure"""
from typing import List
import pulumi
import pulumi_aws as aws
from key import Key
import json

AVAILABILITY_ZONES = ["us-west-2b", "us-west-2c", "us-west-2d"]
"""The availability zones which we use"""


class VirtualPrivateCloud:
    """The actual VPC and corresponding subnets/route tables."""

    def __init__(self, resource_name: str, key: Key) -> None:
        """Creates a new virtual private cloud in three availability
        zones, where each availability zone has a public and private subnet,
        and each public subnet has a NAT gateway which can be used by the
        private subnets.

        Args:
            resource_name (str): The resource name prefix to use for resources
                created by this instance
            key (Key): the key to use for the bastion
        """
        self.resource_name: str = resource_name
        """The resource name to prefix resource names for for resources
        created by this instance
        """

        self.key: Key = key
        """The key used for the bastion server"""

        self.availability_zones: List[str] = AVAILABILITY_ZONES
        """The availability zones that the subnets are in"""

        self.vpc: aws.ec2.Vpc = aws.ec2.Vpc(
            f"{resource_name}_vpc",
            cidr_block="10.0.0.0/16",
            enable_dns_hostnames=True,
            tags={"Name": "VPC from pulumi"},
        )
        """The actual VPC"""

        self.igw: aws.ec2.InternetGateway = aws.ec2.InternetGateway(
            f"{resource_name}-igw",
            vpc_id=self.vpc.id,
            tags={"Name": "Internet Gateway from pulumi"},
        )
        """The internet gateway for the public subnets"""

        self.public_subnets: List[aws.ec2.Subnet] = [
            aws.ec2.Subnet(
                f"{resource_name}-public-subnet-{idx}",
                availability_zone=zone,
                vpc_id=self.vpc.id,
                cidr_block=f"10.0.{idx*2+1}.0/24",
            )
            for idx, zone in enumerate(AVAILABILITY_ZONES)
        ]
        """The public subnets for each availability zone"""

        self.private_subnets: List[aws.ec2.Subnet] = [
            aws.ec2.Subnet(
                f"{resource_name}-private-subnet-{idx}",
                availability_zone=zone,
                vpc_id=self.vpc.id,
                cidr_block=f"10.0.{idx*2+2}.0/24",
            )
            for idx, zone in enumerate(AVAILABILITY_ZONES)
        ]
        """The private subnets for each availabiltiy zone"""

        self.public_route_tables: List[aws.ec2.RouteTable] = [
            aws.ec2.RouteTable(
                f"{resource_name}-public-route-table-{idx}",
                vpc_id=self.vpc.id,
                routes=[
                    aws.ec2.RouteTableRouteArgs(
                        cidr_block="0.0.0.0/0", gateway_id=self.igw.id
                    )
                ],
            )
            for idx in range(len(AVAILABILITY_ZONES))
        ]
        """The route tables for each public subnet"""

        self.public_rtas: List[aws.ec2.RouteTableAssociation] = [
            aws.ec2.RouteTableAssociation(
                f"{resource_name}-public-rta-{idx}",
                subnet_id=subnet.id,
                route_table_id=route_table.id,
            )
            for idx, subnet, route_table in zip(
                range(len(self.public_subnets)),
                self.public_subnets,
                self.public_route_tables,
            )
        ]
        """The route table association for each public subnet"""

        self.nat_ami = aws.ec2.get_ami(
            most_recent=True,
            filters=[
                aws.ec2.GetAmiFilterArgs(name="name", values=["amzn-ami-vpc-nat-*"]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
                aws.ec2.GetAmiFilterArgs(name="architecture", values=["x86_64"]),
            ],
            owners=["137112412989"],
        )
        """The Amazon Machine Id for the NAT gateways"""

        self.nat_security_group = aws.ec2.SecurityGroup(
            f"{resource_name}-nat_security_group",
            description="Allow all traffic",
            vpc_id=self.vpc.id,
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=0, protocol="-1", to_port=0, cidr_blocks=["0.0.0.0/0"]
                )
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0, protocol="-1", to_port=0, cidr_blocks=["0.0.0.0/0"]
                )
            ],
        )
        """The security group for the NAT gateways"""

        self.nats: List[aws.ec2.Instance] = [
            aws.ec2.Instance(
                f"{resource_name}-nat-{idx}",
                instance_type="t3a.nano",
                ami=self.nat_ami.id,
                vpc_security_group_ids=[self.nat_security_group.id],
                subnet_id=public_subnet.id,
                source_dest_check=False,
                associate_public_ip_address=True,
                tags={"Name": f"pulumi NAT for {az}"},
            )
            for idx, public_subnet, az in zip(
                range(len(AVAILABILITY_ZONES)), self.public_subnets, AVAILABILITY_ZONES
            )
        ]
        """The NAT ec2 instances for each public subnet"""

        self.private_route_tables: List[aws.ec2.RouteTable] = [
            aws.ec2.RouteTable(
                f"{resource_name}-route-table-{idx}",
                vpc_id=self.vpc.id,
                routes=[
                    aws.ec2.RouteTableRouteArgs(
                        cidr_block="0.0.0.0/0",
                        network_interface_id=nat.primary_network_interface_id,
                    )
                ],
            )
            for idx, nat in enumerate(self.nats)
        ]
        """The route tables for the private subnets"""

        self.private_rtas: List[aws.ec2.RouteTableAssociation] = [
            aws.ec2.RouteTableAssociation(
                f"{resource_name}-private-rta-{idx}",
                subnet_id=subnet.id,
                route_table_id=route_table.id,
            )
            for idx, subnet, route_table in zip(
                range(len(AVAILABILITY_ZONES)),
                self.private_subnets,
                self.private_route_tables,
            )
        ]
        """The route table associations for the private subnets"""

        self.amazon_linux_arm64 = aws.ec2.get_ami(
            most_recent=True,
            filters=[
                aws.ec2.GetAmiFilterArgs(name="name", values=["amzn2-ami-*"]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
                aws.ec2.GetAmiFilterArgs(name="architecture", values=["arm64"]),
            ],
            owners=["137112412989"],
        )
        """The preferred arm64 ami"""

        self.amazon_linux_amd64 = aws.ec2.get_ami(
            most_recent=True,
            filters=[
                aws.ec2.GetAmiFilterArgs(name="name", values=["amzn2-ami-*"]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
                aws.ec2.GetAmiFilterArgs(name="architecture", values=["x86_64"]),
            ],
            owners=["137112412989"],
        )
        """The preferred amd64 ami"""

        self.amazon_linux_bleeding_arm64 = aws.ec2.get_ami(
            most_recent=True,
            filters=[
                aws.ec2.GetAmiFilterArgs(name="name", values=["al2022-ami-20*"]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
                aws.ec2.GetAmiFilterArgs(name="architecture", values=["arm64"]),
            ],
            owners=["137112412989"],
        )
        """The bleeding edge arm64 ami, for if the preferred one is too out of date"""

        self.bastion_security_group: aws.ec2.SecurityGroup = aws.ec2.SecurityGroup(
            f"{resource_name}-bastion-security-group",
            description="Allow incoming port 22",
            vpc_id=self.vpc.id,
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0, protocol="-1", to_port=0, cidr_blocks=["0.0.0.0/0"]
                )
            ],
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=22, protocol="tcp", to_port=22, cidr_blocks=["0.0.0.0/0"]
                )
            ],
            tags={"Name": f"{resource_name} bastion"},
        )

        self.standard_iam_role = aws.iam.Role(
            f"{resource_name}_standard_iam_role",
            assume_role_policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Action": "sts:AssumeRole",
                            "Effect": "Allow",
                            "Sid": "",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                        }
                    ],
                }
            ),
            tags={
                "Name": "webapp-iam-role",
            },
        )
        """The standard iam role with no additional permissions"""

        self.standard_instance_profile = aws.iam.InstanceProfile(
            f"{resource_name}_standard_instance_profile",
            role=self.standard_iam_role.name,
        )
        """The standard instance profile with no additional permissions"""

        self.bastion: aws.ec2.Instance = aws.ec2.Instance(
            f"{resource_name}-bastion",
            ami=self.amazon_linux_arm64.id,
            associate_public_ip_address=True,
            subnet_id=self.public_subnets[0].id,
            instance_type="t4g.nano",
            key_name=key.key_pair.key_name,
            vpc_security_group_ids=[self.bastion_security_group.id],
            iam_instance_profile=self.standard_instance_profile.name,
            tags={"Name": f"{resource_name}-bastion"},
        )
        """The bastion server which can connect to the instances"""

        pulumi.export(f"{resource_name} bastion", self.bastion.public_ip)
