"""
file_service/url_fetcher.py
URL 上传：下载 + 白名单校验 + SSRF 防护
"""
import ipaddress
import logging
import os
import re
import socket
from urllib.parse import urlparse, unquote

import requests
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile

from file_service.models import UserFile, UserStorageQuota

from logger import logger

# ========== 域名白名单 ==========
DEFAULT_URL_DOMAIN_WHITELIST = [
    # 网盘直链
    'aliyundrive.com',
    'lanzou.com', 'lanzoui.com', 'lanzoux.com',
    'weiyun.com',
    # 开发者资源
    'raw.githubusercontent.com',
    'gist.githubusercontent.com',
    'objects.githubusercontent.com',
    'github.com',
    # 文件分享
    'dl.dropboxusercontent.com',
    'drive.google.com',
]

# ========== 禁止的 IP/网段（SSRF 防护） ==========
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('169.254.169.254/32'),
]

# ========== 允许的 Content-Type ==========
ALLOWED_CONTENT_TYPES = set(UserFile.ALLOWED_MIME_TYPES.keys())

# ========== 常量 ==========
HEAD_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 30
CHUNK_SIZE = 64 * 1024  # 64 KB


def is_domain_allowed(url: str) -> bool:
    """检查 URL 域名是否在白名单中（支持子域名匹配）"""
    hostname = urlparse(url).hostname
    if not hostname:
        return False
    whitelist = getattr(settings, 'FILE_SERVICE_URL_WHITELIST', DEFAULT_URL_DOMAIN_WHITELIST)
    for allowed in whitelist:
        if hostname == allowed or hostname.endswith('.' + allowed):
            return True
    return False


def _check_ip_blocked(hostname: str) -> tuple[bool, str]:
    """DNS 解析后检查 IP 是否在黑名单中"""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True, f"无法解析域名: {hostname}"

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for blocked in BLOCKED_IP_RANGES:
            if ip in blocked:
                return True, "目标地址不被允许（内网/保留地址）"
    return False, ""


def _extract_filename(response, url: str) -> str:
    """从 Content-Disposition 或 URL 路径提取文件名"""
    cd = response.headers.get('Content-Disposition', '')
    if cd:
        # filename*=UTF-8''xxx or filename="xxx"
        match = re.search(r"filename\*=(?:UTF-8''|utf-8'')(.+?)(?:;|$)", cd, re.I)
        if match:
            return unquote(match.group(1).strip().strip('"'))
        match = re.search(r'filename=[""]?([^";\n]+)', cd)
        if match:
            return unquote(match.group(1).strip().strip('"'))

    # 从 URL 路径提取
    path = urlparse(url).path
    name = os.path.basename(path)
    if name:
        return unquote(name)[:255]
    return 'downloaded_file'


def fetch_url(url: str, user) -> dict:
    """
    从 URL 下载文件，返回类文件对象。

    Returns:
        {"success": True, "file_obj": InMemoryUploadedFile, "filename": str, ...}
        或 {"success": False, "error": str}
    """
    # 1. 协议校验
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return {"success": False, "error": "仅支持 http/https 协议"}
    if not parsed.hostname:
        return {"success": False, "error": "URL 格式错误"}

    # 2. 域名白名单
    if not is_domain_allowed(url):
        return {"success": False, "error": "该域名不在允许的白名单中"}

    # 3. DNS → IP 检查
    blocked, reason = _check_ip_blocked(parsed.hostname)
    if blocked:
        return {"success": False, "error": reason}

    # 4. HEAD 预检
    try:
        head = requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True,
                             headers={'User-Agent': 'UniScheduler-FileService/1.0'})
    except requests.RequestException as e:
        return {"success": False, "error": f"HEAD 请求失败: {e}"}

    content_type = head.headers.get('Content-Type', '').split(';')[0].strip().lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        return {"success": False, "error": f"不支持的文件类型: {content_type}"}

    content_length = head.headers.get('Content-Length')
    quota = UserStorageQuota.get_or_create_for_user(user)
    if content_length:
        cl = int(content_length)
        if cl > quota.max_file_size:
            max_mb = quota.max_file_size / (1024 * 1024)
            return {"success": False, "error": f"文件大小超过限制（上限 {max_mb:.0f}MB）"}

    # 5. 流式下载
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True,
                            headers={'User-Agent': 'UniScheduler-FileService/1.0'})
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"success": False, "error": f"下载失败: {e}"}

    # 再次获取实际 content_type
    actual_ct = resp.headers.get('Content-Type', '').split(';')[0].strip().lower()
    if actual_ct and actual_ct not in ALLOWED_CONTENT_TYPES:
        resp.close()
        return {"success": False, "error": f"不支持的文件类型: {actual_ct}"}
    if actual_ct:
        content_type = actual_ct

    filename = _extract_filename(resp, url)

    # 流式读取到内存
    from io import BytesIO
    buf = BytesIO()
    downloaded = 0
    max_size = quota.max_file_size

    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
        downloaded += len(chunk)
        if downloaded > max_size:
            resp.close()
            return {"success": False, "error": f"文件大小超过限制（上限 {max_size // (1024 * 1024)}MB）"}
        buf.write(chunk)

    resp.close()
    buf.seek(0)

    file_obj = InMemoryUploadedFile(
        file=buf,
        field_name='file',
        name=filename,
        content_type=content_type or 'application/octet-stream',
        size=downloaded,
        charset=None,
    )

    return {
        "success": True,
        "file_obj": file_obj,
        "filename": filename,
        "mime_type": content_type or 'application/octet-stream',
        "file_size": downloaded,
    }
