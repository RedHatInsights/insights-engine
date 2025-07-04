import os
import socket
import watchtower

CLOWDER_ENABLED = os.environ.get('CLOWDER_ENABLED', False)


def clowder_config():
    import app_common_python

    cfg = app_common_python.LoadedConfig

    if cfg.logging:
        cw = cfg.logging.cloudwatch
        return cw.accessKeyId, cw.secretAccessKey, cw.region, cw.logGroup, False
    else:
        return None, None, None, None, None


def non_clowder_config():
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", None)
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", None)
    aws_region_name = os.getenv("AWS_REGION_NAME", None)
    aws_log_group = os.getenv("AWS_LOG_GROUP", "platform")
    create_log_group = str(os.getenv("AWS_CREATE_LOG_GROUP")).lower() == "true"
    return aws_access_key_id, aws_secret_access_key, aws_region_name, aws_log_group, create_log_group


def configure_logging():
    def inner(log_config):
        if os.environ.get("CLOWDER_ENABLED", "").lower() == "true":
            f = clowder_config
        else:
            f = non_clowder_config

        aws_access_key_id, aws_secret_access_key, aws_region_name, aws_log_group, create_log_group = f()

        if all((aws_access_key_id, aws_secret_access_key, aws_region_name)):
            import boto3

            i_boto3_client = boto3.client(aws_access_key_id=aws_access_key_id,
                                    aws_secret_access_key=aws_secret_access_key,
                                    region_name=aws_region_name,
                                    service_name="logs")

            # configure logging handler to use watchtower
            log_config["handlers"]["watchtower"] = {
                "()": watchtower.CloudWatchLogHandler,
                "boto3_client": i_boto3_client,
                "log_group_name": aws_log_group,
                "stream_name": socket.gethostname(),
                "create_log_group": create_log_group,
            }

            if log_config["formatters"].get("logstash"):
                log_config["handlers"]["watchtower"]["formatter"] = "logstash"

            log_config["loggers"][""]["handlers"].append("watchtower")

        return log_config
    return inner
