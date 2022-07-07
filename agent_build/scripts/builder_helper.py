import argparse
import sys
import pathlib as pl
from typing import Dict, Type, Callable

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent
# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(SOURCE_ROOT))

from agent_build.package_builders import ALL_BUILDERS
from agent_build.tools.environment_deployments.deployments import CacheableBuilder


def run_builder_from_command_line(
        possible_builders: Dict[str, Type[CacheableBuilder]],
        config: Dict = None,
):

    def create_parser():
        parser_ = argparse.ArgumentParser()
        parser_.add_argument("builder_name", choices=possible_builders.keys())
        return parser_

    base_parser = create_parser()
    args, other_args = base_parser.parse_known_args()

    builder_cls = possible_builders[args.builder_name]

    main_parser = create_parser()

    builder_cls.add_command_line_arguments(
        parser=main_parser
    )

    args = main_parser.parse_args()

    builder_cls.handle_command_line_arguments(args=args, config=config)


if __name__ == '__main__':
    run_builder_from_command_line(possible_builders=ALL_BUILDERS)

