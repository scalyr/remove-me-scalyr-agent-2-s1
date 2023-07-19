import pathlib as pl
import subprocess
from typing import Type

from agent_build_refactored.tools.constants import REQUIREMENTS_DEV_COVERAGE, AGENT_BUILD_OUTPUT_PATH
from agent_build_refactored.tools.docker.common import delete_container
from agent_build_refactored.tools.docker.buildx.build import buildx_build, DockerImageBuildOutput
from agent_build_refactored.container_images.image_builders import ALL_CONTAINERISED_AGENT_BUILDERS, ImageType, ContainerisedAgentBuilder, SUPPORTED_ARCHITECTURES

_PARENT_DIR = pl.Path(__file__).parent


def build_test_version_of_container_image(
    image_builder_cls: Type[ContainerisedAgentBuilder],
    image_type: ImageType,
    result_image_name: str,
    ready_image_oci_tarball: pl.Path = None,
):

    image_builder = image_builder_cls(
        image_type=image_type,
    )

    registry_container_name = "agent_image_e2e_test_registry"

    delete_container(
        container_name=registry_container_name
    )

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p=5000:5000",
            f"--name={registry_container_name}",
            "registry:2",
        ],
        check=True
    )
    try:
        all_image_tags = image_builder.generate_final_registry_tags(
            registry="localhost:5000",
            user="user",
            tags=["prod"],
        )

        image_builder.publish(
            tags=all_image_tags,
            existing_oci_layout_dir=ready_image_oci_tarball
        )

        prod_image_tag = all_image_tags[0]

        test_dependencies_dir = AGENT_BUILD_OUTPUT_PATH / "container_image_e2e_test_dependencies"

        image_builder_cls.build_dependencies(
            output_dir=test_dependencies_dir,
        )

        buildx_build(
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            context_path=_PARENT_DIR,
            architecture=SUPPORTED_ARCHITECTURES[:],
            build_args={
                "REQUIREMENTS_FILE_CONTENT": REQUIREMENTS_DEV_COVERAGE,
            },
            build_contexts={
                "prod_image": f"docker-image://{prod_image_tag}",
                "dependencies": str(test_dependencies_dir),
            },
            output=DockerImageBuildOutput(
                name=result_image_name,
            )
        )
    finally:
        delete_container(
            container_name=registry_container_name
        )

    return result_image_name


def get_image_builder_by_name(name: str):
    return ALL_CONTAINERISED_AGENT_BUILDERS[name]