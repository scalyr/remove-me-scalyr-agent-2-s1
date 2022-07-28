import abc
import dataclasses
import logging
import os
import re
import time
import pathlib as pl
import json
from urllib.parse import quote_plus, urlencode
from typing import Optional, BinaryIO, Union, Callable, List, Any

import requests


log = logging.getLogger(__name__)


class LogFileReader:
    def __init__(self, file_path: pl.Path):
        self._remaining_data = b""
        self._file_path = file_path
        self._file_obj: Optional[BinaryIO] = None

    def close(self):
        if self._file_obj:
            self._file_obj.close()

    def _read_data(self) -> bytes:
        if self._file_obj is None:
            self._file_obj = self._file_path.open("rb")

        return self._file_obj.read()

    def read_next_lines(self) -> Optional[str]:

        new_data = self._read_data()
        # There is no new data, skip and wait.
        if new_data:
            # There is a new content in the log file. Get only full lines from the new data.
            # Join existing log data with a new.
            self._remaining_data = b"".join([self._remaining_data, new_data])

        # Find the first new line character to separate next complete lines from the other data
        next_new_line_index = self._remaining_data.find(b"\n")

        # There's no any new line, wait until there is enough data for a line.
        if next_new_line_index == -1:
            return None

        # There is a complete log line.
        new_line_bytes = self._remaining_data[:next_new_line_index + 1:]

        # Save remaining data.
        self._remaining_data = self._remaining_data[next_new_line_index + 1:]

        return new_line_bytes.decode().strip()


class AgentRunner:
    def __init__(self, config: dict):
        self._config = config

    def start_no_fork(self):
        pass

    @abc.abstractmethod
    def start(self):
        pass


AGENT_LOG_LINE_TIMESTAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+Z"


def preprocess_agent_log_messages(content: str):

    lines = content.splitlines(keepends=True)

    if not lines:
        return []

    # Remove last line if it's incomplete.
    if not lines[-1].endswith(os.linesep):
        lines.pop(-1)

    lines = [line.strip() for line in lines]

    messages = []
    for line in lines:
        line = line.strip()
        if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} .*", line):
            messages.append((line, []))
        else:
            # If line does not start with agent log preamble, then it has to be a multiline message
            # or error traceback, so we all those additional lines to previous message in additional list.
            messages[-1][1].append(line)

    return messages


def check_agent_log_for_errors(content: str):

    messages = preprocess_agent_log_messages(content=content)
    error_line_pattern = re.compile(rf"{AGENT_LOG_LINE_TIMESTAMP} (ERROR|CRITICAL) .*")
    for message, additional_lines in messages:
        # error is detected, normally fail the test, but also need to check for some particular error
        # that we may want pass.

        whole_error = message + "\n" + "\n".join(additional_lines)
        if error_line_pattern.match(message):

            to_fail = True

            # There is an issue with dns resolution on GitHub actions side, so we skip some of the error messages.
            connection_error_mgs = '[error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to errno=-3.'

            if connection_error_mgs in messages:
                # If the traceback that follows after error message contains particular error message,
                # then we are ok with that.
                errors_to_ignore = [
                    "socket.gaierror: [Errno -3] Try again",
                    "socket.gaierror: [Errno -3] Temporary failure in name resolution",
                ]
                for error_to_ignore in errors_to_ignore:
                    if error_to_ignore in additional_lines:
                        to_fail = False
                        log.info(f"Ignored error: {whole_error}")
                        break

            if to_fail:
                raise AssertionError(f"Agent log container error: {whole_error}")

def check_requests_stats_in_agent_log(content: str) -> bool:
    # The pattern to match the periodic message lines with network request statistics.

    messages = preprocess_agent_log_messages(content)
    for line, _ in messages:
        m = re.match(
            rf"{AGENT_LOG_LINE_TIMESTAMP} INFO \[core] \[(scalyr_agent\.agent_main:\d+|scalyr-agent-2:\d+)] "
            r"agent_requests requests_sent=(?P<requests_sent>\d+) "
            r"requests_failed=(?P<requests_failed>\d+) "
            r"bytes_sent=(?P<bytes_sent>\d+) "
            r".+",
            line,
        )

        if m:
            log.info("Requests stats message has been found. Verify that stats...")
            # Also do a final check for a valid request stats.
            md = m.groupdict()
            requests_sent = int(md["requests_sent"])
            bytes_sent = int(md["bytes_sent"])
            assert bytes_sent > 0, f"Agent log says that during the run the agent has sent zero bytes."
            assert requests_sent > 0, f"Agent log says that during the run the agent has sent zero requests."

            log.info(
                f"Agent requests stats have been found and they are valid."
            )
            return True
    else:
        return False


