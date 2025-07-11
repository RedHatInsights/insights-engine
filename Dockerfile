FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

USER root
ENV APP_ROOT=/opt/app-root
WORKDIR $APP_ROOT

# Install required packages
RUN microdnf update -y && microdnf -y install git file tar xz zip unzip bzip2 gzip python3.12 python3.12-pip && microdnf clean all && ln -sf /bin/python3.12 /bin/python3
RUN python3 -m pip install --no-cache-dir --root-user-action=ignore --upgrade pip setuptools

# copy license
COPY LICENSE /licenses/insights_engine_LICENSE
# add config file for plugins
RUN echo -e "defaults:\n  allow_remote_resource_access: False\n">/etc/insights.yaml
# Install insights-engine
COPY . .
RUN python3 -m pip install --no-cache-dir .

RUN useradd -ms /bin/bash i_engine
RUN chown -R i_engine $APP_ROOT
USER i_engine
# Start the engine
CMD ["insights-core-engine", "config.yaml"]
