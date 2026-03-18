"""Entry point: python -m confluence_mini_mcp"""

from .server import mcp


def main():
    mcp.run()


if __name__ == "__main__":
    main()
