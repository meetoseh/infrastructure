"""Amazon Cognito is a user identification service which supports
sign in through social identity providers like Google, Facebook,
Amazon, or Apple, and through SAML identity providers, as well as
through direct user sign-in.
"""
from typing import List
import pulumi
import pulumi_aws as aws
from urllib.parse import urlencode
from tls import TransportLayerSecurity


class Cognito:
    """Initializes the Amazon Cognito resources required to implement
    seamless complex sign-in options
    """

    def __init__(
        self,
        resource_name: str,
        tls: TransportLayerSecurity,
        google_oidc_client_id: pulumi.Input[str],
        google_oidc_client_secret: pulumi.Input[str],
        expo_username: pulumi.Input[str],
        expo_app_slug: pulumi.Input[str],
        development_expo_urls: pulumi.Input[List[str]],
    ) -> None:
        """Creates the appropriate Amazon Cognito resources.

        Args:
            resource_name (str): the resource name prefix to use
                for resources created by this instance
            tls (TransportLayerSecurity): the transport layer security which
                is used for configuring the subdomain for authorization
            google_oidc_client_id (str): The client id for using google as an
                identity provider
            google_oidc_client_secret (str): The client secret for using google as
                an identity provider
            expo_username (str): The username for the React Expo application, which
                is used for native apps. This is used to allowlist the required
                callback url for the native app:
                https://docs.expo.dev/versions/latest/sdk/auth-session/
            expo_app_slug (str): The slug for the React Expo application
            development_expo_urls (list[str]): A list of url's that should be allowed
                as callback urls for cognito in order to support development. This is
                typically all exp:// endpoints for private IP addresses, and is required
                since the expo auth middleman doesn't work correctly in some contexts:
                https://github.com/expo/expo/issues/8957
        """
        self.resource_name: str = resource_name
        """the prefix used for resources created by this instance"""

        self.tls: TransportLayerSecurity = tls
        """the main websites TLS settings"""

        self.google_oidc_client_id: pulumi.Output[str] = pulumi.Output.from_input(
            google_oidc_client_id
        )
        """the oauth client id to use google as an identity provider"""

        self.google_oidc_client_secret: pulumi.Output[str] = pulumi.Output.from_input(
            google_oidc_client_secret
        )
        """the oauth client secret to use google as an identity provider"""

        self.expo_username: pulumi.Output[str] = pulumi.Output.from_input(expo_username)
        """the username for the React Expo application, which is used for native apps"""

        self.expo_app_slug: pulumi.Output[str] = pulumi.Output.from_input(expo_app_slug)
        """the slug for the React Expo application"""

        self.development_expo_urls: pulumi.Output[List[str]] = pulumi.Output.from_input(
            development_expo_urls
        )
        """A list of url's that should be allowed as callback urls for cognito in order
        to support development"""

        self.expo_callback_url: pulumi.Output[str] = pulumi.Output.all(
            expo_username, expo_app_slug
        ).apply(lambda args: f"https://auth.expo.io/@{args[0]}/{args[1]}")
        """the callback url for the React Expo application"""

        self.user_pool: aws.cognito.UserPool = aws.cognito.UserPool(
            f"{self.resource_name}-user-pool",
            account_recovery_setting=aws.cognito.UserPoolAccountRecoverySettingArgs(
                recovery_mechanisms=[
                    aws.cognito.UserPoolAccountRecoverySettingRecoveryMechanismArgs(
                        name="verified_email", priority=1
                    ),
                ],
            ),
            admin_create_user_config=aws.cognito.UserPoolAdminCreateUserConfigArgs(
                allow_admin_create_user_only=False,
            ),
            auto_verified_attributes=["email"],
            device_configuration=aws.cognito.UserPoolDeviceConfigurationArgs(
                challenge_required_on_new_device=True,
                device_only_remembered_on_user_prompt=True,
            ),
            mfa_configuration="OPTIONAL",
            software_token_mfa_configuration=aws.cognito.UserPoolSoftwareTokenMfaConfigurationArgs(
                enabled=True
            ),
            schemas=[
                aws.cognito.UserPoolSchemaArgs(
                    attribute_data_type="String",
                    name="email",
                    developer_only_attribute=False,
                    mutable=True,
                    required=True,
                    string_attribute_constraints=aws.cognito.UserPoolSchemaStringAttributeConstraintsArgs(
                        max_length=320, min_length=2
                    ),
                ),
                aws.cognito.UserPoolSchemaArgs(
                    attribute_data_type="String",
                    name="name",
                    developer_only_attribute=False,
                    mutable=True,
                    required=True,
                    string_attribute_constraints=aws.cognito.UserPoolSchemaStringAttributeConstraintsArgs(
                        max_length=320, min_length=2
                    ),
                ),
                aws.cognito.UserPoolSchemaArgs(
                    attribute_data_type="String",
                    name="phone_number",
                    developer_only_attribute=False,
                    mutable=True,
                    required=False,
                    string_attribute_constraints=aws.cognito.UserPoolSchemaStringAttributeConstraintsArgs(
                        max_length=32, min_length=5
                    ),
                ),
                aws.cognito.UserPoolSchemaArgs(
                    attribute_data_type="String",
                    name="picture",
                    developer_only_attribute=False,
                    mutable=True,
                    required=False,
                    string_attribute_constraints=aws.cognito.UserPoolSchemaStringAttributeConstraintsArgs(
                        max_length=2048, min_length=6
                    ),
                ),
            ],
            alias_attributes=["email"],
            username_configuration=aws.cognito.UserPoolUsernameConfigurationArgs(
                case_sensitive=False
            ),
            tags={
                "Name": f"{self.resource_name}-user-pool",
            },
        )
        """the actual user pool to authenticate users"""

        self.expected_issuer: pulumi.Output[str] = self.user_pool.id.apply(
            lambda _id: f"https://cognito-idp.us-west-2.amazonaws.com/{_id}"
        )
        """The expected issuer for the json tokens"""

        self.public_kid_url: pulumi.Output[str] = self.user_pool.id.apply(
            lambda _id: f"https://cognito-idp.us-west-2.amazonaws.com/{_id}/.well-known/jwks.json"
        )
        """the URL where the correct JSON web key set (JWKS) can be found for the user pool
        see https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
        """

        domain_with_prefix: pulumi.Output[str] = pulumi.Output.from_input(
            self.tls.domain
        ).apply(lambda d: f"https://{d.rstrip('.')}")
        domain_with_prefix_and_trailing_slash: pulumi.Output[
            str
        ] = domain_with_prefix.apply(lambda d: f"{d}/")

        self.google_identity_provider: aws.cognito.IdentityProvider = (
            aws.cognito.IdentityProvider(
                f"{resource_name}-google-identity-provider",
                user_pool_id=self.user_pool.id,
                provider_name="Google",
                provider_type="Google",
                provider_details={
                    "authorize_scopes": "profile email openid",
                    "client_id": self.google_oidc_client_id,
                    "client_secret": self.google_oidc_client_secret,
                },
                attribute_mapping={
                    "email": "email",
                    "username": "sub",
                    "name": "name",
                    "picture": "picture",
                },
            )
        )
        """the google identity provider to allow sign in with google"""

        self.user_pool_client: aws.cognito.UserPoolClient = aws.cognito.UserPoolClient(
            f"{self.resource_name}-user-pool-client",
            user_pool_id=self.user_pool.id,
            generate_secret=False,
            callback_urls=pulumi.Output.all(
                [domain_with_prefix_and_trailing_slash],
                [self.expo_callback_url],
                self.development_expo_urls,
            ).apply(lambda args: sum(args, [])),
            default_redirect_uri=domain_with_prefix_and_trailing_slash,
            enable_token_revocation=True,
            prevent_user_existence_errors="ENABLED",
            allowed_oauth_flows_user_pool_client=True,
            allowed_oauth_flows=["code", "implicit"],
            allowed_oauth_scopes=[
                "email",
                "profile",
                "phone",
                "openid",
            ],
            read_attributes=[
                "email",
                "phone_number",
                "name",
                "given_name",
                "family_name",
                "picture",
            ],
            supported_identity_providers=[
                "COGNITO",
                self.google_identity_provider.provider_name,
            ],
            name=tls.domain.removesuffix("."),
        )
        """The user pool client which the frontend redirects to for generating tokens"""

        self.auth_domain: str = f"auth.{self.tls.domain}"
        """the domain to use for authentication, e.g., auth.example.com. - note the
        trailing slash
        """

        self.auth_certificate_provider: aws.Provider = aws.Provider(
            f"{resource_name}-auth-certificate-provider", region="us-east-1"
        )
        """The auth certificate provider; when using a custom domain with the
        user pool client we must be in the us east 1 region
        """

        auth_domain_without_trailing_dot = self.auth_domain.rstrip(".")
        self.auth_certificate: aws.acm.Certificate = aws.acm.Certificate(
            f"{resource_name}-certificate",
            opts=pulumi.ResourceOptions(provider=self.auth_certificate_provider),
            domain_name=auth_domain_without_trailing_dot,
            validation_method="DNS",
        )
        """The certificate we use for the auth subdomain in the us-east-1 region"""

        self.auth_validation_records: List[aws.route53.Record] = [
            aws.route53.Record(
                f"{resource_name}-validation-record-{idx}",
                allow_overwrite=True,
                name=self.auth_certificate.domain_validation_options.apply(
                    lambda opts: opts[idx].resource_record_name
                ),
                records=[
                    self.auth_certificate.domain_validation_options.apply(
                        lambda opts: opts[idx].resource_record_value
                    )
                ],
                ttl=60,
                type=self.auth_certificate.domain_validation_options.apply(
                    lambda opts: opts[idx].resource_record_type
                ),
                zone_id=self.tls.route53_zone.zone_id,
            )
            for idx in range(1)
        ]
        """The validation records for the auth certificate"""

        self.auth_certificate_validation: aws.acm.CertificateValidation = (
            aws.acm.CertificateValidation(
                f"{resource_name}-cert-validation",
                opts=pulumi.ResourceOptions(provider=self.auth_certificate_provider),
                certificate_arn=self.auth_certificate.arn,
                validation_record_fqdns=[
                    record.fqdn for record in self.auth_validation_records
                ],
            )
        )
        """The confirmation that the amazon certificate manager is satisfied with
        our ownership over the auth domain and hence will issue us certificates for it.
        """

        self.user_pool_domain: aws.cognito.UserPoolDomain = aws.cognito.UserPoolDomain(
            f"{resource_name}-user-pool-domain",
            opts=pulumi.ResourceOptions(
                depends_on=[
                    self.tls.lb_v4_record,
                    self.tls.certificate_validation,
                    self.tls.load_balancer,
                ]
            ),
            domain=auth_domain_without_trailing_dot,
            user_pool_id=self.user_pool.id,
            certificate_arn=self.auth_certificate.arn,
        )
        """the auth domain for the user pool (the auth subdomain of the main website)"""

        self.auth_route53_record: aws.route53.Record = aws.route53.Record(
            f"{resource_name}-auth-route53-record",
            name=self.auth_domain,
            type="A",
            zone_id=self.tls.route53_zone.zone_id,
            aliases=[
                aws.route53.RecordAliasArgs(
                    evaluate_target_health=False,
                    name=self.user_pool_domain.cloudfront_distribution_arn,
                    zone_id="Z2FDTNDATAQYW2",
                )
            ],
        )
        """The route53 record which directs the auth subdomain to the user pool"""

        self.login_url: pulumi.Output[str] = self.user_pool_domain.domain.apply(
            lambda d: f"https://{d}/login"
        )
        """The url for the login page"""

        self.token_login_url: pulumi.Output[str] = pulumi.Output.all(
            self.login_url,
            self.user_pool_client.id,
            domain_with_prefix_and_trailing_slash,
        ).apply(
            lambda args: f"{args[0]}?"
            + urlencode(
                {
                    "response_type": "token",
                    "client_id": args[1],
                    "redirect_uri": args[2],
                }
            )
        )
        """The URL to use for the token login"""

        pulumi.export(f"{resource_name}-token-login-url", self.token_login_url)
        pulumi.export(f"{resource_name}-client-id", self.user_pool_client.id)
