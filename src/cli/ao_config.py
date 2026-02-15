import argparse
import os
from ao.common.config import Config, _ask_field
from ao.common.constants import AO_CONFIG


def get_user_input() -> Config:
    database_url = _ask_field(
        "Database URL (leave empty for SQLite)\n> ",
        str,
        default=os.environ.get("DATABASE_URL"),
        error_message="Please enter a valid database URL or leave empty.",
    )

    config = Config(database_url=database_url)
    return config


def config_command():
    config = get_user_input()
    config_file = AO_CONFIG
    config.to_yaml_file(config_file)


def config_command_parser():
    description = (
        "Run `ao config` before you debug your agents. This "
        "will prompt some configurations that you can choose. "
        "These will get saved in a default path or in --config_path "
        "which you can pass: `ao config --config_path some/path/config.yaml"
    )
    parser = argparse.ArgumentParser("Config", usage="ao-config", description=description)
    return parser


def main():
    parser = config_command_parser()
    parser.parse_args()
    config_command()


if __name__ == "__main__":
    main()
