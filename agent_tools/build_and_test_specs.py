import sys
import pathlib as pl
import dataclasses
import enum
import collections
import logging
import argparse
import json
import shutil
from typing import Dict, Type, List, Callable, Union


__PARENT_DIR__ = pl.Path(__file__).parent.absolute()
__SOURCE_ROOT__ = __PARENT_DIR__.parent

sys.path.append(str(__SOURCE_ROOT__))

from agent_tools import environment_deployers as deployers
from agent_tools import constants
from agent_tools import package_builders
from agent_tools import run_in_docker


_AGENT_BUILD_DIR = __SOURCE_ROOT__ / "agent_build"
_SCRIPTS_DIR_PATH = __PARENT_DIR__ / "environment_deployer_scripts"


base_environment_used_files = [
    _AGENT_BUILD_DIR / "requirements.txt",
    _AGENT_BUILD_DIR / "monitors_requirements.txt",
    __SOURCE_ROOT__ / "dev-requirements.txt",
    __SOURCE_ROOT__ / "benchmarks/micro/requirements-compression-algorithms.txt",
]

PYTHON_ENVIRONMENT_DEPLOYER = deployers.EnvironmentDeployer(
    name="python",
    deployment_script_path=_SCRIPTS_DIR_PATH / "install_python_and_ruby.sh"
)

BASE_ENVIRONMENT_DEPLOYER = deployers.EnvironmentDeployer(
    name="base_environment",
    deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_base_environment.sh",
    used_files=base_environment_used_files,
)

BASE_WINDOWS_ENVIRONMENT_DEPLOYER = deployers.EnvironmentDeployer(
    name="windows_agent_builder",
    deployment_script_path=_SCRIPTS_DIR_PATH / "deploy_agent_windows_builder.ps1",
    used_files=base_environment_used_files,
)


# Map deployers to their names.
DEPLOYERS: Dict[str, deployers.EnvironmentDeployer] = {
    dep.name: dep for dep in [
        PYTHON_ENVIRONMENT_DEPLOYER,
        BASE_ENVIRONMENT_DEPLOYER,
        BASE_WINDOWS_ENVIRONMENT_DEPLOYER
    ]
}

_LINUX_SPECS_BASE_IMAGE = "centos:7"
_LINUX_SPECS_DEPLOYERS = [
    PYTHON_ENVIRONMENT_DEPLOYER,
    BASE_ENVIRONMENT_DEPLOYER
]

_DEFAULT_ARCHITECTURES = [
    constants.Architecture.X86_64, constants.Architecture.ARM64
]


def create_build_spec_name(
        package_type: constants.PackageType,
        architecture: constants.Architecture = None
):
    result = f"{package_type.value}"
    if architecture:
        result = f"{result}_{architecture.value}"

    return result


@dataclasses.dataclass
class DockerImageInfo:
    image_name: str


@dataclasses.dataclass
class PackageBuildSpec:
    package_type: constants.PackageType
    package_builder_cls: Type[package_builders.PackageBuilder]
    used_deployers: List[deployers.EnvironmentDeployer]
    filename_glob: str
    architecture: constants.Architecture
    base_image: DockerImageInfo = None

    @property
    def name(self) -> str:
        return create_build_spec_name(
            package_type=self.package_type,
            architecture=self.architecture
        )

    @property
    def used_deployers_string_array(self):
        used_deployer_names = [d.name for d in self.used_deployers]
        return ",".join(used_deployer_names)

    @property
    def used_deployers_info_as_dict(self):

        return {
            "deployers": self.used_deployers_string_array,
            "base-docker-image": package_build_spec.base_image.image_name,
            "architecture": package_build_spec.architecture.value
        }

    def get_dockerized_function(
            self,
            func: Callable,
            build_stage: str,
            path_mappings: Dict[Union[str, pl.Path], Union[str, pl.Path]] = None
    ):
        image_name = f"agent-builder-spec-{self.name}".lower()
        wrapped_func = run_in_docker.dockerized_function(
            func=func,
            image_name=image_name,
            base_image=self.base_image.image_name,
            architecture=self.architecture,
            build_stage=build_stage,
            used_deployers=self.used_deployers,
            path_mappings=path_mappings

        )

        return wrapped_func

    def build(self, output_path: pl.Path):
        wrapped_func = self.get_dockerized_function(
            func=self.build_package_from_spec,
            build_stage="build",
            path_mappings={output_path: "/tmp/build"}
        )
        wrapped_func(
            package_build_spec_name=self.name,
            output_path_dir=str(output_path)
        )

    @staticmethod
    def build_package_from_spec(
            package_build_spec_name: str,
            output_path_dir: str,
            locally: bool = False,
            variant: str = None,
            no_versioned_file_name: bool = False
    ):
        output_path = pl.Path(output_path_dir)
        package_build_spec = PACKAGE_BUILD_SPECS[package_build_spec_name]
        if output_path.exists():
            shutil.rmtree(output_path)
        output_path.mkdir(parents=True)

        package_builder_cls = package_build_spec.package_builder_cls
        package_builder = package_builder_cls(
            architecture=package_build_spec.architecture,
            variant=variant, no_versioned_file_name=no_versioned_file_name
        )
        package_builder.build(
            output_path=output_path,
        )



