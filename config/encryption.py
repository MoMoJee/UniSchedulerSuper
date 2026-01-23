"""
API 密钥加密存储模块

行业常用方案：
1. AES-256 对称加密 - 用于加密存储敏感数据
2. 密钥派生 - 使用 PBKDF2 或 Argon2 从主密钥派生加密密钥
3. 每个用户独立的加密密钥（基于用户ID + 主密钥派生）
4. 数据库存储加密后的密文 + 初始化向量(IV)

本模块实现：
- AES-256-GCM 加密（提供认证加密，防篡改）
- 使用 Django SECRET_KEY 作为主密钥源
- 为每个用户派生独立的加密密钥
- 支持密钥轮换（通过版本标记）

使用方式：
    from config.encryption import SecureKeyStorage
    
    # 加密存储
    encrypted = SecureKeyStorage.encrypt_api_key(api_key, user_id)
    
    # 解密读取
    api_key = SecureKeyStorage.decrypt_api_key(encrypted, user_id)
"""

import os
import base64
import hashlib
import logging
from typing import Optional, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings

logger = logging.getLogger(__name__)

# 加密版本标记，用于将来的密钥轮换
ENCRYPTION_VERSION = "v1"

# 加密前缀，用于识别已加密的值
ENCRYPTED_PREFIX = "$ENCRYPTED$"


