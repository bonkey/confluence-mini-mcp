"""Entry point: python -m confluence_mini_mcp"""

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from .doctor import run_doctor

        sys.exit(run_doctor())

    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
