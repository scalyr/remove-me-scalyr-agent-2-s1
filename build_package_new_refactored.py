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

"""
This is a new package build script which uses new package build logic.
usage:
      build_package_new.py <name of the package>

to see all available packages to build use:
    build_package_new.py --help


Commands line arguments for the particular package builder are defined within the builder itself,
to see those options use build_package_new.py <name of the package> --help.
"""
import argparse
import sys
import pathlib as pl


if sys.version_info < (3, 8, 0):
    raise ValueError("This script requires Python 3.8 or above")

# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.absolute()))

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_PACKAGE_BUILDERS,
)
from agent_build_refactored.container_images.image_builders import (
    ALL_CONTAINERISED_AGENT_BUILDERS,
    ImageType,
    SUPPORTED_ARCHITECTURES,
)

init_logging()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)

    package_parser = subparsers.add_parser("package")

    package_parser.add_argument(
        "builder_name",
        choices=ALL_PACKAGE_BUILDERS.keys(),
    )
    package_parser.add_argument(
        "--output-dir",
        default=str(SOURCE_ROOT / "build")
    )

    image_parser = subparsers.add_parser("image")

    image_parser.add_argument(
        "builder_name",
        choices=ALL_CONTAINERISED_AGENT_BUILDERS.keys(),
    )

    def _add_images_type_arg(_parser):
        _parser.add_argument(
            "--image-type",
            required=True,
            choices=[t.value for t in ImageType]
        )

    image_parser_action_subparsers = image_parser.add_subparsers(dest="action", required=True)

    image_build_parser = image_parser_action_subparsers.add_parser("build")
    image_build_parser.add_argument(
        "--output-dir",
        required=True,
    )
    _add_images_type_arg(image_build_parser)

    image_only_dependency_parser = image_parser_action_subparsers.add_parser("build-only-cache-dependency")
    image_only_dependency_parser.add_argument(
        "--architecture",
        required=True,
        choices=[a.value for a in SUPPORTED_ARCHITECTURES]
    )

    image_publish_parser = image_parser_action_subparsers.add_parser("publish")

    _add_images_type_arg(image_publish_parser)
    image_publish_parser.add_argument(
        "--registry",
        required=True,
    )

    image_publish_parser.add_argument(
        "--user",
        required=True,
    )
    image_publish_parser.add_argument(
        "--tags",
        required=True,
    )
    image_publish_parser.add_argument(
        "--from-oci-layout-dir",
        required=False,
    )

    args = parser.parse_args()

    if args.command == "package":
        package_builder_cls = ALL_PACKAGE_BUILDERS[args.builder_name]

        builder = package_builder_cls()
        builder.build(
            output_dir=pl.Path(args.output_dir),
        )
        exit(0)
    elif args.command == "image":
        image_builder_cls = ALL_CONTAINERISED_AGENT_BUILDERS[args.builder_name]

        if args.action == "build-only-cache-dependency":
            builder = image_builder_cls(
                only_cache_dependency_arch=CpuArch(args.architecture)
            )
            builder.build()
            exit(0)
        elif args.action == "build":
            if args.output_dir:
                output_dir = pl.Path(args.output_dir)
            else:
                output_dir = None

            builder = image_builder_cls(
                image_type=ImageType(args.image_type),
            )
            builder.build(
                output_dir=output_dir
            )
            exit(0)
        elif args.action == "publish":
            tags = args.tags.split(",")

            builder = image_builder_cls(
                image_type=ImageType(args.image_type),
            )

            if args.from_oci_layout_dir:
                existing_oci_layout_dir = pl.Path(args.from_oci_layout_dir)
            else:
                existing_oci_layout_dir = None
            
            final_tags = builder.generate_final_registry_tags(
                registry=args.registry,
                user=args.user,
                tags=tags
            )
            builder.publish(
                tags=final_tags,
                existing_oci_layout_dir=existing_oci_layout_dir
            )
            exit(0)
