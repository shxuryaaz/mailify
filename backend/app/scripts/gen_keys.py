"""Generate the secrets Mailify needs and print them ready to paste into .env:

  python -m app.scripts.gen_keys

Prints a Fernet key (encrypts the Gmail refresh token), a JWT secret, and a
VAPID keypair (Web Push). Run once; keep these out of source control.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.fernet import Fernet
from py_vapid import Vapid01


def _vapid_keypair() -> tuple[str, str]:
    vapid = Vapid01()
    vapid.generate_keys()
    # Application-server keys must be URL-safe base64, unpadded.
    priv = base64.urlsafe_b64encode(
        vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    ).decode().rstrip("=")
    public_numbers = vapid.public_key.public_numbers()
    raw_pub = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
    pub = base64.urlsafe_b64encode(raw_pub).decode().rstrip("=")
    return pub, priv


def main() -> None:
    fernet = Fernet.generate_key().decode()
    jwt_secret = secrets.token_urlsafe(48)
    vapid_pub, vapid_priv = _vapid_keypair()
    pubsub_token = secrets.token_urlsafe(24)
    cron_secret = secrets.token_urlsafe(24)

    print("# ---- paste into backend/.env ----")
    print(f"FERNET_KEY={fernet}")
    print(f"JWT_SECRET={jwt_secret}")
    print(f"VAPID_PUBLIC_KEY={vapid_pub}")
    print(f"VAPID_PRIVATE_KEY={vapid_priv}")
    print(f"PUBSUB_VERIFICATION_TOKEN={pubsub_token}")
    print(f"CRON_SECRET={cron_secret}")
    print()
    print("# ---- paste the public key into frontend/.env ----")
    print(f"VITE_VAPID_PUBLIC_KEY={vapid_pub}")


if __name__ == "__main__":
    main()
