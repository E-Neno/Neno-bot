import asyncio
import logging

from dotenv import load_dotenv

from .client import client_from_environment


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_dotenv()
    asyncio.run(client_from_environment().serve_forever())


if __name__ == "__main__":
    main()
