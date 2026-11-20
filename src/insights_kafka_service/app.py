#!/usr/bin/env python
import argparse
from insights_messaging.appbuilder import AppBuilder


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("config", help="Application Configuration.")
    return p.parse_args()


def main():
    import os
    from insights_kafka_service.telemetry import init_otel, instrument_outbound_http

    init_otel(
        service_name="insights-engine",
        service_version=os.getenv("IMAGE_TAG", "unknown"),
    )
    instrument_outbound_http()

    args = parse_args()
    with open(args.config) as f:
        AppBuilder(f.read()).build_app().run()


if __name__ == "__main__":
    main()
