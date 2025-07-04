import json
import logging
import os

from insights import dr
from insights_messaging.consumers.kafka import Kafka

from . import PayloadMeta

logger = logging.getLogger(__name__)

CLOWDER_ENABLED = os.environ.get("CLOWDER_ENABLED", False)


def get_redis(cfg):
    import redis

    if CLOWDER_ENABLED:
        from app_common_python import LoadedConfig

        hostname = LoadedConfig.inMemoryDb.hostname
        password = LoadedConfig.inMemoryDb.password
    else:
        hostname = (
            cfg.get("hostname")
            if cfg.get("hostname") is not None
            else os.environ.get("REDIS_HOSTNAME")
        )
        password = (
            cfg.get("password")
            if cfg.get("password") is not None
            else os.environ.get("REDIS_PASSWORD")
        )

    # use ssl if the password is present - since the password is only present in the config if ssl is enabled in app-interface
    ssl = password is not None and password != ""

    return redis.Redis(
        host=hostname,
        port=LoadedConfig.inMemoryDb.port,
        password=password,
        ssl=ssl,
        decode_responses=cfg.get("decode_responses"),
    )


class InsightsKafkaConsumer(Kafka):
    def __init__(self, *args, **kwargs):
        logger.debug('InsightsKafkaConsumer starting up, args=%s, kwargs=%s', args, kwargs)
        if CLOWDER_ENABLED:
            from app_common_python import LoadedConfig, KafkaTopics, KafkaServers

            KAFKA_BROKER = LoadedConfig.kafka.brokers[0]
            if os.environ.get("EVENTS_TOPIC"):
                events_topic_requested_name = os.environ.get("EVENTS_TOPIC")
            else:
                events_topic_requested_name = "platform.inventory.events"

            kwargs.update(
                {
                    "bootstrap_servers": KafkaServers,
                    "incoming_topic": KafkaTopics[events_topic_requested_name].name,
                }
            )

            if KAFKA_BROKER.sasl:
                kwargs.update(
                    {
                        "sasl.mechanism": KAFKA_BROKER.sasl.saslMechanism,
                        "security.protocol": KAFKA_BROKER.sasl.securityProtocol.lower(),
                        "sasl.username": KAFKA_BROKER.sasl.username,
                        "sasl.password": KAFKA_BROKER.sasl.password,
                    }
                )

            if KAFKA_BROKER.cacert:
                with open("/tmp/cacert.pem", "w") as f:
                    f.write(KAFKA_BROKER.cacert)
                kwargs["ssl.ca.location"] = "/tmp/cacert.pem"
        # group.instance.id: OffsetCommit failed: Broker: Static consumer fenced by other consumer with same group.instance.id
        kwargs["group.instance.id"] = os.environ.get("HOSTNAME")
        self.services = kwargs.pop("services")
        super().__init__(*args, **kwargs)
        self.types = ("created", "updated")
        self.redis = get_redis(kwargs["redis"]) if "redis" in kwargs else None
        logger.info('InsightsKafkaConsumer services=%s, redis=%s', self.services, self.redis)

    def deserialize(self, bytes_):
        return json.loads(bytes_.decode("utf-8"))

    def handles(self, input_msg):
        input_type = input_msg["type"]  # missing type means malformed input
        meta = input_msg.get("platform_metadata")
        if meta is not None:
            if meta.get("service"):
                return input_type in self.types and meta["service"] in self.services
        return False

    def _handle_retries(self, request_id):
        """
        If redis is configured, use it to track requests by request_id. If a
        request_id has been seen 2 or more times, previous attempts to handle
        it have failed catastrophically (probably OOMKilled), and we should
        stop trying.
        """
        if self.redis:
            current = self.redis.get(request_id)
            if current:
                current = int(current)
            else:
                current = 0
            if current >= 2:
                logger.warn(
                    'Have already processed request %s %d times, aborting...',
                    request_id, current
                )
                raise Exception("For request id {0}, the kafka message process attempts exceeded in insights engine service".format(request_id))
            else:
                if current > 0:
                    logger.warn(
                        'Have already processed request %s %d times, retrying...',
                        request_id, current
                    )
                current += 1
                self.redis.set(request_id, current, ex=3600)

    def process(self, raw_input_msg):
        # Since we use a very restrictive class to deserialize the JSON
        # we perform that portion here, before passing to the process()
        # in insights-core-messaging
        Payload = PayloadMeta.from_json(raw_input_msg)
        request_id = Payload.platform_metadata.request_id
        self._handle_retries(request_id)
        logger.info(
            'Processing request id %s timestamp %s',
            request_id, Payload.platform_metadata.timestamp
        )
        super().process(Payload)
        logger.info('Completed processing request id %s', request_id)

    def get_url(self, input_msg):
        return input_msg.platform_metadata.url

    def create_broker(self, input_msg):
        broker = dr.Broker()
        broker[PayloadMeta] = input_msg.platform_metadata
        return broker
