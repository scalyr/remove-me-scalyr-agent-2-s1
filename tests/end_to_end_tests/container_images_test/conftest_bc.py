import pathlib as pl
import subprocess
from typing import Callable

import pytest

from agent_build_refactored.tools.constants import CpuArch, REQUIREMENTS_DEV_COVERAGE
from agent_build_refactored.tools.docker.common import delete_container
from agent_build_refactored.tools.docker.buildx.build import buildx_build, DockerImageBuildOutput, LocalDirectoryBuildOutput

from agent_build_refactored.container_images.dependencies import build_agent_image_dependencies
from agent_build_refactored.container_images.image_builders import ALL_CONTAINERISED_AGENT_BUILDERS, ImageType, SUPPORTED_ARCHITECTURES


_PARENT_DIR = pl.Path(__file__).parent

def add_command_line_args(parser, add_func: Callable):

    add_func(
        "--image-builder-name",
        required=True,
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    add_func(
        "--architecture",
        required=True,
        choices=[a.value for a in SUPPORTED_ARCHITECTURES]
    )

    add_func(
        "--image-type",
        required=True,
        choices=[t.value for t in ImageType],
    )

    add_func(
        "--image-oci-tarball",
        required=False,
    )


def pytest_addoption(parser):
    add_command_line_args(
        parser=parser,
        add_func=parser.addoption
    )


@pytest.fixture(scope="session")
def image_builder_name(request):
    return request.config.option.image_builder_name


@pytest.fixture(scope="session")
def image_builder_cls(image_builder_name):
    return ALL_CONTAINERISED_AGENT_BUILDERS[image_builder_name]


@pytest.fixture(scope="session")
def image_type(request):
    return ImageType(request.config.option.image_type)


@pytest.fixture(scope="session")
def architecture(request):
    return CpuArch(request.config.option.architecture)


@pytest.fixture(scope="session")
def registry_with_image():

    container_name = "agent_image_e2e_test_registry"

    delete_container(
        container_name=container_name
    )

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p=5000:5000",
            f"--name={container_name}",
            "registry:2",
        ]
    )

    yield

    delete_container(
        container_name=container_name,
    )


@pytest.fixture(scope="session")
def all_image_tags(image_builder_cls, image_type):

    image_builder = image_builder_cls(
        image_type=image_type,
    )

    tags = image_builder.generate_final_registry_tags(
        registry="localhost:5000",
        user="user",
        tags=["latest", "test"],
    )

    return tags


@pytest.fixture(scope="session")
def image_full_tag(all_image_tags):
    return all_image_tags[0]


@pytest.fixture(scope="session")
def prod_image_tag(all_image_tags):
    return all_image_tags[0]


@pytest.fixture(scope="session")
def test_image_tag(all_image_tags, prod_image_tag, image_builder_cls, image_type, request):
    image_builder = image_builder_cls(
        image_type=image_type,
    )

    image_builder.publish(
        tags=all_image_tags,
        existing_oci_layout_dir=request.config.option.image_oci_tarball
    )

    dirr = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2-final/agent_build_output/ffffffff")
    image_builder_cls.build_dependencies(
        output_dir=dirr,
    )
    image_name = "test_version"

    test_image_build_context_dir = _PARENT_DIR / "fixtures/test_image"
    buildx_build(
        dockerfile_path=test_image_build_context_dir / "Dockerfile",
        context_path=test_image_build_context_dir,
        architecture=SUPPORTED_ARCHITECTURES[:],
        build_args={
            "REQUIREMENTS_FILE_CONTENT": REQUIREMENTS_DEV_COVERAGE,
        },
        build_contexts={
            "prod_image": f"docker-image://{prod_image_tag}",
            "dependencies": str(dirr),
        },
        output=DockerImageBuildOutput(
            name=image_name,
        )
    )
    yield image_name

    subprocess.run(
        [
            "docker",
            "image",
            "rm",
            "-f",
            image_name,
        ],
        check=True,
    )


# @pytest.fixture(scope="session")
# def image_oci_tarball(image_builder_cls, tmp_path_factory, image_type, request, all_image_tags):
#
#     output = tmp_path_factory.mktemp("builder_output")
#     output = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2-final/agent_build_output/IMAGE_OCI")
#     image_builder = image_builder_cls(
#         image_type=image_type,
#     )
#
#     image_builder.publish(
#         tags=all_image_tags,
#         existing_oci_layout_dir=request.config.option.image_oci_tarball
#     )
#     dependencies_dir = pl.Path("/Users/arthur/PycharmProjects/scalyr-agent-2-final/agent_build_output/ggggg")
#
#     build_image_test_version(
#         architectures=SUPPORTED_ARCHITECTURES[:],
#         prod_image_name=all_image_tags[1],
#         output_dir=dependencies_dir,
#     )
#
#     a=10



