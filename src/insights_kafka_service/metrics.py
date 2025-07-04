import time
import dateutil.parser as dateparser
from datetime import datetime, timezone
from operator import itemgetter
from prometheus_client import Counter, Histogram
from prometheus_client import start_http_server
from prometheus_client.metrics import INF
from insights_messaging.watchers import ConsumerWatcher, EngineWatcher
import os

# Histograms
message_process_time = Histogram("insights_message_process_time_seconds", "Total time to process an archive", unit='seconds')
engine_extraction_time = Histogram("insights_engine_extraction_time_seconds", "Total time to extract the archive", unit='seconds')
engine_analysis_time = Histogram("insights_engine_analysis_time_seconds", "Total time to analyze an archive", unit='seconds')
engine_failed_analysis_time = Histogram("insights_engine_failed_analysis_time_seconds", "Total seconds it took to process an archive that failed", unit='seconds')
engine_total_time = Histogram("insights_engine_total_time_seconds", "Total time it took for the engine to completely process an archive", unit='seconds')

# latency buckets range from 0.05 to 104857.6 seconds (~29 hours)
latency_buckets = [0.05 * (2**i) for i in range(0, 22)] + [INF]
engine_ingress_latency = Histogram("insights_engine_ingress_latency_seconds", "Total duration from ingress to beginning of archive processing", unit='seconds', buckets=latency_buckets)

# Counters
message_failure_count = Counter("insights_engine_message_failure_count", "Total of failed messages")
message_success_count = Counter("insights_engine_message_success_count", "Total of successful messages")
message_processed = Counter("insights_engine_message_processed_count", "Total messages sent through the consumer")
message_received = Counter("insights_archive_received_count", "Total archives received the consumer")
# To count kafka msgs for redhat internal accounts, this will show in canary dashboard to monitor new release
internal_message_received = Counter("internal_insights_archive_received_count", "Total internal archives received the consumer")
internal_message_success_count = Counter("internal_insights_engine_message_success_count", "Total of internal successful messages")
internal_message_failure_count = Counter("internal_insights_engine_message_failure_count", "Total of internal failed messages")
internal_message_processed = Counter("internal_insights_engine_message_processed_count", "Total internal messages sent through the consumer")

engine_archive_received = Counter("insights_engine_received_archive_count", "Total archives received by engine")
engine_process_success = Counter("insights_engine_process_success_count", "Total archive successfully analyzed")
engine_process_failure = Counter("insights_engine_total_process_failures_count", "Total archives that failed to be analyzed")
engine_process_completed = Counter("insights_engine_process_completed_count", "Total archives completely processed and analyzed by the engine")

CLOWDER_ENABLED = os.environ.get('CLOWDER_ENABLED', False)

REDHAT_INTERNAL_ACCOUNTS = [
    # JIRA:
    #   - https://issues.redhat.com/browse/ESSNTL-4624
    #   - https://issues.redhat.com/browse/ESSNTL-4774
    #   - https://issues.redhat.com/browse/ESSNTL-4859
    '10902428', '1092491', '11494071', '1212729', '1460290', '1615407',
    '477931', '5243891', '5348764', '5355424', '5357088', '5378341',
    '540155', '5535485', '5542693', '5594202', '5619559', '5705820',
    '5910538', '6038690', '6076664', '6115179', '6144213',
    '6181901', '6212377', '6212943', '6217386', '6217387', '6217388',
    '6217410', '6219291', '6219292', '6229994', '6229996', '6316938',
    '6341559', '6407009', '6951286', '7030388', '7121658', '7146748',
    '824399', '901532', '901578', '9842175', '7453185',
]


def parse_timestamp(s):
    """
    Use dateutil.parser to parse the date and return None on any errors.
    """
    try:
        return dateparser.parse(s)
    # this is dateutil.parser._parser.ParserError, but we don't need to be that
    # specific
    except Exception:
        pass


class Watcher(ConsumerWatcher):
    def __init__(self, port=8080):
        if CLOWDER_ENABLED:
            from app_common_python import LoadedConfig
            port = LoadedConfig.metricsPort
        start_http_server(port)
        self.start_time = None

    def get_top_times(self, broker):
        return sorted(broker.exec_times.items(), key=itemgetter(1))[-25:]

    def on_recv(self, msg):
        message_received.inc()
        if msg.platform_metadata.account in REDHAT_INTERNAL_ACCOUNTS:
            internal_message_received.inc()
        self.start_time = time.time()

        ingress_time = parse_timestamp(msg.platform_metadata.timestamp)
        if ingress_time is not None:
            now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
            latency = (now_utc - ingress_time).total_seconds()
            engine_ingress_latency.observe(latency)

    def on_consumer_success(self, input_msg, broker, results):
        message_success_count.inc()
        if input_msg.platform_metadata.account in REDHAT_INTERNAL_ACCOUNTS:
            internal_message_success_count.inc()

    def on_consumer_failure(self, input_msg, exception):
        message_failure_count.inc()
        if input_msg.platform_metadata.account in REDHAT_INTERNAL_ACCOUNTS:
            internal_message_failure_count.inc()

    def on_consumer_complete(self, input_msg):
        message_processed.inc()
        if input_msg.platform_metadata.account in REDHAT_INTERNAL_ACCOUNTS:
            internal_message_processed.inc()
        endtime = time.time() - self.start_time
        message_process_time.observe(endtime)


class Engine(EngineWatcher):
    def pre_extract(self, broker, path):
        engine_archive_received.inc()
        self.start_time = time.time()

    def on_extract(self, ctx, broker, extraction):
        self.extract_time = time.time()
        engine_extraction_time.observe(self.extract_time - self.start_time)

    def on_engine_success(self, broker, result):
        engine_process_success.inc()
        analysis = time.time() - self.extract_time
        engine_analysis_time.observe(analysis)

    def on_engine_failure(self, broker, ex):
        engine_process_failure.inc()
        analysis = time.time() - self.extract_time
        engine_failed_analysis_time.observe(analysis)

    def on_engine_complete(self, broker):
        engine_process_completed.inc()
        total_time = time.time() - self.start_time
        engine_total_time.observe(total_time)
