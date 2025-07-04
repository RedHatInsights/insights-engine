#!/usr/bin/env python
import datetime
import json
import logging
import os

from confluent_kafka import Producer

from insights_messaging.watchers import ConsumerWatcher
from insights_messaging.publishers import Publisher

logger = logging.getLogger(__name__)

CLOWDER_ENABLED = os.environ.get("CLOWDER_ENABLED", False)


class PayloadTracker(Publisher):
    def __init__(self, bootstrap_servers, topic, service_name, **kwargs):
        self.producer = Producer(
            {"bootstrap.servers": ",".join(bootstrap_servers), **kwargs}
        )
        self.topic = topic
        self.service = service_name

    def send_status(self, watcher_msg, status, status_msg):
        request_id = watcher_msg.platform_metadata.request_id
        account = watcher_msg.platform_metadata.account
        inventory_id = watcher_msg.host["id"]
        system_id = watcher_msg.host["insights_id"]
        payload_status_json = {
            "service": self.service,
            "account": account,
            "request_id": request_id,
            "inventory_id": inventory_id,
            "system_id": system_id,
            "status": status,
            "status_msg": status_msg,
            "date": str(datetime.datetime.now().isoformat()),
        }
        payload_status = json.dumps(payload_status_json)
        self.producer.produce(self.topic, payload_status.encode("utf-8"))


class Watcher(ConsumerWatcher):
    def __init__(self, *args, **kwargs):
        if CLOWDER_ENABLED:
            from app_common_python import LoadedConfig, KafkaTopics

            KAFKA_BROKER = LoadedConfig.kafka.brokers[0]

            kwargs.update(
                {
                    "bootstrap_servers": [
                        f"{KAFKA_BROKER.hostname}:{KAFKA_BROKER.port}"
                    ],
                    "topic": KafkaTopics["platform.payload-status"].name,
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
        topic = kwargs.pop("topic")
        service_name = kwargs.pop("service_name")
        self.tracker = PayloadTracker(bootstrap_servers, topic, service_name, **kwargs)

    def on_recv(self, msg):
        status = "received"
        status_msg = "Engine request received"
        self.tracker.send_status(msg, status, status_msg)

    def on_consumer_success(self, input_msg, broker, results):
        status = "success"
        status_msg = "Engine request success"
        self.tracker.send_status(input_msg, status, status_msg)

    def on_consumer_failure(self, input_msg, exception):
        status = "error"
        status_msg = "Engine request error:\n" + exception
        self.tracker.send_status(input_msg, status, status_msg)
