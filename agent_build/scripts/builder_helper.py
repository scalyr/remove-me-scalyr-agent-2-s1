import argparse
from typing import Dict, Type

from agent_build.package_builders import ALL_BUILDERS
from agent_build.tools.environment_deployments.deployments import CacheableBuilder


def run_builder_from_command_line(
        possible_builders: Dict[str, Type[CacheableBuilder]]
):

    def create_parser():
        parser_ = argparse.ArgumentParser()
        parser_.add_argument("builder_name", choices=possible_builders.keys())
        return parser_

    base_parser = create_parser()
    args, other_args = base_parser.parse_known_args()

    builder_cls = ALL_BUILDERS[args.builder_name]

    main_parser = create_parser()

    builder_cls.add_command_line_arguments(parser=main_parser)

    args = main_parser.parse_args()

    builder_cls.handle_command_line_arguments(args=args)


if __name__ == '__main__':
    run_builder_from_command_line(possible_builders=ALL_BUILDERS)

