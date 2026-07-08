#!/usr/bin/env python3
"""
guildcord entrypoint.

Usage:
    python main.py [config.yaml]

Defaults to ./config.yaml if no path is given.
"""

import asyncio
import sys

from guildcord.config.schema import load_config
from guildcord.discord_bridge.bot import WowBridge


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)
    bridge = WowBridge(config)
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