def get_package_build_spec(
        package_build_spec: PackageBuildSpec
):
    used_deployer_names = [d.name for d in package_build_spec.used_deployers]
    used_deployers_str = ",".join(used_deployer_names)
    return {
        "deployers": used_deployers_str,
        "base-docker-image": package_build_spec.base_image,
        "architecture": package_build_spec.architecture.value
    }


PACKAGE_BUILD_SPECS: Dict[str, PackageBuildSpec] = {}


def _add_specs(
        package_type: constants.PackageType,
        package_builder_cls: Type[package_builders.PackageBuilder],
        filename_glob_format: str,
        used_deployers: List[deployers.EnvironmentDeployer] = None,
        base_docker_image: str = None,
        architectures: List[constants.Architecture] = None,
):
    global PACKAGE_BUILD_SPECS
    architectures = architectures or [None]

    specs = []

    for arch in architectures:
        used_deployers = used_deployers or []

        if base_docker_image:
            base_docker_image_spec = DockerImageInfo(
                image_name=base_docker_image,
            )
        else:
            base_docker_image_spec = None

        package_arch_name = package_builder_cls.PACKAGE_FILENAME_ARCHITECTURE_SUFFIXES.get(arch, "")

        spec = PackageBuildSpec(
            package_type=package_type,
            package_builder_cls=package_builder_cls,
            filename_glob=filename_glob_format.format(arch=package_arch_name),
            used_deployers=used_deployers,
            architecture=arch,
            base_image=base_docker_image_spec
        )
        spec_name = create_build_spec_name(
            package_type=package_type,
            architecture=arch
        )
        PACKAGE_BUILD_SPECS[spec_name] = spec
        specs.append(spec)

    return specs


