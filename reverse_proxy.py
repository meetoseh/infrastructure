"""Constructs the appropriate number of reverse proxies on the
given subnets.
"""
import itertools
from typing import List, Sequence, Tuple
import pulumi
import pulumi_aws as aws
from key import Key
from remote_executor import RemoteExecution, RemoteExecutionInputs
from vpc import VirtualPrivateCloud
from webapp import Webapp


class ReverseProxy:
    """Contains the reverse proxies within the virtual private cloud"""

    def __init__(
        self,
        resource_name: str,
        vpc: VirtualPrivateCloud,
        key: Key,
        rest_backend: Webapp,
        ws_backend: Webapp,
        frontend: Webapp,
    ) -> None:
        """Creates a reverse proxy in the first 2 public subnets of
        the virtual private cloud

        Args:
            resource_name (str): The prefix for the names of resources
                created by this instance
            vpc (VirtualPrivateCloud): The vpc to create the reverse
                proxies in.
            rest_backend (Webapp): The webapp responsible for the REST
                backend
            ws_backend (Webapp): The webapp responsible for the websocket
                backend
            frontend (Webapp): The webapp responsible for the frontend
        """
        self.resource_name: str = resource_name
        """The prefix for the names of resoruces created by this instance"""

        self.vpc: VirtualPrivateCloud = vpc
        """The virtual private cloud that the reverse proxies reside in"""

        self.rest_backend: Webapp = rest_backend
        """The backend for REST api requests"""

        self.ws_backend: Webapp = ws_backend
        """The backend for websocket api requests"""

        self.frontend: Webapp = frontend
        """The application for frontend requests"""

        self.reverse_proxy_security_group: aws.ec2.SecurityGroup = (
            aws.ec2.SecurityGroup(
                f"{resource_name}-reverse-proxy-security-group",
                vpc_id=self.vpc.vpc.id,
                description="Allow inbound port 80 traffic",
                ingress=[
                    aws.ec2.SecurityGroupIngressArgs(
                        from_port=80,
                        protocol="tcp",
                        to_port=80,
                        cidr_blocks=["0.0.0.0/0"],
                    ),
                    aws.ec2.SecurityGroupIngressArgs(
                        from_port=22,
                        protocol="tcp",
                        to_port=22,
                        cidr_blocks=[
                            self.vpc.bastion.private_ip.apply(lambda ip: f"{ip}/32")
                        ],
                    ),
                ],
                egress=[
                    aws.ec2.SecurityGroupEgressArgs(
                        from_port=0, protocol="-1", to_port=0, cidr_blocks=["0.0.0.0/0"]
                    )
                ],
                tags={"Name": f"{resource_name} reverse proxy security group"},
            )
        )
        """The security group used for reverse proxies"""

        self.reverse_proxies: List[aws.ec2.Instance] = [
            aws.ec2.Instance(
                f"{resource_name}-reverse-proxy-{idx}",
                ami=self.vpc.amazon_linux_arm64.id,
                instance_type="t4g.nano",
                associate_public_ip_address=False,
                subnet_id=subnet.id,
                vpc_security_group_ids=[self.reverse_proxy_security_group.id],
                key_name=self.vpc.key.key_pair.key_name,
                iam_instance_profile=self.vpc.standard_instance_profile.name,
                tags={"Name": f"{resource_name} reverse proxy {idx}"},
            )
            for idx, subnet in enumerate(self.vpc.private_subnets[:2])
        ]
        """The reverse proxy instances"""

        self.reverse_proxy_installs: List[RemoteExecution] = [
            RemoteExecution(
                f"{resource_name}-reverse-proxy-installs-{idx}",
                RemoteExecutionInputs(
                    script_name="setup-scripts/reverse-proxy",
                    file_substitutions={
                        "nginx.conf": {
                            "BACKEND_UPSTREAM": get_upstreams(self.rest_backend),
                            "WEBSOCKET_UPSTREAM": get_upstreams(self.ws_backend),
                            "FRONTEND_UPSTREAM": get_upstreams(self.frontend),
                        }
                    },
                    host=instance.private_ip,
                    private_key=self.vpc.key.private_key_path,
                    bastion=self.vpc.bastion.public_ip,
                    shared_script_name="scripts/shared",
                ),
            )
            for idx, instance in enumerate(self.reverse_proxies)
        ]
        """The commands to install and configure nginx on each reverse proxy"""


def get_upstreams(webapp: Webapp) -> pulumi.Input[str]:
    """Produces the correct upstream substitution to target the given
    webapp, i.e., the string of the format

        server 10.0.1.0:80;
        server 10.0.2.0:80;

    where the ip addresses target instances of the webapp in all subnets
    """
    all_instances: List[aws.ec2.Instance] = list(
        itertools.chain(
            *[
                (inst for inst in subnet_insts)
                for subnet_insts in webapp.instances_by_subnet
            ]
        )
    )

    def make_upstream(ip_addresses: Tuple[Sequence[str]]) -> str:
        return "\n".join(f"server {ip}:80;" for ip in ip_addresses[0])

    return pulumi.Output.all([inst.private_ip for inst in all_instances]).apply(
        make_upstream
    )
