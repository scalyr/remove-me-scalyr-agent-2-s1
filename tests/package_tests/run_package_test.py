import argparse
import json
import pathlib as pl
import logging
import sys
import os
from typing import Union, Type

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent.parent.absolute()

sys.path.append(str(__SOURCE_ROOT__))

from tests.package_tests import all_package_tests


_TEST_CONFIG_PATH = pl.Path(__file__).parent / "credentials.json"

if _TEST_CONFIG_PATH.exists():
    config = json.loads(_TEST_CONFIG_PATH.read_text())
else:
    config = {}


def get_option(name: str, default: str = None, type_: Union[Type[str], Type[list]] = str, ):
    global config

    name = name.lower()

    env_variable_name = name.upper()
    value = os.environ.get(env_variable_name, None)
    if value is not None:
        if type_ == list:
            value = value.split(",")
        else:
            value = type_(value)
        return value

    value = config.get(name, None)
    if value:
        return value

    if default:
        return default

    raise ValueError(
        f"Can't find config option '{name}' "
        f"Provide it through '{env_variable_name}' env. variable or by "
        f"specifying it in the test config file - {_TEST_CONFIG_PATH}."
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s][%(module)s] %(message)s")

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)
    list_command_parser = subparsers.add_parser("list")

    package_test_parser = subparsers.add_parser("run-package-test")
    package_test_parser.add_argument("test_name", choices=all_package_tests.ALL_PACKAGE_TESTS.keys())

    package_test_parser.add_argument("--build-dir-path", dest="build_dir_path", required=False)
    package_test_parser.add_argument("--package-path", dest="package_path", required=False)
    package_test_parser.add_argument(
        "--frozen-package-test-runner-path",
        dest="frozen_package_test_runner_path",
        required=False
    )
    package_test_parser.add_argument("--scalyr-api-key", dest="scalyr_api_key", required=False)

    get_tests_github_matrix_parser = subparsers.add_parser("get-package-builder-tests-github-matrix")
    get_tests_github_matrix_parser.add_argument("package_name")

    args = parser.parse_args()

    if args.command == "list":
        names = [t.unique_name for t in all_package_tests.ALL_PACKAGE_TESTS.values()]
        for test_name in sorted(names):
            print(test_name)

    if args.command == "run-package-test":

        scalyr_api_key = get_option("scalyr_api_key", args.scalyr_api_key)

        package_test = all_package_tests.ALL_PACKAGE_TESTS[args.test_name]

        if isinstance(package_test, all_package_tests.DockerImagePackageTest):
            package_test.run_test(
                scalyr_api_key=scalyr_api_key
            )
        exit(0)
