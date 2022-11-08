from typing import List
import pulumi
import pulumi_aws as aws
import vpc
from tls import TransportLayerSecurity
from key import Key
import webapp
import rqlite
import redis
import reverse_proxy
import urllib.parse
import ipaddress
from cognito import Cognito

config = pulumi.Config()
github_username = config.require("github_username")
github_pat = config.require_secret("github_pat")
domain = config.require("domain")
rqlite_id_offset = config.get_int("rqlite_id_offset")
if rqlite_id_offset is None:
    rqlite_id_offset = 0
deployment_secret = config.require_secret("deployment_secret")
slack_web_errors_url = config.require_secret("slack_web_errors_url")
slack_ops_url = config.require_secret("slack_ops_url")
google_oidc_client_id = config.require("google_oidc_client_id")
google_oidc_client_secret = config.require_secret("google_oidc_client_secret")
expo_username = config.require("expo_username")
expo_app_slug = config.require("expo_app_slug")
development_expo_urls = [
    u for u in config.get("development_expo_urls", default="").split(",") if u != ""
]
webapp_counter = config.get_int("webapp_counter")
"""the webapp counter doesn't do anything, but changing it will rebuild all the webapps--useful for testing"""
apple_app_id_team_id = config.require("apple_app_id_team_id")
apple_services_id = config.require("apple_services_id")
apple_key_id = config.require("apple_key_id")
apple_key_file = config.require("apple_key_file")

# it's easy to misuse development_expo_urls, so we make sure it's valid
for idx, url_str in enumerate(development_expo_urls):
    url = urllib.parse.urlparse(url_str)
    assert (
        url.scheme == "exp"
    ), f"development_expo_urls[{idx}]: expected {url_str=} scheme to be exp, got {url.scheme=}"
    assert (
        url.port == 19000
    ), f"development_expo_urls[{idx}]: expected {url_str=} port to be 19000, got {url.port=}"
    try:
        ip = ipaddress.ip_address(url.hostname)
    except:
        assert (
            False
        ), f"development_expo_urls[{idx}]: expected {url_str=} hostname to be an IP address, got {url.hostname=}"

    assert (
        ip.is_private
    ), f"development_expo_urls[{idx}]: expected {url_str=} hostname to be private, got {url.hostname=}"


key = Key("key", "key.pub", "key.openssh")

main_vpc = vpc.VirtualPrivateCloud("main_vpc", key)
main_rqlite = rqlite.RqliteCluster("main_rqlite", main_vpc, id_offset=rqlite_id_offset)
main_redis = redis.RedisCluster("main_redis", main_vpc)


def make_standard_webapp_configuration(args) -> str:
    rqlite_ips: List[str] = args[: len(main_rqlite.instances)]
    redis_ips: List[str] = args[
        len(rqlite_ips) : len(rqlite_ips) + len(main_redis.instances)
    ]
    remaining = args[len(rqlite_ips) + len(redis_ips) :]
    deploy_secret: str = remaining[0]
    web_errors_url: str = remaining[1]
    ops_url: str = remaining[2]
    login_url: str = remaining[3]
    auth_domain: str = remaining[4]
    auth_client_id: str = remaining[5]
    public_kid_url: str = remaining[6]
    expected_issuer: str = remaining[7]
    domain: str = remaining[8]
    s3_bucket_name: str = remaining[9]

    joined_rqlite_ips = ",".join(rqlite_ips)
    joined_redis_ips = ",".join(redis_ips)

    return "\n".join(
        [
            f'export RQLITE_IPS="{joined_rqlite_ips}"',
            f'export REDIS_IPS="{joined_redis_ips}"',
            f'export DEPLOYMENT_SECRET="{deploy_secret}"',
            f'export SLACK_WEB_ERRORS_URL="{web_errors_url}"',
            f'export SLACK_OPS_URL="{ops_url}"',
            f'export LOGIN_URL="{login_url}"',
            f'export AUTH_DOMAIN="{auth_domain}"',
            f'export AUTH_CLIENT_ID="{auth_client_id}"',
            f'export PUBLIC_KID_URL="{public_kid_url}"',
            f'export EXPECTED_ISSUER="{expected_issuer}"',
            f'export ROOT_FRONTEND_URL="https://{domain}"',
            f'export ROOT_BACKEND_URL="https://{domain}"',
            f'export ROOT_WEBSOCKET_URL="wss://{domain}"',
            f'export OSEH_S3_BUCKET_NAME="{s3_bucket_name}"',
            f"export ENVIRONMENT=production",
            f"export AWS_DEFAULT_REGION=us-west-2",
        ]
    )


bucket = aws.s3.Bucket("bucket", acl="private", tags={"Name": "oseh"})
backend_rest = webapp.Webapp(
    "backend_rest",
    main_vpc,
    "meetoseh/backend",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter,
)
backend_ws = webapp.Webapp(
    "backend_ws",
    main_vpc,
    "meetoseh/websocket",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter,
)
frontend = webapp.Webapp(
    "frontend",
    main_vpc,
    "meetoseh/frontend-web",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    instance_type="t4g.small",  # node requires 1.2gb ram to build :/
    bleeding_ami=True,  # required for node 18
    webapp_counter=webapp_counter,
)
jobs = webapp.Webapp(
    "jobs",
    main_vpc,
    "meetoseh/jobs",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter,
)
main_reverse_proxy = reverse_proxy.ReverseProxy(
    "main_reverse_proxy", main_vpc, key, backend_rest, backend_ws, frontend
)
tls = TransportLayerSecurity(
    "tls",
    domain,
    main_vpc.vpc.id,
    [subnet.id for subnet in main_vpc.public_subnets],
    [instance.id for instance in main_reverse_proxy.reverse_proxies],
)
cognito = Cognito(
    "cognito",
    tls=tls,
    google_oidc_client_id=google_oidc_client_id,
    google_oidc_client_secret=google_oidc_client_secret,
    apple_app_id_team_id=apple_app_id_team_id,
    apple_services_id=apple_services_id,
    apple_key_id=apple_key_id,
    apple_key_file=apple_key_file,
    expo_username=expo_username,
    expo_app_slug=expo_app_slug,
    development_expo_urls=development_expo_urls,
)
standard_configuration = pulumi.Output.all(
    *[instance.private_ip for instance in main_rqlite.instances],
    *[instance.private_ip for instance in main_redis.instances],
    deployment_secret,
    slack_web_errors_url,
    slack_ops_url,
    cognito.token_login_url,
    cognito.auth_domain,
    cognito.user_pool_client.id,
    cognito.public_kid_url,
    cognito.expected_issuer,
    domain,
    bucket.bucket,
).apply(make_standard_webapp_configuration)

backend_rest.perform_remote_executions(standard_configuration)
backend_ws.perform_remote_executions(standard_configuration)
frontend.perform_remote_executions(standard_configuration)
jobs.perform_remote_executions(standard_configuration)
