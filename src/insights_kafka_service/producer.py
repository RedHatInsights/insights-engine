import json
import logging
import os

import attr
from confluent_kafka import Producer

from insights_messaging.publishers import Publisher

logger = logging.getLogger(__name__)
CLOWDER_ENABLED = os.environ.get("CLOWDER_ENABLED", False)


class InsightsKafkaProducer(Publisher):
    def __init__(self, **kwargs):
        if CLOWDER_ENABLED:
            from app_common_python import LoadedConfig, KafkaTopics

            KAFKA_BROKER = LoadedConfig.kafka.brokers[0]
            kwargs.update(
                {
                    "bootstrap_servers": [
                        f"{KAFKA_BROKER.hostname}:{KAFKA_BROKER.port}"
                    ],
                    "topic": KafkaTopics["platform.engine.results"].name,
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

        bootstrap_servers = kwargs.pop("bootstrap_servers")
        self.topic = kwargs.pop("topic")
        self.producer = Producer(
            {"bootstrap.servers": ",".join(bootstrap_servers), **kwargs}
        )

    def delivery_report(self, err, msg):
        if err is not None:
            logger.error(f"Message failed delivery: {err}\n{msg}")
        else:
            logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")

    def publish(self, input_msg, response):
        response = json.loads(response)
        for k in list(response.keys()):
            if k in ["skips", "packages"]:
                del response[k]
        v = json.dumps({"input": attr.asdict(input_msg), "results": response})
        self.producer.produce(self.topic, v.encode("utf-8"), callback=self.delivery_report)
        # poll here to clean up the delivery report queue. This is inexpensive and will keep
        # the queue clean
        self.producer.poll(0)

    def error(self, input_msg, ex):
        logger.exception(
            "failure in process()", exc_info=ex, extra=attr.asdict(input_msg)
        )
