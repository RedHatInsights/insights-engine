from setuptools import find_packages, setup

requirements = [
    "attrs==19.3.0",
    "urllib3==1.26.19",
    "boto3==1.35.16",
    "botocore==1.35.16",
    "s3fs==0.6.0",
    "confluent-kafka==2.9.0",
    "logstash-formatter==0.5.17",
    "prometheus-client==0.21.1",
    "requests==2.32.3",
    "watchtower==3.3.1",
    "app-common-python==0.2.7",
    "insights-core-messaging @ git+https://github.com/RedHatInsights/insights-core-messaging@1.2.19"
]


# Update the version of insights-core and relevant plugins in
# "core_and_plugins.txt" file.
with open("core_and_plugins.txt", "r") as crf:
    requirements.extend(line.strip() for line in crf)


setup(
    name="insights-core-engine",
    version="0.1",
    url="https://github.com/redhatinsights/insights-core-engine",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=requirements,
    extras_require={"test": ["pytest>=5.4.1", "flake8>=3.7.9"], "redis": ["redis"]},
    entry_points={
        "console_scripts": ["insights-core-engine = insights_kafka_service.app:main"]
    },
)