DEB_x86_64, DEB_ARM64 = _add_specs(
    package_type=constants.PackageType.DEB,
    package_builder_cls=package_builders.DebPackageBuilder,
    filename_glob_format="scalyr-agent-2_*.*.*_{arch}.deb",
    used_deployers=_LINUX_SPECS_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
RPM_x86_64, RPM_ARM64 = _add_specs(
    package_type=constants.PackageType.RPM,
    package_builder_cls=package_builders.RpmPackageBuilder,
    filename_glob_format="scalyr-agent-2-*.*.*-*.{arch}.rpm",
    used_deployers=_LINUX_SPECS_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
TAR_x86_64, TAR_ARM64 = _add_specs(
    package_type=constants.PackageType.TAR,
    package_builder_cls=package_builders.TarballPackageBuilder,
    filename_glob_format="scalyr-agent-*.*.*_{arch}.tar.gz",
    used_deployers=_LINUX_SPECS_DEPLOYERS,
    base_docker_image=_LINUX_SPECS_BASE_IMAGE,
    architectures=_DEFAULT_ARCHITECTURES
)
MSI_x86_64 = _add_specs(
    package_type=constants.PackageType.MSI,
    package_builder_cls=package_builders.MsiWindowsPackageBuilder,
    filename_glob_format="ScalyrAgentInstaller-*.*.*.msi",
    used_deployers=[BASE_WINDOWS_ENVIRONMENT_DEPLOYER],
    architectures=[constants.Architecture.X86_64]
)

class TargetSystem(enum.Enum):
    UBUNTU_1404 = "ubuntu-1404"


class OSFamily(enum.Enum):
    WINDOWS = 1
    LINUX = 2


@dataclasses.dataclass
class Ec2BasedTestSpec:
    image_name: str
    image_id: str
    size_id: str
    ssh_username: str
    os_family: OSFamily


@dataclasses.dataclass
class PackageTestSpec:
    name: str
    target_system: TargetSystem
    package_build_spec: PackageBuildSpec
    remote_machine_spec: Union[DockerImageInfo, Ec2BasedTestSpec] = None


TEST_SPECS: Dict[str, PackageTestSpec] = {}
PACKAGE_BUILDER_TO_TEST_SPEC: Dict[str, List[PackageTestSpec]] = collections.defaultdict(list)


def create_test_spec(
        target_system: TargetSystem,
        package_builder_spec: PackageBuildSpec,
        remote_machine_specs: List[Union[DockerImageInfo, Ec2BasedTestSpec]] = None
):

    global TEST_SPECS, PACKAGE_BUILDER_TO_TEST_SPEC

    package_build_spec_name = create_build_spec_name(
        package_type=package_builder_spec.package_type,
        architecture=package_builder_spec.architecture
    )
    test_spec_name = f"{target_system.value}_{package_builder_spec.architecture.value}"
    if remote_machine_specs:
        for remote_machine_spec in remote_machine_specs:
            if isinstance(remote_machine_spec, DockerImageInfo):
                remote_machine_suffix = "docker"
            elif isinstance(remote_machine_spec, Ec2BasedTestSpec):
                remote_machine_suffix = "ec2"
            else:
                raise ValueError(f"Wrong remote machine spec: {remote_machine_spec}")

            full_name = f"{test_spec_name}_{remote_machine_suffix}"

            spec = PackageTestSpec(
                name=full_name,
                target_system=target_system,
                package_build_spec=package_builder_spec,
                remote_machine_spec=remote_machine_spec
            )
            TEST_SPECS[full_name] = spec
            PACKAGE_BUILDER_TO_TEST_SPEC[package_build_spec_name].append(spec)
    else:
        spec = PackageTestSpec(
            name=test_spec_name,
            target_system=target_system,
            package_builder_spec=package_builder_spec,
        )

        TEST_SPECS[test_spec_name] = spec
        PACKAGE_BUILDER_TO_TEST_SPEC[package_build_spec_name].append(spec)


create_test_spec(
    target_system=TargetSystem.UBUNTU_1404,
    package_builder_spec=DEB_x86_64,
    remote_machine_specs=[
        DockerImageInfo("ubuntu:14.04"),
        Ec2BasedTestSpec(
            image_name="Ubuntu Server 14.04 LTS (HVM)",
            image_id="ami-07957d39ebba800d5",
            size_id="t2.small",
            ssh_username="ubuntu",
            os_family=OSFamily.LINUX
        )
    ],
)
create_test_spec(
    target_system=TargetSystem.UBUNTU_1404,
    package_builder_spec=DEB_ARM64,
    remote_machine_specs=[
        DockerImageInfo("ubuntu:14.04"),
        Ec2BasedTestSpec(
            image_name="Ubuntu Server 14.04 LTS (HVM)",
            image_id="ami-07957d39ebba800d5",
            size_id="t2.small",
            ssh_username="ubuntu",
            os_family=OSFamily.LINUX
        )
    ],
)

if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(filename)s] %(message)s")

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command")

    # build_frozen_test_runner = subparsers.add_parser("build-frozen-test-runner")
    # build_frozen_test_runner.add_argument("spec_name", choices=SPECS.keys())
    # build_frozen_test_runner.add_argument("--output-dir", dest="output_dir")
    # build_frozen_test_runner.add_argument("--locally", required=False, action="store_true")

    test_specs_info_parser = subparsers.add_parser("get-package-test-specs")
    test_specs_info_parser.add_argument("package_type", choices=PACKAGE_BUILD_SPECS.keys())

    package_deployers_parser = subparsers.add_parser("get-package-build-spec-info")
    package_deployers_parser.add_argument("package_type", choices=PACKAGE_BUILD_SPECS.keys())

    deployer_parser = subparsers.add_parser("deployer")
    deployer_parser.add_argument("deployer_name", choices=DEPLOYERS.keys())
    deployer_parser.add_argument("deployer_command", choices=["deploy", "checksum", "result-image-name"])
    deployer_parser.add_argument("--base-docker-image", dest="base_docker_image")
    deployer_parser.add_argument("--cache-dir", dest="cache_dir")
    deployer_parser.add_argument("--architecture")

    # deployer_subparsers = deployer_parser.add_subparsers(dest="deployer_command")
    #
    # deploy_parser = deployer_subparsers.add_parser("deploy")


    # deployer_parser.add_argument("name", choices=DEPLOYERS.keys())
    # deployer_parser.add_argument("action", choices=["deploy", "checksum"])
    # deployer_parser.add_argument("--cache-dir", dest="cache_dir")
    # deployer_parser.add_argument("--base-docker-image", dest="base_docker_image")
    # deployer_parser.add_argument("--architecture")

    args = parser.parse_args()

    if args.command == "get-package-build-spec-info":
        package_build_spec = PACKAGE_BUILD_SPECS[args.package_type]
        build_spec = {"include": [package_build_spec.used_deployers_info_as_dict]}
        print(
            json.dumps(build_spec)
        )
        exit(0)

    if args.command == "get-package-test-specs":

        package_build_spec = PACKAGE_BUILD_SPECS[args.package_type]
        test_specs = PACKAGE_BUILDER_TO_TEST_SPEC[args.package_type]

        result_spec_infos = []

        for spec in test_specs:
            spec_info = {}
            spec_info.update(package_build_spec.used_deployers_info_as_dict)

            spec_info["spec_name"] = spec.name

            result_spec_infos.append(spec_info)

        print(json.dumps({"include": result_spec_infos}))

        sys.exit(0)

    if args.command == "deployer":
        deployer = DEPLOYERS[args.deployer_name]
        if args.deployer_command == "deploy":
            if args.base_docker_image:
                deployer.deploy_in_docker(
                    base_docker_image=args.base_docker_image,
                    architecture=constants.Architecture(args.architecture),
                    cache_dir=args.cache_dir,
                )
            else:
                deployer.deploy(
                    cache_dir=args.cache_dir
                )

            exit(0)

        if args.deployer_command == "checksum":
            checksum = deployer.get_used_files_checksum()
            print(checksum)
            exit(0)

        if args.deployer_command == "result-image-name":
            image_name = deployer.get_image_name(constants.Architecture(args.architecture))
            print(image_name)

