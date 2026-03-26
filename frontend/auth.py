from typing import Optional
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request

from config import get_settings

settings = get_settings()
_signer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def create_session_token(username: str) -> str:
    return _signer.dumps({"user": username})


def verify_session_token(token: str) -> Optional[str]:
    try:
        data = _signer.loads(token, max_age=settings.session_max_age)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_session_token(token)
