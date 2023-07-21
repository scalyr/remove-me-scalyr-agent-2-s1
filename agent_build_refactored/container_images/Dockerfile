ARG IMAGE_TYPE

# This stage builds requirement libraries for the agent.
FROM build_base as build_requirement_libs
RUN python3 -m pip install --upgrade setuptools pip --root /tmp/requrements_root
RUN cp -a /tmp/requrements_root/. /
ARG AGENT_REQUIREMENTS
RUN echo "${AGENT_REQUIREMENTS}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/requrements_root
ARG TEST_REQUIREMENTS
RUN echo "${TEST_REQUIREMENTS}" > /tmp/test_requirments.txt
RUN python3 -m pip install -r /tmp/test_requirments.txt --root /tmp/test_requrements_root

FROM scratch as requirement_libs
COPY --from=build_requirement_libs /tmp/requrements_root /requirements
COPY --from=build_requirement_libs /tmp/test_requrements_root /test_requirements

FROM prod_base as final-common
ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
COPY --from=requirement_libs /requirements /
COPY --from=agent_filesystem / /

# Optional stage for docker-json.
FROM final-common as final-docker-json
# Nothing to add

# Optional stage for docker-api.
FROM final-common as final-docker-api
# Nothing to add


# Optional stage for docker-syslog.
FROM final-common as final-docker-syslog
# expose syslog ports
EXPOSE 601/tcp
# Please note Syslog UDP 1024 max packet length (rfc3164)
EXPOSE 514/udp


# Optional stage for k8s.
FROM final-common as final-k8s
ENV SCALYR_STDOUT_SEVERITY ERROR


FROM final-${IMAGE_TYPE} as final
MAINTAINER Scalyr Inc <support@scalyr.com>

CMD ["python3", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py","--no-fork", "--no-change-user", "start"]