def verify_agent_log(
        log_file_reader: LogFileReader
):

    log.info("Start verifying agent log.")
    error_line_pattern = re.compile(rf"{AGENT_LOG_LINE_TIMESTAMP} ERROR .*")
    whole_log_text = ""

    while True:
        line = log_file_reader.read_next_lines()
        if line is None:
            time.sleep(0.1)
            continue

        whole_log_text = f"{whole_log_text}\n{line}"

        # error line is detected, normally fail the test, but also need to check for some particular error
        # that we may want pass.
        if error_line_pattern.match(line):
            to_fail = True
            error_line = line
            error_traceback_lines = []

            # Keep reading traceback lines until normal error message was read.
            # Since we don't know the the last traceback line, we just wait for a normal log  message or
            # stop after some timeout.
            # 20 seconds should be ok since there has to be a next periodic status message.
            stop_time = time.time() + 20

            while time.time() >= stop_time:
                line = log_file_reader.read_next_lines()

                if line is None:
                    time.sleep(0.1)
                    continue

                # We know that this is a traceback line because it does not start with regular log message preamble,
                # and if it starts with such, then the traceback is over.
                if re.match(rf"{AGENT_LOG_LINE_TIMESTAMP} .*", line):
                    break

                error_traceback_lines.append(line)

            whole_error = b"".join([error_line, *error_traceback_lines])

            # There is an issue with dns resolution on GitHub actions side, so we skip some of the error messages.
            connection_error_mgs = '[error="client/connectionFailed"] Failed to connect to "https://agent.scalyr.com" due to errno=-3.'


            if connection_error_mgs in line:
                # If the traceback that follows after error message contains particular error message,
                # then we are ok with that.
                errors_to_ignore = [
                    "socket.gaierror: [Errno -3] Try again",
                    "socket.gaierror: [Errno -3] Temporary failure in name resolution",
                ]
                for error_to_ignore in errors_to_ignore:
                    if error_to_ignore in error_traceback_lines[-1]:
                        to_fail = False
                        log.info(f"Ignored error: {whole_error}")
                        break

            if to_fail:
                raise AssertionError(f"Error line in agent log:\n{whole_error}")

        # The pattern to match the periodic message lines with network request statistics. This message is written only
        # when all startup messages are written, so it's a good time to stop the verification of the agent.log file.
        m = re.match(
            rf"{AGENT_LOG_LINE_TIMESTAMP} INFO \[core] \[(agent_main\.py:\d+|scalyr-agent-2:\d+)] "
            r"agent_requests requests_sent=(?P<requests_sent>\d+) "
            r"requests_failed=(?P<requests_failed>\d+) "
            r"bytes_sent=(?P<bytes_sent>\d+) "
            r".+",
            line,
        )

        if m:
            log.info("Requests stats message has been found. Verify that stats...")
            # Also do a final check for a valid request stats.
            md = m.groupdict()
            requests_sent = int(md["requests_sent"])
            bytes_sent = int(md["bytes_sent"])
            assert bytes_sent > 0, f"    Agent log says that during the run the agent has sent zero bytes.\n" \
                                   f"Whole log content: {whole_log_text}"
            assert requests_sent > 0, f"    Agent log says that during the run the agent has sent zero requests.\n" \
                                      f"Whole log content: {whole_log_text}"

            log.info(
                f"    Agent requests stats have been found and they are valid.\nWhole log content: {whole_log_text}"
            )
            break


class ScalyrQueryRequest:
    """
    Abstraction to create scalyr API requests.
    """

    def __init__(
            self,
            server_address,
            read_api_key,
            max_count=1000,
            start_time=None,
            end_time=None,
            filters=None,
            logger=log
    ):
        self._server_address = server_address
        self._read_api_key = read_api_key
        self._max_count = max_count
        self._start_time = start_time
        self._end_time = end_time
        self._filters = filters or []

        self._logger = logger

    def build(self):
        params = {
            "maxCount": self._max_count,
            "startTime": self._start_time or time.time(),
            "token": self._read_api_key,
        }

        params_str = urlencode(params)

        quoted_filters = [quote_plus(f) for f in self._filters]
        filter_fragments_str = "+and+".join(quoted_filters)

        query = "{0}&filter={1}".format(params_str, filter_fragments_str)

        return query

    def send(self):
        query = self.build()

        protocol = "https://" if not self._server_address.startswith("http") else ""

        full_query = "{0}{1}/api/query?queryType=log&{2}".format(
            protocol, self._server_address, query
        )

        self._logger.info("Query server: {0}".format(full_query))

        with requests.Session() as session:
            resp = session.get(full_query)

        if resp.status_code != 200:
            self._logger.info(f"Query failed with {resp.text}.")
            return None

        data = resp.json()

        return data

_TEST_LOG_MESSAGE_COUNT = 1000

def write_messages_to_test_log(
        log_file_path: pl.Path
):
    with log_file_path.open("a") as test_log_write_file:
        for i in range(_TEST_LOG_MESSAGE_COUNT):
            data = {
                "count": i
            }
            data_json = json.dumps(data)
            test_log_write_file.write(data_json)
            test_log_write_file.write("\n")
            test_log_write_file.flush()


_QUERY_RETRY_DELAY = 10

