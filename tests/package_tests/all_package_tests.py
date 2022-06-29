# Copyright 2014-2021 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import collections
import pathlib as pl
import subprocess
import sys
import logging
from typing import Dict, List, Type


from agent_build.tools import constants
from agent_build import package_builders
from tests.package_tests.internals import docker_test, k8s_test
from agent_build.tools.environment_deployments import deployments
from agent_build.tools import build_in_docker
from agent_build.tools import common
from agent_build.package_builders import DOCKER_IMAGE_PACKAGE_BUILDERS, PackageBuilder, DockerImageBuilder, CacheableStepsRunner
from agent_build.tools.environment_deployments.deployments import DeploymentStep
from agent_build.tools.constants import Architecture

_PARENT_DIR = pl.Path(__file__).parent
__SOURCE_ROOT__ = _PARENT_DIR.parent.parent.absolute()

# The global collection of all test. It is used by CI aimed scripts in order to be able to perform those test just
# by knowing the name of needed test.
ALL_PACKAGE_TESTS: Dict[str, Type["Test"]] = {}

# Maps package test of some package to the builder of this package. Also needed for the GitHub Actions CI to
# create a job matrix for a particular package tests.
PACKAGE_BUILDER_TESTS: Dict[
    package_builders.PackageBuilder, List["Test"]
] = collections.defaultdict(list)


class Test:
    """
    Particular package test. If combines information about the package type, architecture,
    deployment and the system where test has to run.
    """
    NAME: str
    PACKAGE_BUILDER_CLS: Type[PackageBuilder]
    CACHEABLE_DEPLOYMENT_STEPS: List[DeploymentStep]

    def __init__(
        self,
        #base_name: str,
        #package_builder_cls: Type[package_builders.PackageBuilder],
    ):
        """
        :param base_name: Base name of the test.
        :param package_builder: Builder instance to build the image.
        :param additional_deployment_steps: Additional deployment steps that may be needed to perform the test.
            They are additionally performed after the deployment steps of the package builder.
        :param deployment_architecture: Architecture of the machine where the test's deployment has to be perform.
            by default it is an architecture of the package builder.
        """
        #self._base_name = base_name
        #self.package_builder_cls = package_builder_cls

    # @property
    # def unique_name(self) -> str:
    #     """
    #     The unique name of the package test. It contains information about all specifics that the test has.
    #     """
    #     return f"{self.package_builder.name}_{self._base_name}".replace("-", "_")


