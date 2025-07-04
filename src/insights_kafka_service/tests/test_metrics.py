from insights_kafka_service import metrics


def test_parse_timestamp():
    # this is a timestamp formatted according to ingress' kafka message metadata envelope
    raw = "2020-03-05T16:57:25.816427745Z"
    assert metrics.parse_timestamp(raw) is not None
    assert metrics.parse_timestamp("garbage") is None
