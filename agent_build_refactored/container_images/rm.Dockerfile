ARG BASE_DISTRO
ARG IMAGE_TYPE=common

FROM ubuntu:22.04 as base_ubuntu
# We upgrade current packages in order to keep everything up to date, including security updates.
RUN DEBIANFRONTEND=noninteractive apt-get update && \
    apt-get dist-upgrade --yes --no-install-recommends --no-install-suggests && \
    apt-get install -y \
    python3 && \
    apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

FROM python:3.8.16-alpine as base_alpine

FROM base_${BASE_DISTRO} as base

FROM base as build_base_ubuntu
# We upgrade current packages in order to keep everything up to date, including security updates.
ENV DEBIANFRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y \
    python3 \
    python3-pip  \
    python3-dev \
    rustc \
    cargo

FROM base as build_base_alpine
RUN apk update && apk add --virtual build-dependencies \
    binutils \
    build-base \
    linux-headers \
    gcc \
    g++ \
    make \
    curl \
    python3-dev \
    patchelf \
    git \
    bash \
    rust \
    cargo

FROM build_base_${BASE_DISTRO} as build_requirements
RUN python3 -m pip install --upgrade setuptools pip --root /tmp/requrements_root
RUN cp -a /tmp/requrements_root/. /
ARG AGENT_REQUIREMENTS
RUN echo "${AGENT_REQUIREMENTS}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/requrements_root

FROM scratch as requirements
COPY --from=build_requirements /tmp/requrements_root/. /

FROM base as agent_base
COPY --from=requirements / /
COPY --from=agent_filesystem / /

FROM agent_base as final_common
MAINTAINER Scalyr Inc <support@scalyr.com>
CMD ["python3", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]

# Optional stage for docker-json.
FROM final_common as final-docker-json
# Nothing to add

# Optional stage for docker-api.
FROM final_common as final-docker-api
# Nothing to add


# Optional stage for docker-syslog.
FROM final_common as final-docker-syslog
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM final_common as final-k8s
ENV SCALYR_STDOUT_SEVERITY ERROR

FROM final-${IMAGE_TYPE}