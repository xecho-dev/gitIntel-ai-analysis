import base64
import os
import json
import struct
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESCCM, AESGCM
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

bearer_scheme = HTTPBearer(auto_error=False)


def _jwe_dir_aes_cbc_hs512_decrypt(jwe_token: str, secret: str) -> bytes:
    """
    解密 NextAuth v5 JWE token（alg=dir, enc=A256CBC-HS512）。

    JWE compact serialization:
      BASE64URL(BASE64URL(header).BASE64URL(encrypted_key).BASE64URL(iv).BASE64URL(ct).BASE64URL(tag))
    """
    try:
        parts = jwe_token.split(".")
        if len(parts) != 5:
            return b""

        protected_header_b64, encrypted_key_b64, iv_b64, ciphertext_b64, tag_b64 = parts

        protected_header = base64url_decode(protected_header_b64)
        iv = base64url_decode(iv_b64)
        ciphertext = base64url_decode(ciphertext_b64)
        tag = base64url_decode(tag_b64)

        header = json.loads(protected_header)
        alg = header.get("alg")  # e.g. "dir"
        enc = header.get("enc")  # e.g. "A256CBC-HS512"

        # A256CBC-HS512: 256-bit key for AES-CBC, 512-bit key for HMAC-SHA-512
        # Total derived key = 256/8 + 512/8 = 32 + 64 = 96 bytes
        derived_key = _hkdf_sha256(secret.encode(), b"", 96, info=b"NextAuth.js-v5-JWE-Encryption")
        mac_key = derived_key[:32]
        enc_key = derived_key[32:64]

        # Verify auth tag: HMAC-SHA512(AL, AAD || IV || CT)
        al = struct.pack("!>Q", len(protected_header) * 8)
        aad = protected_header + iv + ciphertext
        expected_tag = hmac_sha512(mac_key, aad)
        if not hmac_verify(tag, expected_tag):
            return b""

        # Decrypt: AES-256-CBC with PKCS7 padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as sym_padding
        cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        padder = sym_padding.PKCS7(256).unpadder()
        plaintext = padder.update(padded) + padder.finalize()
        return plaintext

    except Exception:
        return b""


def base64url_decode(data: str | bytes) -> bytes:
    if isinstance(data, str):
        data = data.encode()
    # Add padding if needed
    rem = len(data) % 4
    if rem:
        data += b"=" * (4 - rem)
    return base64.urlsafe_b64decode(data)


def hmac_sha512(key: bytes, data: bytes) -> bytes:
    import hmac, hashlib
    return hmac.new(key, data, hashlib.sha512).digest()


def hmac_verify(tag: bytes, expected: bytes) -> bool:
    import hmac
    return hmac.compare_digest(tag, expected)


def _hkdf_sha256(ikm: bytes, salt: bytes, length: int, info: bytes = b"") -> bytes:
    """Simple HKDF-SHA256"""
    import hashlib, hmac as _hmac
    prk = _hmac.new(salt or b"\x00" * 32, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    counter = 1
    while len(okm) < length:
        t = _hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def decode_jwt_token(token: str) -> Optional[dict]:
    """
    1. 尝试 python-jose 解码（标准 HS256 JWT）
    2. 尝试 JWE 解密（NextAuth v5 加密格式 alg=dir, enc=A256CBC-HS512），
       解密后得到内层 JWT，再用 python-jose 解码内层 payload
    """
    secret = os.getenv("AUTH_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        return None

    # 尝试 1: 直接用 HS256 解码（适用于旧版 NextAuth 或某些配置）
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"],
            options={"verify_aud": False, "verify_exp": True},
        )
        return payload
    except JWTError:
        pass

    # 尝试 2: JWE 加密格式（NextAuth v5 默认）
    try:
        inner_jwt = _jwe_dir_aes_cbc_hs512_decrypt(token, secret)
        if not inner_jwt:
            return None
        inner_str = inner_jwt.decode("utf-8")
        # 内层仍然是 JWS
        payload = jwt.decode(
            inner_str, secret, algorithms=["HS256"],
            options={"verify_aud": False, "verify_exp": True},
        )
        return payload
    except Exception:
        return None


def get_token_from_request(request: Request) -> Optional[str]:
    """从请求中提取 Bearer token"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def require_auth(request: Request) -> dict:
    """
    验证请求中的用户身份，返回一个包含 user_id 的 payload。

    认证优先级：
    1. X-User-Id header（来自前端 BFF 层，信任来源，仅做非空检查）
    2. Bearer token + JWT_SECRET / AUTH_SECRET 解码
    """
    # 优先级 1：来自 BFF 的内部可信请求头
    x_user_id = request.headers.get("X-User-Id")
    if x_user_id:
        print(f"[DEBUG require_auth] Using X-User-Id from BFF header: {x_user_id}")
        return {"sub": x_user_id, "source": "bff-header"}

    # 优先级 2：标准 Bearer token
    token = get_token_from_request(request)
    if not token:
        print("[DEBUG require_auth] No Bearer token found in request")
        raise HTTPException(status_code=401, detail="未登录，请先使用 GitHub 账号登录")

    secret = os.getenv("AUTH_SECRET") or os.getenv("JWT_SECRET")
    print(f"[DEBUG require_auth] Token prefix: '{token[:30]}...', secret present: {bool(secret)}, token header start: '{token[:10]}'")

    payload = decode_jwt_token(token)
    if not payload:
        import traceback
        traceback.print_exc()
        print("[DEBUG require_auth] JWT decode failed - possible secret mismatch or invalid token")
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    print(f"[DEBUG require_auth] Successfully decoded payload: {payload}")
    return payload
