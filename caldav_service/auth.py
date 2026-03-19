"""
CalDAV 认证模块

支持：
1. HTTP Basic Auth（用户名 + API Token 作为密码）
2. HTTP Basic Auth（用户名 + 明文密码）
3. Bearer Token（Authorization: Token <key>）

CalDAV 客户端（iOS/macOS/Thunderbird/DAVx5）均使用 Basic Auth。
"""

import base64

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

from logger import logger


def get_user_from_request(request):
    """
    从 HTTP 请求中提取并认证用户。

    按优先级尝试：
    1. HTTP Basic Auth，密码字段接受 API Token
    2. HTTP Basic Auth，密码字段接受明文密码
    3. Authorization: Token/Bearer <key>
    4. 仅 Token（无 Authorization 前缀，用于某些客户端）

    Returns:
        User 对象，或 None
    """
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')

    if not auth_header:
        logger.debug("[CalDAV Auth] No Authorization header present")
        return None

    logger.debug(f"[CalDAV Auth] Authorization header type: {auth_header.split(' ')[0] if ' ' in auth_header else 'unknown'}")

    if auth_header.startswith('Basic '):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        except Exception as e:
            logger.warning(f"[CalDAV Auth] Failed to decode Basic auth: {e}")
            return None
        username, _, password = decoded.partition(':')
        if not username or not password:
            logger.warning(f"[CalDAV Auth] Basic auth missing username or password")
            return None

        logger.debug(f"[CalDAV Auth] Basic auth attempt for user: {username}")

        # 尝试把 password 当作 API Token
        try:
            token_obj = Token.objects.select_related('user').get(key=password)
            if token_obj.user.username == username:
                logger.debug(f"[CalDAV Auth] Token auth succeeded for: {username}")
                return token_obj.user
            else:
                logger.debug(f"[CalDAV Auth] Token found but username mismatch: expected={token_obj.user.username}, got={username}")
        except Token.DoesNotExist:
            logger.debug(f"[CalDAV Auth] Password is not a valid API token")

        # 尝试普通密码认证
        user = authenticate(request, username=username, password=password)
        if user:
            logger.debug(f"[CalDAV Auth] Password auth succeeded for: {username}")
            return user

        # 密码认证失败 — 检查用户是否存在并有可用密码
        try:
            db_user = User.objects.get(username=username)
            has_usable = db_user.has_usable_password()
            logger.warning(f"[CalDAV Auth] Password auth failed for: {username} (user exists={True}, has_usable_password={has_usable})")
        except User.DoesNotExist:
            logger.warning(f"[CalDAV Auth] User '{username}' does not exist")
        return None

    # Token xxx 或 Bearer xxx
    if auth_header.startswith('Token ') or auth_header.startswith('Bearer '):
        token_value = auth_header.split(' ', 1)[1].strip()
        try:
            user = Token.objects.select_related('user').get(key=token_value).user
            logger.debug(f"[CalDAV Auth] Token/Bearer auth succeeded for: {user.username}")
            return user
        except Token.DoesNotExist:
            logger.warning(f"[CalDAV Auth] Invalid token/bearer value")
            return None

    logger.warning(f"[CalDAV Auth] Unrecognized Authorization scheme: {auth_header[:20]}...")
    return None