def verify_test_log_file_upload(
        #log_file_path: pl.Path,
        scalyr_api_read_key: str,
        scalyr_server: str,
        #full_server_host: str,
        start_time: Union[float, int],
        query_filters: List[str],
        counter_getter: Callable
):
    while True:
        resp = ScalyrQueryRequest(
            server_address=scalyr_server,
            read_api_key=scalyr_api_read_key,
            max_count=_TEST_LOG_MESSAGE_COUNT,
            start_time=start_time,
            filters=query_filters
            # filters=[
            #     f"$logfile=='{log_file_path}'"
            #     f"$serverHost=='{full_server_host}'",
            # ]
        ).send()

        if not resp:
            log.info(f"Retry in {_QUERY_RETRY_DELAY} sec.")
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        events = resp["matches"]

        if not events:
            log.info(f"No events have been uploaded yet, retry in {_QUERY_RETRY_DELAY} sec.")
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        if len(events) < _TEST_LOG_MESSAGE_COUNT:
            log.info(
                f"Not all events have been uploaded. "
                f"Expected: {_TEST_LOG_MESSAGE_COUNT}. "
                f"Actual: {len(events)}"
            )
            time.sleep(_QUERY_RETRY_DELAY)
            continue

        assert len(events) == _TEST_LOG_MESSAGE_COUNT, f"Number of uploaded event more that " \
                                                      f"expected ({_TEST_LOG_MESSAGE_COUNT})."

        event_counts = [counter_getter(e) for e in events]

        assert event_counts == list(range(_TEST_LOG_MESSAGE_COUNT)), "Counters in the uploaded event not in the right order."

        log.info(f"All {_TEST_LOG_MESSAGE_COUNT} events have been uploaded.")
        break


def verify_logs(
    scalyr_api_read_key: str,
    scalyr_server: str,
    get_agent_log_content: Callable[[], str],
    counters_verification_query_filters: List[str],
    counter_getter: Callable[[Any], int],
    write_counter_messages: Callable[[], None] = None
):
    """
    Do a basic verifications on agent log file.
    It also writes test log with counter messages that are queried later from Scalyr servers to compare results.
    :param scalyr_api_read_key: Scalyr API key with read permissions.
    :param scalyr_server: Scalyr server hostname.
    :param get_agent_log_content: Function that has to return current contant of the running agent log.
        That function has to implemented accoring to a type of the running agent, e.g. kubernetes, docker, or package
    :param counters_verification_query_filters:  List of Scalyr query language filters which are required to fetch
        messages that are ingested by the 'write_counter_messages'
    :param counter_getter: Function which should return counter from the ingested message.
    :param write_counter_messages: Function that writes counter messages to upload the to Scalyr.
        Can be None, for example for the kubernetes image test, where writer pod is already started.
    """
    if write_counter_messages:
        log.info("Write test log file messages.")
        write_counter_messages()

    agent_log_content = get_agent_log_content()

    # Verify agent start up line
    assert "Starting scalyr agent" in agent_log_content
    # Ensure CA validation is not disabled with default install
    assert "sslverifyoff" not in agent_log_content
    assert "Server certificate validation has been disabled" not in agent_log_content

    check_agent_log_for_errors(content=agent_log_content)

    log.info("Wait for agent log requests stats.")
    while not check_requests_stats_in_agent_log(
        content=get_agent_log_content()
    ):
        time.sleep(1)

    log.info("Verify that previously written test log file content has been uploaded to server.")
    try:
        while True:
            resp = ScalyrQueryRequest(
                server_address=scalyr_server,
                read_api_key=scalyr_api_read_key,
                max_count=_TEST_LOG_MESSAGE_COUNT,
                start_time=time.time() - 60 * 5,
                filters=counters_verification_query_filters
            ).send()

            if not resp:
                log.info(f"Retry in {_QUERY_RETRY_DELAY} sec.")
                time.sleep(_QUERY_RETRY_DELAY)
                continue

            events = resp["matches"]

            if not events:
                log.info(f"No events have been uploaded yet, retry in {_QUERY_RETRY_DELAY} sec.")
                time.sleep(_QUERY_RETRY_DELAY)
                continue

            if len(events) < _TEST_LOG_MESSAGE_COUNT:
                log.info(
                    f"Not all events have been uploaded. "
                    f"Expected: {_TEST_LOG_MESSAGE_COUNT}. "
                    f"Actual: {len(events)}"
                )
                time.sleep(_QUERY_RETRY_DELAY)
                continue

            assert len(events) == _TEST_LOG_MESSAGE_COUNT, f"Number of uploaded event more that " \
                                                          f"expected ({_TEST_LOG_MESSAGE_COUNT})."

            event_counts = [counter_getter(e) for e in events]

            assert event_counts == list(range(_TEST_LOG_MESSAGE_COUNT)), "Counters in the uploaded event not in the right order."

            log.info(f"All {_TEST_LOG_MESSAGE_COUNT} events have been uploaded.")
            break

        # Do a final error check for agent log.
        check_agent_log_for_errors(content=get_agent_log_content())
    finally:
        log.info(f"FULL AGENT LOG:\n{get_agent_log_content()}")
