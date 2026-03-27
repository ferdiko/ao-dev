import os
import time
import yaml
from argparse import ArgumentParser, REMAINDER
from sovara.common.constants import SOVARA_CONFIG
from sovara.runner.agent_runner import AgentRunner


def launch_command_parser():
    parser = ArgumentParser(
        usage="so-record <script.py> [<args>]",
        description="Launch a Python script with Sovara instrumentation.",
        allow_abbrev=False,
    )

    parser.add_argument(
        "--config-file",
        default=None,
        help="The config file to use for the default values in the launching script.",
    )

    parser.add_argument(
        "--run-name",
        default=None,
        help="Name that will be used in the run list. If not set, Run X where X is the index of the current run will be used.",
    )

    parser.add_argument(
        "-m",
        "--module",
        action="store_true",
        help="Change each process to interpret the launch script as a Python module, executing with the same behavior as 'python -m'.",
    )

    parser.add_argument(
        "script_path",
        type=str,
        help="The full path to the script to be executed, followed by all the remaining arguments.",
    )

    parser.add_argument(
        "script_args", nargs=REMAINDER, help="Arguments of the script to be executed."
    )
    return parser


def _validate_launch_command(args):
    default_dict = {}
    config_file = None

    # check if the location of the config file is set
    if args.config_file is not None and os.path.isfile(args.config_file):
        config_file = args.config_file
    # if not, check in the SOVARA_CONFIG path
    elif os.path.isfile(SOVARA_CONFIG):
        config_file = SOVARA_CONFIG
    # if also not, it stays empty and we rely on the (default) args

    if config_file is not None:
        with open(config_file, encoding="utf-8") as f:
            default_dict = yaml.safe_load(f)

    # the arguments overwrite what is written in the config file
    # that's why they come second.
    args.__dict__ = {**default_dict, **args.__dict__}
    # we don't need the config_file anymore and we don't
    # want to confuse people with it still in the args:
    del args.config_file

    return args


def launch_command(args):
    args = _validate_launch_command(args)

    agent_runner = AgentRunner(
        script_path=args.script_path,
        script_args=args.script_args,
        is_module_execution=args.module,
        run_name=args.run_name,
    )
    agent_runner.run()


def main():
    parser = launch_command_parser()
    args = parser.parse_args()
    launch_command(args)


if __name__ == "__main__":
    main()
