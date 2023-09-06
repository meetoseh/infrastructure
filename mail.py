"""This module facilitates SES via an auto-subscribing SNS route"""

import secrets
from typing import List, Optional, TypedDict
import pulumi
import pulumi_aws as aws
from pulumi.dynamic import ResourceProvider, CreateResult, Resource
from tls import TransportLayerSecurity
import subprocess


class SimpleEmailService:
    """Contains the setup related to amazon simple email service"""

    def __init__(
        self,
        resource_name: str,
        tls: TransportLayerSecurity,
        sns_path: str,
        deps: List[pulumi.Resource],
    ) -> None:
        """Initializes the simple email service using the confirmed domain
        in the given transport layer security instance, with SNS used to
        receive notifications about email delivery. The SNS topic will be
        created and a subscription will be attached to the given path,
        which must be auto-subscribed by the corresponding path. Since that
        requires that the backend is ready to run, the dependencies list
        should include e.g., the reverse proxy, backend, databases, etc.

        Args:
            resource_name (str): A unique prefix used for all resources
                created by this instance
            tls (TransportLayerSecurity): The transport layer security
                instance to use for the domain
            sns_path (str): The path to subscribe to for email delivery
                notifications, e.g., /api/1/emails/sns-mail
            deps (List[pulumi.Resource]): The list of dependencies to
                wait for before autoconfirming the subscription
        """
        self.resource_name: str = resource_name
        """A unique prefix used for all resources created by this instance"""

        self.tls: TransportLayerSecurity = tls
        """The transport layer security instance to use for the domain"""

        self.sns_path: str = sns_path
        """The path to subscribe to for email delivery notifications"""

        self.deps: List[pulumi.Resource] = deps
        """The list of dependencies to wait for before autoconfirming the
        subscription"""

        trimmed_domain = self.tls.domain.rstrip(".")

        self.domain_identity = aws.ses.DomainIdentity(
            f"{resource_name}-domain-identity",
            domain=trimmed_domain,
            opts=pulumi.ResourceOptions(depends_on=[self.tls.certificate_validation]),
        )
        """The domain identity that we will send emails from"""

        self.verification_record = aws.route53.Record(
            f"{resource_name}-verification-record",
            zone_id=tls.route53_zone.zone_id,
            name=f"_amazonses.{trimmed_domain}",
            type="TXT",
            ttl=600,
            records=[self.domain_identity.verification_token],
        )
        """The verification record that is verified to show we control the domain identity"""

        self.verification = aws.ses.DomainIdentityVerification(
            f"{resource_name}-verification",
            domain=trimmed_domain,
            opts=pulumi.ResourceOptions(depends_on=[self.verification_record]),
        )
        """The verification that shows we control the domain identity"""

        self.dkim = aws.ses.DomainDkim(
            f"{resource_name}-dkim",
            domain=trimmed_domain,
            opts=pulumi.ResourceOptions(depends_on=[self.verification]),
        )
        """DKIM records that can be used to verify emails sent from this domain"""

        self.dkim_records = []

        def _create_dkim_record(idx: int):
            # need to bind to a new variable idx rather than the loop
            # variable, otherwise all records will be the same
            return aws.route53.Record(
                f"{resource_name}-dkim-record-{idx}-b",
                zone_id=tls.route53_zone.zone_id,
                name=self.dkim.dkim_tokens.apply(
                    lambda tokens: f"{tokens[idx]}._domainkey"
                ),
                type="CNAME",
                ttl=600,
                records=[
                    self.dkim.dkim_tokens.apply(
                        lambda tokens: f"{tokens[idx]}.dkim.amazonses.com"
                    )
                ],
            )

        self.dkim_records = [_create_dkim_record(i) for i in range(3)]
        """The three route53 records used to facilitate DKIM"""

        self.mail_feedback = aws.sns.Topic(
            f"{resource_name}-mail-feedback",
            name_prefix=resource_name,
        )
        """The SNS topic that will receive email delivery notifications"""

        self.mail_feedback_to_api = aws.sns.TopicSubscription(
            f"{resource_name}-mail-feedback-to-api",
            topic=self.mail_feedback.arn,
            protocol="https",
            confirmation_timeout_in_minutes=2,
            delivery_policy="""{
  "healthyRetryPolicy": {
    "minDelayTarget": 5,
    "maxDelayTarget": 180,
    "numRetries": 10,
    "numNoDelayRetries": 1,
    "numMinDelayRetries": 2,
    "numMaxDelayRetries": 2,
    "backoffFunction": "arithmetic"
  }
}""",
            endpoint_auto_confirms=True,
            endpoint=f"https://{trimmed_domain}{sns_path}",
            opts=pulumi.ResourceOptions(depends_on=deps),
        )
        """The SNS topic subscription that will send email delivery notifications to the backend"""

        self.bounce_subscription = aws.ses.IdentityNotificationTopic(
            f"{resource_name}-bounce-subscription",
            topic_arn=self.mail_feedback.arn,
            notification_type="Bounce",
            identity=self.domain_identity.domain,
        )
        """Indicates to SES that we want to receive bounce notifications via SNS"""

        self.complaint_subscription = aws.ses.IdentityNotificationTopic(
            f"{resource_name}-complaint-subscription",
            topic_arn=self.mail_feedback.arn,
            notification_type="Complaint",
            identity=self.domain_identity.domain,
        )
        """Indicates to SES that we want to receive complaint notifications via SNS"""

        self.delivery_subscription = aws.ses.IdentityNotificationTopic(
            f"{resource_name}-delivery-subscription",
            topic_arn=self.mail_feedback.arn,
            notification_type="Delivery",
            identity=self.domain_identity.domain,
        )
        """Indicates to SES that we want to receive delivery notifications via SNS"""

        self.email_forwarding_disabled = DisableEmailFeedbackForwardingResource(
            f"{resource_name}-email-forwarding-disabled",
            DAFFInputs(domain=trimmed_domain),
            opts=pulumi.ResourceOptions(
                depends_on=[
                    self.bounce_subscription,
                    self.complaint_subscription,
                    self.verification,
                ]
            ),
        )
        """Disables email forwarding for the domain"""


class DAFFInputs(TypedDict):
    domain: pulumi.Input[str]


class _DAFFInputs(TypedDict):
    domain: str


class DisableEmailFeedbackForwarding(ResourceProvider):
    def create(self, inputs: _DAFFInputs):
        new_id = secrets.token_urlsafe(16)
        subprocess.call(
            [
                "aws",
                "ses",
                "set-identity-feedback-forwarding-enabled",
                "--identity",
                inputs["domain"],
                "--no-forwarding-enabled",
                "--region",
                "us-west-2",
            ],
            shell=True,
        )
        return CreateResult(id_=new_id, outs={})


class DisableEmailFeedbackForwardingResource(Resource):
    def __init__(
        self,
        name: str,
        props: DAFFInputs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__(DisableEmailFeedbackForwarding(), name, props, opts)
