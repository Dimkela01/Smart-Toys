"""Maintenance commands.

make seed                      # create the first admin, print its TOTP setup URI
python -m app.cli seed-admin --email me@example.com
python -m app.cli rotate-totp --email me@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from app.config import settings
from app.db import SessionFactory, engine
from app.services import admin as admin_service
from app.services import audit


async def _seed_admin(email: str, password: str | None) -> int:
    async with SessionFactory() as session:
        existing = await admin_service.find_by_email(session, email)
        if existing is not None:
            # already in the desired state, so this is not a failure
            print(f"admin {email} already exists; use rotate-totp to issue a new secret")
            return 0

        generated = password or secrets.token_urlsafe(16)
        admin, secret = await admin_service.create_admin(session, email=email, password=generated)
        await audit.record(session, actor_type="system", action="admin.created", target=f"admin:{admin.id}")
        await session.commit()

    print(f"admin created: {email}")
    if password is None:
        print(f"password:      {generated}")
    print(f"TOTP secret:   {secret}")
    print(f"setup URI:     {admin_service.provisioning_uri(email=email, secret=secret)}")
    print("\nAdd the URI to an authenticator app now; it is not stored in readable form.")
    return 0


async def _rotate_totp(email: str) -> int:
    async with SessionFactory() as session:
        admin = await admin_service.find_by_email(session, email)
        if admin is None:
            print(f"no admin with address {email}")
            return 1
        secret = await admin_service.rotate_totp(session, admin=admin)
        await audit.record(
            session, actor_type="system", action="admin.totp_rotated", target=f"admin:{admin.id}"
        )
        await session.commit()

    print(f"new TOTP secret for {email}: {secret}")
    print(f"setup URI: {admin_service.provisioning_uri(email=email, secret=secret)}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.command == "seed-admin":
            return await _seed_admin(args.email, args.password)
        if args.command == "rotate-totp":
            return await _rotate_totp(args.email)
    finally:
        await engine.dispose()
    print(f"unknown command: {args.command}")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-admin", help="create a team account with TOTP")
    seed.add_argument("--email", default=settings.admin_seed_email)
    seed.add_argument(
        "--password",
        default=settings.admin_seed_password or None,
        help="omit to have one generated and printed",
    )

    rotate = sub.add_parser("rotate-totp", help="issue a new TOTP secret")
    rotate.add_argument("--email", default=settings.admin_seed_email)

    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
