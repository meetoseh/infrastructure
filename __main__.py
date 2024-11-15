import base64
from typing import List
import pulumi
import pulumi_aws as aws
from mail import SimpleEmailService
import vpc
from tls import TransportLayerSecurity
from key import Key
import webapp
import rqlite
import redis
import reverse_proxy
import urllib.parse
import ipaddress
import os

if os.environ.get("AWS_PROFILE") is None or "oseh" not in os.environ.get("AWS_PROFILE"):
    raise Exception(
        "AWS_PROFILE must be set to an oseh profile to avoid accidentally using wrong AWS account"
    )

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
slack_oseh_bot_url = config.require_secret("slack_oseh_bot_url")
slack_oseh_classes_url = config.require_secret("slack_oseh_classes_url")
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
image_file_jwt_secret = config.require_secret("image_file_jwt_secret")
file_upload_jwt_secret = config.require_secret("file_upload_jwt_secret")
content_file_jwt_secret = config.require_secret("content_file_jwt_secret")
journey_jwt_secret = config.require_secret("journey_jwt_secret")
daily_event_jwt_secret = config.require_secret("daily_event_jwt_secret")
interactive_prompt_jwt_secret = config.require_secret("interactive_prompt_jwt_secret")
id_token_secret = config.require_secret("id_token_secret")
refresh_token_secret = config.require_secret("refresh_token_secret")
course_jwt_secret = config.require_secret("course_jwt_secret")
revenue_cat_secret_key = config.require_secret("revenue_cat_secret_key")
revenue_cat_stripe_public_key = config.require_secret("revenue_cat_stripe_public_key")
revenue_cat_google_play_public_key = config.require_secret(
    "revenue_cat_google_play_public_key"
)
revenue_cat_apple_public_key = config.require_secret("revenue_cat_apple_public_key")
stripe_secret_key = config.require_secret("stripe_secret_key")
stripe_public_key = config.require_secret("stripe_public_key")
stripe_price_id = config.require("stripe_price_id")
twilio_account_sid = config.require("twilio_account_sid")
twilio_auth_token = config.require_secret("twilio_auth_token")
twilio_phone_number = config.require("twilio_phone_number")
twilio_verify_service_sid = config.require("twilio_verify_service_sid")
twilio_message_service_sid = config.require("twilio_message_service_sid")
klaviyo_api_key = config.require_secret("klaviyo_api_key")
oseh_openai_api_key = config.require_secret("oseh_openai_api_key")
oseh_pexels_api_key = config.require_secret("oseh_pexels_api_key")
oseh_stability_ai_key = config.require_secret("oseh_stability_ai_key")
oseh_play_ht_user_id = config.require("oseh_play_ht_user_id")
oseh_play_ht_api_key = config.require_secret("oseh_play_ht_api_key")
oseh_reddit_client_id = config.require_secret("oseh_reddit_client_id")
oseh_reddit_client_secret = config.require_secret("oseh_reddit_client_secret")
oseh_mastodon_client_id = config.require_secret("oseh_mastodon_client_id")
oseh_mastodon_client_secret = config.require_secret("oseh_mastodon_client_secret")
oseh_mastodon_access_token = config.require_secret("oseh_mastodon_access_token")
oseh_direct_account_client_id = config.require_secret("oseh_direct_account_client_id")
oseh_direct_account_client_secret = config.require_secret(
    "oseh_direct_account_client_secret"
)
oseh_direct_account_redirect_path = config.require("oseh_direct_account_redirect_path")
oseh_direct_account_jwt_secret = config.require_secret("oseh_direct_account_jwt_secret")
oseh_csrf_jwt_secret_web = config.require_secret("oseh_csrf_jwt_secret_web")
oseh_csrf_jwt_secret_native = config.require_secret("oseh_csrf_jwt_secret_native")
oseh_expo_notification_access_token = config.require_secret(
    "oseh_expo_notification_access_token"
)
oseh_email_template_jwt_secret = config.require_secret("oseh_email_template_jwt_secret")
oseh_siwo_jwt_secret = config.require_secret("oseh_siwo_jwt_secret")
oseh_merge_jwt_secret = config.require_secret("oseh_merge_jwt_secret")
oseh_transcript_jwt_secret = config.require_secret("oseh_transcript_jwt_secret")
oseh_progress_jwt_secret = config.require_secret("oseh_progress_jwt_secret")
revenue_cat_v2_secret_key = config.require_secret("revenue_cat_v2_secret_key")
oseh_gender_api_key = config.require_secret("oseh_gender_api_key")
oseh_client_screen_jwt_secret = config.require_secret("oseh_client_screen_jwt_secret")
oseh_journal_jwt_secret = config.require_secret("oseh_journal_jwt_secret")
oseh_voice_note_jwt_secret = config.require_secret("oseh_voice_note_jwt_secret")

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