class DockerImagePackageTest(Test):
    """
    Test for the agent docker images.
    """

    DOCKER_IMAGE_BUILDER: DockerImageBuilder

    def __init__(
        self,
        # base_name: str,
        # package_builder_cls: Type[package_builders.ContainerPackageBuilder],
        scalyr_api_key: str,
        name_suffix: str = None,
        target_image_architectures: List[constants.Architecture] = None
    ):
        """
        :param target_image_architectures: List of architectures in which to perform the image tests.
        :param base_name: Base name of the test.
        :param package_builder: Builder instance to build the image.
        :param additional_deployment_steps: Additional deployment steps that may be needed to perform the test.
            They are additionally performed after the deployment steps of the package builder.
        :param deployment_architecture: Architecture of the machine where the test's deployment has to be perform.
            by default it is an architecture of the package builder.
        """

        super().__init__()

        if target_image_architectures:
            self.target_image_architecture = target_image_architectures
        else:
            self.target_image_architecture = [
                Architecture.X86_64,
                Architecture.ARM64,
                Architecture.ARMV7
            ]

        self.scalyr_api_key = scalyr_api_key
        self.name_suffix = name_suffix

    # @property
    # def unique_name(self) -> str:
    #     return self._base_name

    def run_test(self):
        """
        Run test for the agent docker image.
        First of all it builds an image, then pushes it to the local registry and does full test.

        :param scalyr_api_key:  Scalyr API key.
        :param name_suffix: Additional suffix to the agent instance name.
        """

        # Run container with docker registry.
        logging.info("Run new local docker registry in container.")
        registry_container = build_in_docker.LocalRegistryContainer(
            name="agent_images_registry", registry_port=5050
        )

        registry_host = "localhost:5050"

        builder_cls = type(self).DOCKER_IMAGE_BUILDER

        def _test_pushed_image():

            # Test that all tags has been pushed to the registry.
            for tag in ["latest", "test", "debug"]:
                logging.info(
                    f"Test that the tag '{tag}' is pushed to the registry '{registry_host}'"
                )

                for image_name in builder_cls.RESULT_IMAGE_NAMES:
                    full_image_name = f"{registry_host}/{image_name}:{tag}"

                    # Remove the local image first, if exists.
                    logging.info("    Remove existing image.")
                    subprocess.check_call(
                        ["docker", "image", "rm", "-f", full_image_name]
                    )

                    logging.info("    Log in to the local registry.")
                    # Login to the local registry.
                    subprocess.check_call(
                        [
                            "docker",
                            "login",
                            "--password",
                            "nopass",
                            "--username",
                            "nouser",
                            registry_host,
                        ]
                    )

                    # Pull the image
                    logging.info("    Pull the image.")
                    try:
                        subprocess.check_call(["docker", "pull", full_image_name])
                    except subprocess.CalledProcessError:
                        logging.exception(
                            "    Can not pull the result image from local registry."
                        )

                    # Check if the tested image contains needed distribution.
                    if "debian" in type(self).NAME:
                        expected_os_name = "debian"
                    elif "alpine" in type(self).NAME:
                        expected_os_name = "alpine"
                    else:
                        raise AssertionError(
                            f"Test {type(self).NAME} does not contain os name (bullseye or alpine)"
                        )

                    # Get the content of the 'os-release' file from the image and verify the distribution name.
                    os_release_content = (
                        common.check_output_with_log(
                            [
                                "docker",
                                "run",
                                "-i",
                                "--rm",
                                str(full_image_name),
                                "/bin/cat",
                                "/etc/os-release",
                            ]
                        )
                        .decode()
                        .lower()
                    )

                    assert (
                        expected_os_name in os_release_content
                    ), f"Expected {expected_os_name}, got {os_release_content}"

                    # Remove the image once more.
                    logging.info("    Remove existing image.")
                    subprocess.check_call(
                        ["docker", "image", "rm", "-f", full_image_name]
                    )

            # Use any of variants of the image name to test it.
            local_registry_image_name = (
                f"{registry_host}/{builder_cls.RESULT_IMAGE_NAMES[0]}"
            )

            # Start the tests for each architecture.
            # TODO: Make tests run in parallel.
            for arch in self.target_image_architecture:
                logging.info(
                    f"Start testing image '{local_registry_image_name}' with architecture "
                    f"'{arch.as_docker_platform.value}'"
                )

                if "k8s" in builder_cls.NAME:
                    k8s_test.run(
                        image_name=local_registry_image_name,
                        architecture=arch,
                        scalyr_api_key=self.scalyr_api_key,
                        name_suffix=self.name_suffix,
                    )
                else:
                    docker_test.run(
                        image_name=local_registry_image_name,
                        architecture=arch,
                        scalyr_api_key=self.scalyr_api_key,
                        name_suffix=self.name_suffix,
                    )

        try:
            with registry_container:
                # Build image and push it to the local registry.
                # Instead of calling the build function run the build_package script,
                # so it can also be tested.
                logging.info("Build docker image")
                subprocess.check_call(
                    [
                        sys.executable,
                        "build_package_new.py",
                        type(self).DOCKER_IMAGE_BUILDER.NAME,
                        "--registry",
                        registry_host,
                        "--tag",
                        "latest",
                        "--tag",
                        "test",
                        "--tag",
                        "debug",
                        "--push",
                    ],
                    cwd=str(__SOURCE_ROOT__),
                )
                _test_pushed_image()
        finally:
            # Cleanup.
            # Removing registry container.
            subprocess.check_call(["docker", "logout", registry_host])

            subprocess.check_call(["docker", "image", "prune", "-f"])


DOCKER_IMAGE_TESTS = {}
# Create tests for the all docker images (json/syslog/api) and for k8s image.
for builder_name, builder_cls in DOCKER_IMAGE_PACKAGE_BUILDERS.items():
    class ImagePackageTest(DockerImagePackageTest, CacheableStepsRunner):
        NAME = f"{builder_name}_test"
        # Specify the builder that has to build the image.
        DOCKER_IMAGE_BUILDER = builder_cls
        # Specify which architectures of the result image has to be tested.
        CACHEABLE_DEPLOYMENT_STEPS = [*builder_cls.CACHEABLE_DEPLOYMENT_STEPS]

    DOCKER_IMAGE_TESTS[ImagePackageTest.NAME] = ImagePackageTest

ALL_PACKAGE_TESTS.update(DOCKER_IMAGE_TESTS)

# (
#     DOCKER_JSON_TEST_DEBIAN,
#     DOCKER_SYSLOG_TEST_DEBIAN,
#     DOCKER_API_TEST_DEBIAN,
#     K8S_TEST_DEBIAN,
#     DOCKER_JSON_TEST_ALPINE,
#     DOCKER_SYSLOG_TEST_ALPINE,
#     DOCKER_API_TEST_ALPINE,
#     K8S_TEST_ALPINE,
# ) = _docker_image_tests