class SecureKeyStorage:
    """安全密钥存储类"""
    
    # 缓存派生的密钥，避免重复计算
    _key_cache = {}
    
    @classmethod
    def _get_master_key(cls) -> bytes:
        """
        获取主密钥
        使用 Django SECRET_KEY 作为主密钥源
        """
        secret_key = getattr(settings, 'SECRET_KEY', '')
        if not secret_key:
            raise ValueError("Django SECRET_KEY 未配置")
        
        # 使用 SHA-256 生成固定长度的主密钥
        return hashlib.sha256(secret_key.encode()).digest()
    
    @classmethod
    def _derive_user_key(cls, user_id: int) -> bytes:
        """
        为用户派生独立的加密密钥
        
        使用 PBKDF2 从主密钥 + 用户ID 派生 256 位密钥
        这样即使数据库泄露，没有主密钥也无法解密
        """
        cache_key = f"user_{user_id}"
        if cache_key in cls._key_cache:
            return cls._key_cache[cache_key]
        
        master_key = cls._get_master_key()
        
        # 使用用户 ID 作为盐值的一部分
        salt = f"unischeduler_user_{user_id}_salt".encode()
        
        # PBKDF2 密钥派生
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for AES-256
            salt=salt,
            iterations=100000,  # 推荐迭代次数
        )
        
        derived_key = kdf.derive(master_key)
        cls._key_cache[cache_key] = derived_key
        
        return derived_key
    
    @classmethod
    def encrypt_api_key(cls, api_key: str, user_id: int) -> str:
        """
        加密 API 密钥
        
        Args:
            api_key: 明文 API 密钥
            user_id: 用户 ID
        
        Returns:
            加密后的字符串，格式: $ENCRYPTED$v1$<nonce_base64>$<ciphertext_base64>
        """
        if not api_key:
            return ""
        
        # 如果已经是加密的，直接返回
        if api_key.startswith(ENCRYPTED_PREFIX):
            return api_key
        
        try:
            # 获取用户专属密钥
            key = cls._derive_user_key(user_id)
            
            # 生成随机 nonce（12 bytes for GCM）
            nonce = os.urandom(12)
            
            # 使用 AES-256-GCM 加密
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, api_key.encode('utf-8'), None)
            
            # 编码为 base64
            nonce_b64 = base64.b64encode(nonce).decode('ascii')
            ciphertext_b64 = base64.b64encode(ciphertext).decode('ascii')
            
            # 返回格式化的加密字符串
            return f"{ENCRYPTED_PREFIX}{ENCRYPTION_VERSION}${nonce_b64}${ciphertext_b64}"
            
        except Exception as e:
            logger.error(f"加密 API 密钥失败: {e}")
            raise ValueError(f"加密失败: {e}")
    
    @classmethod
    def decrypt_api_key(cls, encrypted_value: str, user_id: int) -> str:
        """
        解密 API 密钥
        
        Args:
            encrypted_value: 加密后的字符串
            user_id: 用户 ID
        
        Returns:
            明文 API 密钥
        """
        if not encrypted_value:
            return ""
        
        # 如果不是加密格式，直接返回（兼容旧数据）
        if not encrypted_value.startswith(ENCRYPTED_PREFIX):
            return encrypted_value
        
        try:
            # 解析加密字符串
            parts = encrypted_value.split('$')
            # 格式: ['', 'ENCRYPTED', 'v1', '<nonce>', '<ciphertext>']
            if len(parts) != 5:
                logger.warning("加密格式无效，返回原值")
                return encrypted_value
            
            version = parts[2]
            nonce_b64 = parts[3]
            ciphertext_b64 = parts[4]
            
            # 目前只支持 v1
            if version != "v1":
                logger.warning(f"不支持的加密版本: {version}")
                return encrypted_value
            
            # 获取用户专属密钥
            key = cls._derive_user_key(user_id)
            
            # 解码 base64
            nonce = base64.b64decode(nonce_b64)
            ciphertext = base64.b64decode(ciphertext_b64)
            
            # 使用 AES-256-GCM 解密
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            logger.error(f"解密 API 密钥失败: {e}")
            # 解密失败时返回空字符串，避免泄露密文
            return ""
    
    @classmethod
    def is_encrypted(cls, value: str) -> bool:
        """检查值是否已加密"""
        return value.startswith(ENCRYPTED_PREFIX) if value else False
    
    @classmethod
    def encrypt_model_config(cls, config: dict, user_id: int) -> dict:
        """
        加密模型配置中的所有 API 密钥
        
        Args:
            config: 包含 custom_models 的配置字典
            user_id: 用户 ID
        
        Returns:
            加密后的配置字典（原字典的副本）
        """
        if not config:
            return config
        
        result = config.copy()
        
        # 加密 custom_models 中的 api_key
        if 'custom_models' in result:
            encrypted_models = {}
            for model_id, model_config in result['custom_models'].items():
                model_copy = model_config.copy()
                if 'api_key' in model_copy and model_copy['api_key']:
                    model_copy['api_key'] = cls.encrypt_api_key(
                        model_copy['api_key'], user_id
                    )
                encrypted_models[model_id] = model_copy
            result['custom_models'] = encrypted_models
        
        return result
    
    @classmethod
    def decrypt_model_config(cls, config: dict, user_id: int) -> dict:
        """
        解密模型配置中的所有 API 密钥
        
        Args:
            config: 加密的配置字典
            user_id: 用户 ID
        
        Returns:
            解密后的配置字典（原字典的副本）
        """
        if not config:
            return config
        
        result = config.copy()
        
        # 解密 custom_models 中的 api_key
        if 'custom_models' in result:
            decrypted_models = {}
            for model_id, model_config in result['custom_models'].items():
                model_copy = model_config.copy()
                if 'api_key' in model_copy and model_copy['api_key']:
                    model_copy['api_key'] = cls.decrypt_api_key(
                        model_copy['api_key'], user_id
                    )
                decrypted_models[model_id] = model_copy
            result['custom_models'] = decrypted_models
        
        return result
    
    @classmethod
    def mask_api_key(cls, api_key: str) -> str:
        """
        对 API 密钥进行掩码处理，用于日志或显示
        
        例: sk-abc123def456 -> sk-abc1****f456
        """
        if not api_key:
            return ""
        
        # 已加密的显示为 [已加密]
        if cls.is_encrypted(api_key):
            return "[已加密]"
        
        length = len(api_key)
        if length <= 8:
            return "****"
        
        # 保留前4后4，中间用****替换
        return f"{api_key[:4]}****{api_key[-4:]}"


# 便捷函数
def encrypt_api_key(api_key: str, user_id: int) -> str:
    """加密 API 密钥"""
    return SecureKeyStorage.encrypt_api_key(api_key, user_id)


def decrypt_api_key(encrypted_value: str, user_id: int) -> str:
    """解密 API 密钥"""
    return SecureKeyStorage.decrypt_api_key(encrypted_value, user_id)


def is_encrypted(value: str) -> bool:
    """检查是否已加密"""
    return SecureKeyStorage.is_encrypted(value)
