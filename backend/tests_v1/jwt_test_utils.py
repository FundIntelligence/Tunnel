"""
Shared helpers for tests that exercise the authenticated request path.

Since `_extract_user_id_from_request` now verifies the Supabase JWT signature
(ES256, against the project's public JWKS), tests can no longer hand-build an
unsigned token and expect it to be accepted. These helpers mint *genuinely
signed* ES256 tokens with a throwaway test keypair, and expose the matching
public JWKS so tests can patch `backend.v1.api._get_jwks` to return it.

Usage:
    from tests_v1.jwt_test_utils import bearer, patch_jwks
    with patch_jwks():
        client.patch(..., headers=bearer("user-sub-abc123"))
"""
import time
from contextlib import contextmanager
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk as _jose_jwk
from jose import jwt as _jose_jwt

TEST_KID = "test-signing-key-1"
AUDIENCE = "authenticated"

# Real signing keypair — its public half IS published in PUBLIC_JWKS.
_priv = ec.generate_private_key(ec.SECP256R1())
_PRIV_PEM = _priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUB_PEM = _priv.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

_pub_jwk = _jose_jwk.construct(_PUB_PEM, "ES256").to_dict()
_pub_jwk["kid"] = TEST_KID
_pub_jwk["use"] = "sig"

PUBLIC_JWKS = {"keys": [_pub_jwk]}

# A DIFFERENT keypair whose public half is NOT published — used to forge a
# structurally-valid, correctly-claimed token whose signature cannot verify.
_attacker_priv = ec.generate_private_key(ec.SECP256R1())
_ATTACKER_PRIV_PEM = _attacker_priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def _claims(sub, exp_delta=3600, aud=AUDIENCE):
    now = int(time.time())
    c = {"sub": sub, "iat": now, "exp": now + exp_delta}
    if aud is not None:
        c["aud"] = aud
    return c


def make_token(sub, exp_delta=3600, aud=AUDIENCE, kid=TEST_KID):
    """A genuinely signed, valid ES256 token (verifies against PUBLIC_JWKS)."""
    return _jose_jwt.encode(
        _claims(sub, exp_delta, aud), _PRIV_PEM, algorithm="ES256", headers={"kid": kid}
    )


def make_forged_token(sub, kid=TEST_KID):
    """A token claiming a published kid but signed by an unknown key — must be rejected."""
    return _jose_jwt.encode(
        _claims(sub), _ATTACKER_PRIV_PEM, algorithm="ES256", headers={"kid": kid}
    )


def make_expired_token(sub):
    return make_token(sub, exp_delta=-10)


def bearer(sub, **kw):
    return {"Authorization": f"Bearer {make_token(sub, **kw)}"}


def forged_bearer(sub, **kw):
    return {"Authorization": f"Bearer {make_forged_token(sub, **kw)}"}


@contextmanager
def patch_jwks():
    """Patch the API's JWKS fetch to return our in-memory test public key."""
    with patch("backend.v1.api._get_jwks", return_value=PUBLIC_JWKS):
        yield