# There are two options for rqlite updates; either we can have rqlite recover
# from a node losing all its data, or we can have rqlite add a node and reap a
# node. Note that reaping a node is a very delicate process and this script does
# not reliably have it occur, so it's better to just have rqlite recover from
# one node losing all its data. To do this, keep rqlite_id_offset the same and go
# through the increment maintenance subnet idx until all nodes are replaced. Allow
# enough time for the node to recover before moving onto the next node
#
# After updating a node, connect to that node via the rqlite command line interface
# and run `.nodes` to ensure the nodes match what are expected. If the update does
# not work correctly, errors won't occur until the second node is updated, so it's
# important to manually check after the first node as there will not be any automatic
# alerts.
#
# READ ABOVE FIRST
main_rqlite = rqlite.RqliteCluster(
    "main_rqlite",
    main_vpc,
    id_offset=rqlite_id_offset,
    allow_maintenance_subnet_idx=None,
)

# There is only one option for redis; add/remove a node. THIS DOES NOT WORK ON
# THE MASTER INSTANCE. You must first identify the master instance (info
# replication), update this to specify the new master, then replace the
# instance. When you get to the point you need to replace the current master,
# force a failover first.
#
# VERY IMPORTANT: After replacing an instance, the old sentinels will not be
# reaped automatically. To reap them run `sentinel reset <master_name>` ON EACH
# INSTANCE. This command is dangerous; it will temporarily cause the cluster to
# be unavailable as all the sentinels forget about everyone, and is prone to
# split-head syndrome if there aren't exactly the correct number of sentinels
# alive. However, it's the only way to reap sentinels AFAIK, and failing to reap
# sentinels will eventually make the cluster unresponsive. The sentinels should
# detect each other within 3s otherwise something went wrong
#
# this can be used for monitoring the state of the cluster; note you aren't expecting
# anything to be sent. make sure you're not on the instance being replaced:
# save
# subscribe +reset-master +slave +failover-state-reconf-slaves +failover-detected +slave-reconf-sent +slave-reconf-inprog +slave-reconf-done +dup-sentinel -dup-sentinel +sentinel +sdown -sdown +odown -odown +new-epoch +try-failover +elected-leader +failover-state-select-slave no-good-slave selected-slave failover-state-send-slaveof-noone failover-end-for-timeout failover-end switch-master +tilt -tilt
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
    domain: str = remaining[3]
    s3_bucket_name: str = remaining[4]
    image_file_jwt_secret: str = remaining[5]
    file_upload_jwt_secret: str = remaining[6]
    content_file_jwt_secret: str = remaining[7]
    journey_jwt_secret: str = remaining[8]
    daily_event_jwt_secret: str = remaining[9]
    revenue_cat_secret_key: str = remaining[10]
    revenue_cat_stripe_public_key: str = remaining[11]
    stripe_secret_key: str = remaining[12]
    stripe_public_key: str = remaining[13]
    stripe_price_id: str = remaining[14]
    google_client_id: str = remaining[15]
    google_client_secret: str = remaining[16]
    apple_client_id: str = remaining[17]
    apple_key_id: str = remaining[18]
    apple_key: str = remaining[19]
    apple_app_id_team_id: str = remaining[20]
    id_token_secret: str = remaining[21]
    refresh_token_secret: str = remaining[22]
    twilio_account_sid: str = remaining[23]
    twilio_auth_token: str = remaining[24]
    twilio_phone_number: str = remaining[25]
    twilio_verify_service_sid: str = remaining[26]
    twilio_message_service_sid: str = remaining[27]
    slack_oseh_bot_url: str = remaining[28]
    interactive_prompt_jwt_secret: str = remaining[29]
    klaviyo_api_key: str = remaining[30]
    slack_oseh_classes_url: str = remaining[31]
    course_jwt_secret: str = remaining[32]
    oseh_openai_api_key: str = remaining[33]
    oseh_pexels_api_key: str = remaining[34]
    oseh_stability_ai_key: str = remaining[35]
    oseh_play_ht_user_id: str = remaining[36]
    oseh_play_ht_api_key: str = remaining[37]
    oseh_reddit_client_id: str = remaining[38]
    oseh_reddit_client_secret: str = remaining[39]
    oseh_mastodon_client_id: str = remaining[40]
    oseh_mastodon_client_secret: str = remaining[41]
    oseh_mastodon_access_token: str = remaining[42]
    oseh_direct_account_client_id: str = remaining[43]
    oseh_direct_account_client_secret: str = remaining[44]
    oseh_direct_account_redirect_path: str = remaining[45]
    oseh_direct_account_jwt_secret: str = remaining[46]
    oseh_csrf_jwt_secret_web: str = remaining[47]
    oseh_csrf_jwt_secret_native: str = remaining[48]
    oseh_expo_notification_access_token: str = remaining[49]
    oseh_email_template_jwt_secret: str = remaining[50]
    oseh_siwo_jwt_secret: str = remaining[51]
    oseh_build_subnet_id: str = remaining[52]
    oseh_build_ami_id: str = remaining[53]
    oseh_build_security_group_id: str = remaining[54]
    oseh_build_iam_instance_profile_name: str = remaining[55]
    oseh_merge_jwt_secret: str = remaining[56]
    oseh_transcript_jwt_secret: str = remaining[57]
    oseh_progress_jwt_secret: str = remaining[58]
    revenue_cat_v2_secret_key: str = remaining[59]
    revenue_cat_google_play_public_key: str = remaining[60]
    revenue_cat_apple_public_key: str = remaining[61]
    oseh_gender_api_key: str = remaining[62]
    oseh_client_screen_jwt_secret: str = remaining[63]
    oseh_backup_build_subnet_id: str = remaining[64]
    oseh_journal_jwt_secret: str = remaining[65]
    oseh_voice_note_jwt_secret: str = remaining[66]

    joined_rqlite_ips = ",".join(rqlite_ips)
    joined_redis_ips = ",".join(redis_ips)

    domain_no_trailing_dot = domain.rstrip(".")

    apple_key_base64 = base64.b64encode(apple_key.encode("utf-8")).decode("utf-8")

    return "\n".join(
        [
            f'export RQLITE_IPS="{joined_rqlite_ips}"',
            f'export REDIS_IPS="{joined_redis_ips}"',
            f'export DEPLOYMENT_SECRET="{deploy_secret}"',
            f'export SLACK_WEB_ERRORS_URL="{web_errors_url}"',
            f'export SLACK_OPS_URL="{ops_url}"',
            f'export ROOT_FRONTEND_URL="https://{domain_no_trailing_dot}"',
            f'export ROOT_BACKEND_URL="https://{domain_no_trailing_dot}"',
            f'export ROOT_FRONTEND_SSR_URL="https://{domain_no_trailing_dot}"',
            f'export ROOT_WEBSOCKET_URL="wss://{domain_no_trailing_dot}"',
            f'export ROOT_EMAIL_TEMPLATE_URL="https://{domain_no_trailing_dot}"',
            f'export OSEH_S3_BUCKET_NAME="{s3_bucket_name}"',
            f'export OSEH_IMAGE_FILE_JWT_SECRET="{image_file_jwt_secret}"',
            f'export OSEH_FILE_UPLOAD_JWT_SECRET="{file_upload_jwt_secret}"',
            f'export OSEH_CONTENT_FILE_JWT_SECRET="{content_file_jwt_secret}"',
            f'export OSEH_JOURNEY_JWT_SECRET="{journey_jwt_secret}"',
            f'export OSEH_DAILY_EVENT_JWT_SECRET="{daily_event_jwt_secret}"',
            f'export OSEH_INTERACTIVE_PROMPT_JWT_SECRET="{interactive_prompt_jwt_secret}"',
            f'export OSEH_SIWO_JWT_SECRET="{oseh_siwo_jwt_secret}"',
            f'export OSEH_REVENUE_CAT_SECRET_KEY="{revenue_cat_secret_key}"',
            f'export OSEH_REVENUE_CAT_V2_SECRET_KEY="{revenue_cat_v2_secret_key}"',
            f'export OSEH_REVENUE_CAT_STRIPE_PUBLIC_KEY="{revenue_cat_stripe_public_key}"',
            f'export OSEH_REVENUE_CAT_GOOGLE_PLAY_PUBLIC_KEY="{revenue_cat_google_play_public_key}"',
            f'export OSEH_REVENUE_CAT_APPLE_PUBLIC_KEY="{revenue_cat_apple_public_key}"',
            f'export OSEH_STRIPE_SECRET_KEY="{stripe_secret_key}"',
            f'export OSEH_STRIPE_PUBLIC_KEY="{stripe_public_key}"',
            f'export OSEH_STRIPE_PRICE_ID="{stripe_price_id}"',
            f'export OSEH_GOOGLE_CLIENT_ID="{google_client_id}"',
            f'export OSEH_GOOGLE_CLIENT_SECRET="{google_client_secret}"',
            f'export OSEH_APPLE_CLIENT_ID="{apple_client_id}"',
            f'export OSEH_APPLE_KEY_ID="{apple_key_id}"',
            f'export OSEH_APPLE_KEY_BASE64="{apple_key_base64}"',
            f'export OSEH_APPLE_APP_ID_TEAM_ID="{apple_app_id_team_id}"',
            f'export OSEH_ID_TOKEN_SECRET="{id_token_secret}"',
            f'export OSEH_REFRESH_TOKEN_SECRET="{refresh_token_secret}"',
            f'export OSEH_TWILIO_ACCOUNT_SID="{twilio_account_sid}"',
            f'export OSEH_TWILIO_AUTH_TOKEN="{twilio_auth_token}"',
            f'export OSEH_TWILIO_PHONE_NUMBER="{twilio_phone_number}"',
            f'export OSEH_TWILIO_VERIFY_SERVICE_SID="{twilio_verify_service_sid}"',
            f'export OSEH_TWILIO_MESSAGE_SERVICE_SID="{twilio_message_service_sid}"',
            f'export OSEH_KLAVIYO_API_KEY="{klaviyo_api_key}"',
            f'export SLACK_OSEH_BOT_URL="{slack_oseh_bot_url}"',
            f'export SLACK_OSEH_CLASSES_URL="{slack_oseh_classes_url}"',
            f'export OSEH_COURSE_JWT_SECRET="{course_jwt_secret}"',
            f'export OSEH_OPENAI_API_KEY="{oseh_openai_api_key}"',
            f'export OSEH_PEXELS_API_KEY="{oseh_pexels_api_key}"',
            f'export OSEH_STABILITY_AI_KEY="{oseh_stability_ai_key}"',
            f'export OSEH_PLAY_HT_USER_ID="{oseh_play_ht_user_id}"',
            f'export OSEH_PLAY_HT_SECRET_KEY="{oseh_play_ht_api_key}"',
            f'export OSEH_REDDIT_CLIENT_ID="{oseh_reddit_client_id}"',
            f'export OSEH_REDDIT_CLIENT_SECRET="{oseh_reddit_client_secret}"',
            f'export OSEH_MASTODON_CLIENT_ID="{oseh_mastodon_client_id}"',
            f'export OSEH_MASTODON_CLIENT_SECRET="{oseh_mastodon_client_secret}"',
            f'export OSEH_MASTODON_ACCESS_TOKEN="{oseh_mastodon_access_token}"',
            f'export OSEH_DIRECT_ACCOUNT_CLIENT_ID="{oseh_direct_account_client_id}"',
            f'export OSEH_DIRECT_ACCOUNT_CLIENT_SECRET="{oseh_direct_account_client_secret}"',
            f'export OSEH_DIRECT_ACCOUNT_REDIRECT_PATH="{oseh_direct_account_redirect_path}"',
            f'export OSEH_DIRECT_ACCOUNT_JWT_SECRET="{oseh_direct_account_jwt_secret}"',
            f'export OSEH_CSRF_JWT_SECRET_WEB="{oseh_csrf_jwt_secret_web}"',
            f'export OSEH_CSRF_JWT_SECRET_NATIVE="{oseh_csrf_jwt_secret_native}"',
            f'export OSEH_EXPO_NOTIFICATION_ACCESS_TOKEN="{oseh_expo_notification_access_token}"',
            f'export OSEH_EMAIL_TEMPLATE_JWT_SECRET="{oseh_email_template_jwt_secret}"',
            f'export OSEH_BUILD_SUBNET_ID="{oseh_build_subnet_id}"',
            f'export OSEH_BACKUP_BUILD_SUBNET_ID="{oseh_backup_build_subnet_id}"',
            f'export OSEH_BUILD_AMI_ID="{oseh_build_ami_id}"',
            f'export OSEH_BUILD_SECURITY_GROUP_ID="{oseh_build_security_group_id}"',
            f'export OSEH_BUILD_IAM_INSTANCE_PROFILE_NAME="{oseh_build_iam_instance_profile_name}"',
            f'export OSEH_MERGE_JWT_SECRET="{oseh_merge_jwt_secret}"',
            f'export OSEH_TRANSCRIPT_JWT_SECRET="{oseh_transcript_jwt_secret}"',
            f'export OSEH_PROGRESS_JWT_SECRET="{oseh_progress_jwt_secret}"',
            f'export OSEH_GENDER_API_KEY="{oseh_gender_api_key}"',
            f'export OSEH_CLIENT_SCREEN_JWT_SECRET="{oseh_client_screen_jwt_secret}"',
            f'export OSEH_JOURNAL_JWT_SECRET="{oseh_journal_jwt_secret}"',
            f'export OSEH_VOICE_NOTE_JWT_SECRET="{oseh_voice_note_jwt_secret}"',
            f"export ENVIRONMENT=production",
            f"export AWS_DEFAULT_REGION=us-west-2",
        ]
    )


