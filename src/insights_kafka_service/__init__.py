
import json
import logging
import os
from base64 import b64decode

import attr

logger = logging.getLogger(__name__)

HOSTNAME = os.getenv("HOSTNAME", None)


def ensure_cls(cl):
    """If the attribute is an instance of cls, pass, else try constructing."""
    def converter(val):
        if isinstance(val, cl):
            return val
        else:
            return cl(**val)
    return converter


def prune_json(doc):
    profile_keys = ["os_release", "satellite_managed", "satellite_id", "tags",
                    "os_kernel_version", "os_kernel_release", "operating_system"]
    if doc["host"].get("system_profile"):
        for k in list(doc["host"]["system_profile"].keys()):
            if k not in profile_keys:
                del doc["host"]["system_profile"][k]

    return doc


@attr.s
class PlatformMeta(object):
    account = attr.ib(default=None)
    b64_identity = attr.ib(default=None)
    category = attr.ib(default=None)
    content_type = attr.ib(default=None)
    custom_metadata = attr.ib(factory=dict)
    elapsed_time = attr.ib(default=None)
    extras = attr.ib(factory=dict)
    host = attr.ib(factory=dict)
    id = attr.ib(default=None)
    is_runtimes = attr.ib(default=False)
    metadata = attr.ib(factory=dict)
    org_id = attr.ib(default=None)
    payload_id = attr.ib(default=None)
    principal = attr.ib(default=None)
    request_id = attr.ib(default="-1")
    satellite_managed = attr.ib(default=None)
    service = attr.ib(default=None)
    size = attr.ib(default=None)
    timestamp = attr.ib(default=None)
    url = attr.ib(default=None)
    validation = attr.ib(default=None)
    test = attr.ib(default=None)
    is_ros = attr.ib(default=None)
    is_ros_v2 = attr.ib(default=None)
    is_pcp_raw_data_collected = attr.ib(default=None)


@attr.s
class PayloadMeta(object):
    platform_metadata = attr.ib(converter=ensure_cls(PlatformMeta))
    metadata = attr.ib(default=None)
    host = attr.ib(factory=dict)
    type = attr.ib(default=None)
    timestamp = attr.ib(default=None)

    @classmethod
    def from_json(cls, content):
        try:
            doc = prune_json(content)
            doc = {a.name: doc.get(a.name, a.default) for a in attr.fields(PayloadMeta)}
            logger.info("Received Message - request_id: %s - inventory_id: %s", doc["platform_metadata"].get("request_id"), doc["host"]["id"])
            return cls(**doc)
        except Exception:
            logger.exception("failed to deserialize message: %s", doc)
            raise

    @property
    def identity(self):
        return json.loads(b64decode(self.platform_metadata.b64_identity))
