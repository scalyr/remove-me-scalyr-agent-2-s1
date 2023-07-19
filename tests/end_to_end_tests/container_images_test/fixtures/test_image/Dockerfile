#FROM prod_image as build
#ARG REQUIREMENTS_FILE_CONTENT
#RUN echo "${REQUIREMENTS_FILE_CONTENT}" > /tmp/requirements.txt
#RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/root
#
#FROM scratch
#COPY --from=build /tmp/root /

FROM prod_image as build
ARG REQUIREMENTS_FILE_CONTENT
RUN echo "${REQUIREMENTS_FILE_CONTENT}" > /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt --root /tmp/root


FROM prod_image
COPY --from=build /tmp/root /
RUN cp "$(which python3)" "$(which python3)-original"
ADD python_coverage_wrapper.sh /tmp/python_coverage_wrapper.sh
RUN mv /tmp/python_coverage_wrapper.sh "$(which python3)"