def make_low_resource_jobs_configuration(args) -> str:
    standard_configuration = args[0]
    return "\n".join([standard_configuration, "export OSEH_JOB_CATEGORIES=2"])


def make_high_resource_jobs_configuration(args) -> str:
    standard_configuration = args[0]
    return "\n".join([standard_configuration, "export OSEH_JOB_CATEGORIES=1,2"])


bucket = aws.s3.Bucket(
    "bucket", acl="private", tags={"Name": "oseh"}, force_destroy=True
)
backend_rest = webapp.Webapp(
    "backend_rest",
    main_vpc,
    "meetoseh/backend",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter + 1,
    num_subnets=2,
    bleeding_ami=True,  # python version 3.9+
    instance_type="t4g.small",  # i think it's running out of memory on the nano occassionally
    volume_size=16,  # disk caching for the audio/image files
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
    bleeding_ami=True,  # python version 3.9+
)
frontend = webapp.Webapp(
    "frontend",
    main_vpc,
    "meetoseh/frontend-web",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    instance_type="t4g.nano",
    bleeding_ami=True,
    webapp_counter=webapp_counter,
)
frontend_ssr = webapp.Webapp(
    "frontend-ssr",
    main_vpc,
    "meetoseh/frontend-ssr-web",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    instance_type="t4g.small",
    bleeding_ami=True,  # required for node 18
    webapp_counter=webapp_counter,
)
high_resource_jobs = webapp.Webapp(
    "high_resource_jobs",
    main_vpc,
    "meetoseh/jobs",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter + 1,
    num_instances_per_subnet=1,
    instance_type="m6g.large",  # needs at least 3 GiB memory; c7g.2xlarge does a ~2m video in 47m
    bleeding_ami=True,  # required for pympanim
    volume_size=128,  # video processing requires a lot of space
)
low_resource_jobs = webapp.Webapp(
    "low_resource_jobs",
    main_vpc,
    "meetoseh/jobs",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter,
    instance_type="t4g.small",  # ffmpeg memory >1.3gb to install
    bleeding_ami=True,  # required for pympanim
)
backend_email_templates = webapp.Webapp(
    "email-templates",
    main_vpc,
    "meetoseh/email-templates",
    github_username,
    github_pat,
    main_vpc.bastion.public_ip,
    key,
    webapp_counter=webapp_counter + 1,
    instance_type="t4g.small",  # node requires 1.2gb ram to build :/
    bleeding_ami=True,  # required for node 18
)
main_reverse_proxy = reverse_proxy.ReverseProxy(
    "main_reverse_proxy",
    main_vpc,
    key,
    backend_rest,
    backend_ws,
    backend_email_templates,
    frontend,
    frontend_ssr,
)
tls = TransportLayerSecurity(
    "tls",
    domain,
    main_vpc.vpc.id,
    [subnet.id for subnet in main_vpc.public_subnets],
    [instance.id for instance in main_reverse_proxy.reverse_proxies],
)

