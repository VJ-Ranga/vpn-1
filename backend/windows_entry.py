"""Standalone backend entry point, bundled with PyInstaller onedir.

The build must include app.main as a hidden import for uvicorn's import string.
"""

import argparse
import ipaddress

import uvicorn


def loopback_host(value: str) -> str:
    try:
        if ipaddress.ip_address(value).is_loopback:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("host must be a loopback IP address")


def port_number(value: str) -> int:
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("port must be between 1 and 65535")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Northstar desktop backend")
    parser.add_argument("--host", type=loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=port_number, default=8766)
    args = parser.parse_args(argv)
    uvicorn.run("app.main:app", host=args.host, port=args.port, access_log=False,
                loop="asyncio", http="h11", ws="none")


if __name__ == "__main__":
    main()
