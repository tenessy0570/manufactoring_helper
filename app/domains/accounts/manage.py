"""Create the first superuser with a password entered only in the operator's terminal."""

import argparse
import asyncio
from getpass import getpass

from app.core.config import get_settings
from app.core.di import create_container
from app.domains.accounts.models import UserCreate
from app.domains.accounts.service import AccountService


async def create(username: str, password: str) -> None:
    container = create_container(get_settings())
    try:
        async with container() as scope:
            user = await (await scope.get(AccountService)).create(
                UserCreate(username=username, password=password, is_superuser=True)
            )
            print("Superuser created:", user.username)
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()
    password = getpass("Password (at least 12 characters): ")
    if not 12 <= len(password) <= 128:
        raise SystemExit("Password must contain 12 to 128 characters")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    asyncio.run(create(args.username, password))


if __name__ == "__main__":
    main()