with open(apple_key_file, "r") as f:
    apple_private_key = f.read()

standard_configuration = pulumi.Output.all(
    *[instance.private_ip for instance in main_rqlite.instances],
    *[instance.private_ip for instance in main_redis.instances],
    deployment_secret,
    slack_web_errors_url,
    slack_ops_url,
    domain,
    bucket.bucket,
    image_file_jwt_secret,
    file_upload_jwt_secret,
    content_file_jwt_secret,
    journey_jwt_secret,
    daily_event_jwt_secret,
    revenue_cat_secret_key,
    revenue_cat_stripe_public_key,
    stripe_secret_key,
    stripe_public_key,
    stripe_price_id,
    google_oidc_client_id,
    google_oidc_client_secret,
    apple_services_id,
    apple_key_id,
    apple_private_key,
    apple_app_id_team_id,
    id_token_secret,
    refresh_token_secret,
    twilio_account_sid,
    twilio_auth_token,
    twilio_phone_number,
    twilio_verify_service_sid,
    twilio_message_service_sid,
    slack_oseh_bot_url,
    interactive_prompt_jwt_secret,
    klaviyo_api_key,
    slack_oseh_classes_url,
    course_jwt_secret,
    oseh_openai_api_key,
    oseh_pexels_api_key,
    oseh_stability_ai_key,
    oseh_play_ht_user_id,
    oseh_play_ht_api_key,
    oseh_reddit_client_id,
    oseh_reddit_client_secret,
    oseh_mastodon_client_id,
    oseh_mastodon_client_secret,
    oseh_mastodon_access_token,
    oseh_direct_account_client_id,
    oseh_direct_account_client_secret,
    oseh_direct_account_redirect_path,
    oseh_direct_account_jwt_secret,
    oseh_csrf_jwt_secret_web,
    oseh_csrf_jwt_secret_native,
    oseh_expo_notification_access_token,
    oseh_email_template_jwt_secret,
    oseh_siwo_jwt_secret,
    main_vpc.private_subnets[0].id,
    main_vpc.amazon_linux_bleeding_arm64.id,
    frontend.security_group.id,
    main_vpc.standard_instance_profile.name,
    oseh_merge_jwt_secret,
    oseh_transcript_jwt_secret,
    oseh_progress_jwt_secret,
    revenue_cat_v2_secret_key,
    revenue_cat_google_play_public_key,
    revenue_cat_apple_public_key,
    oseh_gender_api_key,
    oseh_client_screen_jwt_secret,
    main_vpc.private_subnets[1].id,
    oseh_journal_jwt_secret,
    oseh_voice_note_jwt_secret,
).apply(make_standard_webapp_configuration)
high_resource_config = pulumi.Output.all(standard_configuration).apply(
    make_high_resource_jobs_configuration
)
low_resource_config = pulumi.Output.all(standard_configuration).apply(
    make_low_resource_jobs_configuration
)

