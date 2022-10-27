"""This module is responsible for setting up the application
load balancer to interface with route53, and then connects the
load balancer to target the given reverse proxy instances.
"""
from typing import List
import pulumi
import pulumi_aws as aws


class TransportLayerSecurity:
    """Describes the transport layer security - everything that's required
    to handle a request up until the reverse proxy takes over on an unsecured
    connection.

    In particular, the client connects over TLS to the application load balancer
    which is responsible for forwarding those requests to the reverse proxy instances.
    """

    def __init__(
        self,
        resource_name: str,
        domain: str,
        vpc: pulumi.Input[str],
        subnets: pulumi.Input[List[str]],
        targets: pulumi.Input[List[str]],
    ) -> None:
        """Creates a new set of transport layer security over the given domain
        within the given region to target the given reverse proxies.

        Args:
            resource_name (str): The resource name prefix to use for all resources
                that this creates, e.g., "tls"
            domain (str): The domain which should resolve to the reverse proxies.
                For example: "google.com." - note the trailing dot.
            vpc (Input[str]): the id of the virtual private cloud containing the
                targets
            subnets (list[Input[str]]): the ids of the subnets the targets are in.
            targets (list[Input[str]]): the ids of the ec2 instances which should
                receive HTTP requests over port 80
        """
        self.resource_name: str = resource_name
        """The resource name prefix we use for all resources we create, e.g., 'tls'"""

        self.domain: str = domain
        """The domain that receives requests with a trailing dot. For example,
        "google.com."
        """

        self.vpc: pulumi.Output[str] = pulumi.Output.from_input(vpc)
        """The id of the virtual private cloud containing the targets"""

        self.subnets: pulumi.Output[List[str]] = pulumi.Output.from_input(subnets)
        """The subnets which contain all of the targets"""

        self.targets: pulumi.Output[List[str]] = pulumi.Output.from_input(targets)
        """The ids of the ec2 instances that will receive HTTP requests
        over port 80
        """

        self.security_group: aws.ec2.SecurityGroup = aws.ec2.SecurityGroup(
            f"{resource_name}-security-group",
            vpc_id=self.vpc,
            description="ALB security group - allows ingress everywhere from 80/443",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=80, protocol="tcp", to_port=80, cidr_blocks=["0.0.0.0/0"]
                ),
                aws.ec2.SecurityGroupIngressArgs(
                    from_port=443,
                    protocol="tcp",
                    to_port=443,
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    from_port=0, protocol=-1, to_port=0, cidr_blocks=["0.0.0.0/0"]
                )
            ],
            tags={"Name": "ALB security group from pulumi"},
        )
        """The security group for the application load balancer"""

        self.load_balancer: aws.alb.LoadBalancer = aws.alb.LoadBalancer(
            f"{resource_name}-alb",
            internal=False,
            load_balancer_type="application",
            security_groups=[self.security_group.id],
            drop_invalid_header_fields=True,
            subnets=self.subnets,
            tags={"Name": "LB from Pulumi"},
        )

        self.target_group: aws.alb.TargetGroup = aws.alb.TargetGroup(
            f"{resource_name}-internal",
            port=80,
            protocol="HTTP",
            protocol_version="HTTP1",
            vpc_id=vpc,
            target_type="instance",
            stickiness=aws.alb.TargetGroupStickinessArgs(
                type="lb_cookie", enabled=False
            ),
            tags={"Name": "internal target group from pulumi"},
        )

        self.targets: List[aws.alb.TargetGroupAttachment] = [
            aws.alb.TargetGroupAttachment(
                f"{resource_name}-target-{idx}",
                target_group_arn=self.target_group.arn,
                target_id=target,
                port=80,
            )
            for idx, target in enumerate(targets)
        ]
        """The attachments for each target to the target group
        """

        self.route53_zone: aws.route53.Zone = aws.route53.get_zone(name=domain)
        """The route53 zone corresponding to the domain"""

        domain_without_trailing_dot = domain.rstrip(".")
        self.certificate: aws.acm.Certificate = aws.acm.Certificate(
            f"{resource_name}-certificate",
            domain_name=domain_without_trailing_dot,
            subject_alternative_names=[f"*.{domain_without_trailing_dot}"],
            validation_method="DNS",
        )
        """The certificate that we requested that AWS Amazon Certiface Manager
        create on our behalf for our domain and all subdomains
        """

        self.validation_records: List[aws.route53.Record] = [
            aws.route53.Record(
                f"{resource_name}-validation-record-{idx}",
                allow_overwrite=True,
                name=self.certificate.domain_validation_options.apply(
                    lambda opts: opts[idx].resource_record_name
                ),
                records=[
                    self.certificate.domain_validation_options.apply(
                        lambda opts: opts[idx].resource_record_value
                    )
                ],
                ttl=60,
                type=self.certificate.domain_validation_options.apply(
                    lambda opts: opts[idx].resource_record_type
                ),
                zone_id=self.route53_zone.zone_id,
            )
            for idx in range(2)
        ]
        """The validation records required to show the amazon certificate manager
        that we indeed own the domain. Pulumi doesn't let us create the "correct"
        number of records, which we don't know until we create the certificate,
        so we are forced to hardcode that we expect 2 records (one for the main
        domain, one for the wildcard subdomain)
        """

        self.certificate_validation: aws.acm.CertificateValidation = (
            aws.acm.CertificateValidation(
                f"{resource_name}-cert-validation",
                certificate_arn=self.certificate.arn,
                validation_record_fqdns=[
                    record.fqdn for record in self.validation_records
                ],
            )
        )
        """The confirmation that the amazon certificate manager is satisfied with
        our ownership over the domain and hence will issue us certificates for it.
        """

        self.lb_tls_listener: aws.alb.Listener = aws.alb.Listener(
            f"{resource_name}-alb-tls-listener",
            load_balancer_arn=self.load_balancer.arn,
            port="443",
            protocol="HTTPS",
            ssl_policy="ELBSecurityPolicy-FS-1-2-Res-2020-10",
            certificate_arn=self.certificate.arn,
            default_actions=[
                aws.alb.ListenerDefaultActionArgs(
                    type="forward", target_group_arn=self.target_group.arn
                )
            ],
        )
        """Forwards HTTPS traffic to the target group"""

        self.lb_unsecure_listener: aws.alb.Listener = aws.alb.Listener(
            f"{resource_name}-alb-unsecure-listener",
            load_balancer_arn=self.load_balancer.arn,
            port="80",
            protocol="HTTP",
            default_actions=[
                aws.alb.ListenerDefaultActionArgs(
                    type="redirect",
                    redirect=aws.alb.ListenerDefaultActionRedirectArgs(
                        port="443", protocol="HTTPS", status_code="HTTP_301"
                    ),
                )
            ],
        )
        """Redirects insecure http traffic to the secure endpoint"""

        self.lb_www_v4_record: aws.route53.Record = aws.route53.Record(
            f"{resource_name}-lb-www-v4-record",
            zone_id=self.route53_zone.zone_id,
            name=pulumi.Output.from_input(domain).apply(lambda d: f"www.{d}"),
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.load_balancer.dns_name,
                    zone_id=self.load_balancer.zone_id,
                    evaluate_target_health=False,
                )
            ],
        )
        """Record to direct www.(domain) traffic to the load balancer via ipv4"""

        self.lb_www_v6_record: aws.route53.Record = aws.route53.Record(
            f"{resource_name}-lb-www-v6-record",
            zone_id=self.route53_zone.zone_id,
            name=pulumi.Output.from_input(domain).apply(lambda d: f"www.{d}"),
            type="AAAA",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.load_balancer.dns_name,
                    zone_id=self.load_balancer.zone_id,
                    evaluate_target_health=False,
                )
            ],
        )
        """Record to direct www.(domain) traffic to the load balancer via ipv6"""

        self.lb_v4_record: aws.route53.Record = aws.route53.Record(
            f"{resource_name}-lb-v4-record",
            zone_id=self.route53_zone.zone_id,
            name=domain,
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.load_balancer.dns_name,
                    zone_id=self.load_balancer.zone_id,
                    evaluate_target_health=False,
                )
            ],
        )
        """Record to direct (domain) traffic to the load balancer via ipv4"""

        self.lb_v6_record: aws.route53.Record = aws.route53.Record(
            f"{resource_name}-lb-v6-record",
            zone_id=self.route53_zone.zone_id,
            name=domain,
            type="AAAA",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.load_balancer.dns_name,
                    zone_id=self.load_balancer.zone_id,
                    evaluate_target_health=False,
                )
            ],
        )
        """Record to direct (domain) traffic to the load balancer via ipv6"""
