import abc
import enum
import logging
import pathlib as pl
import subprocess
from typing import Dict, Type, List, Set

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch, AGENT_REQUIREMENTS, REQUIREMENTS_DEV_COVERAGE
from agent_build_refactored.tools.docker.common import delete_container
from agent_build_refactored.tools.builder import Builder
from agent_build_refactored.tools.docker.buildx.build import buildx_build, DockerImageBuildOutput, OCITarballBuildOutput, BuildOutput, LocalDirectoryBuildOutput

from agent_build_refactored.prepare_agent_filesystem import build_linux_fhs_agent_files, add_config

SUPPORTED_ARCHITECTURES = [
    CpuArch.x86_64,
    #CpuArch.AARCH64,
    #CpuArch.ARMV7,
]

logger = logging.getLogger(__name__)
_PARENT_DIR = pl.Path(__file__).parent


class ImageType(enum.Enum):
    K8S = "k8s"
    DOCKER_JSON = "docker-json"
    DOCKER_SYSLOG = "docker-syslog"
    DOCKER_API = "docker-api"


_IMAGE_REGISTRY_NAMES = {
    ImageType.K8S: ["scalyr-k8s-agent"],
    ImageType.DOCKER_JSON: ["scalyr-agent-docker-json"],
    ImageType.DOCKER_SYSLOG: [
        "scalyr-agent-docker-syslog",
        "scalyr-agent-docker",
    ],
    ImageType.DOCKER_API: ["scalyr-agent-docker-api"]
}