backend_rest.perform_remote_executions(standard_configuration)
backend_ws.perform_remote_executions(standard_configuration)
backend_email_templates.perform_remote_executions(standard_configuration)
frontend.perform_remote_executions(standard_configuration)
frontend_ssr.perform_remote_executions(standard_configuration)
high_resource_jobs.perform_remote_executions(high_resource_config)
low_resource_jobs.perform_remote_executions(low_resource_config)

mail = SimpleEmailService(
    "mail",
    tls,
    "/api/1/emails/sns-mail",
    [
        *(itm for row in backend_rest.remote_executions_by_subnet for itm in row),
        *(itm for itm in main_reverse_proxy.reverse_proxy_installs),
        tls.lb_tls_listener,
    ],
)

pulumi.export(
    "example reverse proxy ip", main_reverse_proxy.reverse_proxies[0].private_ip
)
pulumi.export("example frontend-web ip", frontend.instances_by_subnet[0][0].private_ip)
pulumi.export(
    "example frontend-ssr-web ip", frontend_ssr.instances_by_subnet[0][0].private_ip
)
pulumi.export("example backend ip", backend_rest.instances_by_subnet[0][0].private_ip)
pulumi.export("example websocket ip", backend_ws.instances_by_subnet[0][0].private_ip)
pulumi.export(
    "example email template ip",
    backend_email_templates.instances_by_subnet[0][0].private_ip,
)
pulumi.export(
    "example low resource jobs ip",
    low_resource_jobs.instances_by_subnet[0][0].private_ip,
)
pulumi.export(
    "example high resource jobs ip",
    high_resource_jobs.instances_by_subnet[0][0].private_ip,
)
pulumi.export("example rqlite ip", main_rqlite.instances[0].private_ip)
pulumi.export(
    "all rqlite ips",
    pulumi.Output.all(instance.private_ip for instance in main_rqlite.instances),
)
pulumi.export("redis ip 0", main_redis.instances[0].private_ip)
pulumi.export("redis ip 1", main_redis.instances[1].private_ip)
pulumi.export("redis ip 2", main_redis.instances[2].private_ip)