class ContainerisedAgentBuilder(Builder):
    BASE_DISTRO: str
    TAG_SUFFIXES: List[str]

    _requirements_libs_already_built = False
    _final_image_base_already_built = False

    def __init__(
        self,
        image_type: ImageType = None,
        architecture: CpuArch = None,
        only_cache_dependency_arch: CpuArch = None,
    ):
        super(ContainerisedAgentBuilder, self).__init__()
        self.image_type = image_type

        self.architecture = architecture
        self.only_cache_dependency_arch = only_cache_dependency_arch

    @property
    def result_oci_layout_tarball_path(self) -> pl.Path:
        return self.result_dir / f"{self.image_type.value}-{self.__class__.NAME}.tar"

    @property
    def dependencies_dir(self) -> pl.Path:
        return self.work_dir / "dependencies"

    @classmethod
    def _build_dependencies(
        cls,
        stage: str,
        architectures: List[CpuArch],
        output: BuildOutput,
        cache_name: str = None,
    ):

        test_requirements = f"{REQUIREMENTS_DEV_COVERAGE}"

        buildx_build(
            dockerfile_path=_PARENT_DIR / "dependencies.Dockerfile",
            context_path=_PARENT_DIR,
            architecture=architectures,
            build_args={
                "BASE_DISTRO": base_distro,
                "AGENT_REQUIREMENTS": AGENT_REQUIREMENTS,
                "TEST_REQUIREMENTS": test_requirements,
            },
            stage=stage,
            output=output,
            cache_name=cache_name,
        )

    def _build_final_image_base_oci_layout(self):

        stage_name = "final_image_base"
        result_image_oci_layout = self.work_dir / stage_name

        if self.__class__._final_image_base_already_built:
            return result_image_oci_layout

        self._build_dependencies(
            stage=stage_name,
            architectures=SUPPORTED_ARCHITECTURES[:],
            output=OCITarballBuildOutput(
                dest=result_image_oci_layout,
            ),
        )

        self.__class__._final_image_base_already_built = True
        return result_image_oci_layout

    def build_requirement_libs(self):

        stage_name = "requirement_libs"
        result_dir = self.work_dir / stage_name

        if self.__class__._requirements_libs_already_built:
            return result_dir

        base_cache_name = stage_name

        for arch in SUPPORTED_ARCHITECTURES:
            build_target_name = _arch_to_docker_build_target_folder(arch)
            arch_dir = result_dir / build_target_name

            cache_name = f"{base_cache_name}_{arch.value}"

            self._build_dependencies(
                stage=stage_name,
                cache_name=cache_name,
                architectures=[arch],
                output=LocalDirectoryBuildOutput(
                    dest=arch_dir,
                )
            )

        self.__class__._requirements_libs_already_built = True
        return result_dir

    def generate_final_registry_tags(
        self,
        registry: str,
        user: str,
        tags: List[str],
    ):
        result_names = []

        for image_name in _IMAGE_REGISTRY_NAMES[self.image_type]:
            for tag in tags:
                for tag_suffix in self.__class__.TAG_SUFFIXES:
                    final_name = f"{registry}/{user}/{image_name}:{tag}{tag_suffix}"
                    result_names.append(final_name)

        return result_names

    def create_agent_filesystem(self):
        agent_filesystem_dir = self.work_dir / "agent_filesystem"
        build_linux_fhs_agent_files(
            output_path=agent_filesystem_dir,
        )
        # Need to create some docker specific directories.
        pl.Path(agent_filesystem_dir / "var/log/scalyr-agent-2/containers").mkdir()

        # Add config file
        config_name = self.image_type.value
        config_path = SOURCE_ROOT / "docker" / f"{config_name}-config"
        add_config(config_path, agent_filesystem_dir / "etc/scalyr-agent-2")

        # Also change shebang in the agent_main file to python3, since all images fully switched to it.
        agent_main_path = agent_filesystem_dir / "usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py"
        agent_main_content = agent_main_path.read_text()
        new_agent_main_content = agent_main_content.replace("#!/usr/bin/env python", "#!/usr/bin/env python3", 1)
        agent_main_path.write_text(new_agent_main_content)
        return agent_filesystem_dir

    def _build(self):

        requirement_libs_dir = self.build_requirement_libs()

        final_image_base_oci_layout_dir = self._build_final_image_base_oci_layout()

        if self.image_type is None:
            raise Exception("Image type has to be specified for a full build.")

        agent_filesystem_dir = self.create_agent_filesystem()

        buildx_build(
            dockerfile_path=_PARENT_DIR / "Dockerfile",
            context_path=_PARENT_DIR,
            architecture=SUPPORTED_ARCHITECTURES[:],
            build_args={
                "BASE_DISTRO": self.__class__.BASE_DISTRO,
                "IMAGE_TYPE": self.image_type.value
            },
            build_contexts={
                "base_image": f"oci-layout:///{final_image_base_oci_layout_dir}",
                "requirement_libs": str(requirement_libs_dir),
                "agent_filesystem": str(agent_filesystem_dir),
            },
            output=OCITarballBuildOutput(
                dest=self.result_oci_layout_tarball_path,
                extract=False,
            )
        )

    def publish(
        self,
        tags: List[str],
        existing_oci_layout_dir: pl.Path = None,
        registry_username: str = None,
        registry_password: str = None,
    ):
        if existing_oci_layout_dir:
            oci_layer = existing_oci_layout_dir
        else:
            self.build()
            oci_layer = self.result_oci_layout_tarball_path

        container_name = "agent_image_publish_skopeo"

        cmd_args = [
            "docker",
            "run",
            "-i",
            "--rm",
            f"--name={container_name}",
            "--net=host",
            f"-v={oci_layer}:/tmp/oci_layout.tar",
            "quay.io/skopeo/stable:latest",
            #"--debug",
            "copy",
            "--all",
        ]

        if not registry_username and not registry_password:
            cmd_args.extend([
                "--dest-no-creds",
                "--dest-tls-verify=false",
            ])

        delete_container(
            container_name=container_name,
        )

        for tag in tags:
            logger.info(f"Publish image '{tag}'")
            subprocess.run(
                [
                    *cmd_args,
                    "oci-archive:/tmp/oci_layout.tar",
                    f"docker://{tag}",
                ],
                check=True,

            )

        delete_container(
            container_name=container_name,
        )


def _arch_to_docker_build_target_folder(arch: CpuArch):
    if arch == CpuArch.x86_64:
        return "linux_amd64_"
    elif arch == CpuArch.AARCH64:
        return "linux_arm64_"
    elif arch == CpuArch.ARMV7:
        return "linux_arm_v7"


ALL_CONTAINERISED_AGENT_BUILDERS: Dict[str, Type[ContainerisedAgentBuilder]] = {}

for base_distro in ["ubuntu", "alpine"]:
    tag_suffixes = [f"-{base_distro}"]
    if base_distro == "ubuntu":
        tag_suffixes.append("")

    name = base_distro

    class _ContainerisedAgentBuilder(ContainerisedAgentBuilder):
        NAME = name
        BASE_DISTRO = base_distro
        TAG_SUFFIXES = tag_suffixes[:]

    ALL_CONTAINERISED_AGENT_BUILDERS[name] = _ContainerisedAgentBuilder
