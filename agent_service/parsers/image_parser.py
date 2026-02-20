"""
图片解析器

功能：
- 生成 Base64 编码（用于 vision 模型）
- OCR 文字提取（用于非 vision 模型降级）
- 缩略图生成
"""
import os
import base64
from io import BytesIO
from typing import Dict, Any

from .base import BaseParser
from logger import logger


class ImageParser(BaseParser):
    """图片解析器"""
    
    SUPPORTED_MIMES = {
        'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    }
    
    # Vision 模型发送时的最大像素（宽或高）
    MAX_BASE64_DIMENSION = 1024
    
    def can_parse(self, mime_type: str) -> bool:
        return mime_type in self.SUPPORTED_MIMES
    
    def parse(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        解析图片：
        1. 生成压缩后的 base64（用于 vision）
        2. OCR 提取文字（仅在模型不支持 vision 时执行，用于降级）
        
        Kwargs:
            skip_ocr (bool): 当前模型支持 vision 时传 True，跳过耗时的 OCR 流程。
        """
        skip_ocr = kwargs.get('skip_ocr', False)
        filename = os.path.basename(file_path)
        
        try:
            from PIL import Image
        except ImportError:
            return {
                "success": False,
                "text": "",
                "base64": "",
                "metadata": {},
                "error": "需要安装 Pillow 库: pip install Pillow"
            }
        
        try:
            # 1. 读取图片元信息
            with Image.open(file_path) as img:
                metadata = {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode
                }
            
            # 2. 生成压缩后的 base64（限制尺寸以节省 token）
            base64_str = self._generate_base64(file_path)
            base64_len = len(base64_str)
            
            # 3. OCR 文字提取（仅在模型不支持 vision 时执行）
            if skip_ocr:
                ocr_text = ""
                logger.debug(
                    f"[图片解析-Vision模式] 文件={filename}, "
                    f"原始尺寸={metadata['width']}x{metadata['height']}, "
                    f"Base64长度={base64_len:,} 字符, 跳过OCR"
                )
            else:
                ocr_text = self._extract_text_ocr(file_path)
                logger.debug(
                    f"[图片解析-OCR模式] 文件={filename}, "
                    f"原始尺寸={metadata['width']}x{metadata['height']}, "
                    f"提取文字={len(ocr_text)} 字符, Base64长度={base64_len:,} 字符"
                )
            
            return {
                "success": True,
                "text": ocr_text or "[图片，无可识别文字内容]",
                "base64": base64_str,
                "metadata": metadata,
                "error": ""
            }
            
        except Exception as e:
            logger.error(f"图片解析失败 {file_path}: {e}")
            return {
                "success": False,
                "text": "",
                "base64": "",
                "metadata": {},
                "error": str(e)
            }
    
    def _generate_base64(self, file_path: str) -> str:
        """生成压缩后的 Base64 编码"""
        from PIL import Image
        
        with Image.open(file_path) as img:
            # 如果图片过大，先缩放
            if img.width > self.MAX_BASE64_DIMENSION or img.height > self.MAX_BASE64_DIMENSION:
                img.thumbnail(
                    (self.MAX_BASE64_DIMENSION, self.MAX_BASE64_DIMENSION),
                    Image.Resampling.LANCZOS
                )
            
            # 转换为 RGB（处理 RGBA、P 模式）
            if img.mode not in ('RGB', 'L'):
                if img.mode in ('RGBA', 'LA', 'PA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'PA':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert('RGB')
            
            # 编码为 JPEG
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            return base64.b64encode(buffer.read()).decode('utf-8')
    
    def _extract_text_ocr(self, file_path: str) -> str:
        """
        使用 OCR 提取图片中的文字。
        按配置中的降级链优先级尝试：百度云OCR → EasyOCR → pytesseract → 返回空。
        
        降级链由 api_keys.json 的 ocr_services 中各服务的 enabled 字段控制，
        优先级固定为：baidu(云端) → easyocr(本地) → tesseract(本地)。
        """
        from config.api_keys_manager import APIKeyManager
        
        filename = os.path.basename(file_path)
        fallback_chain = APIKeyManager.get_ocr_fallback_chain()
        
        if not fallback_chain:
            logger.warning(f"[OCR] 没有任何已启用的 OCR 服务，跳过文字提取: {filename}")
            return ""
        
        logger.debug(f"[OCR] 降级链: {' → '.join(fallback_chain)}, 文件: {filename}")
        
        dispatch = {
            'baidu': self._try_baidu_ocr,
            'easyocr': self._try_easyocr,
            'tesseract': self._try_pytesseract,
        }
        
        for provider in fallback_chain:
            handler = dispatch.get(provider)
            if not handler:
                continue
            text = handler(file_path)
            if text:
                logger.debug(f"[OCR] {provider} 识别成功: {filename}, 提取 {len(text)} 字符")
                return text
            # handler 返回空串表示该引擎失败/不可用，继续下一个
        
        logger.warning(
            f"[OCR] 所有引擎均未能提取文字 ({', '.join(fallback_chain)}): {filename}。"
            "图片将通过 base64 直接发送给支持视觉的模型。"
        )
        return ""

    # ---- 百度云 OCR ----

    # 类级别 access_token 缓存
    _baidu_access_token: str = ""
    _baidu_token_expires_at: float = 0.0

    def _try_baidu_ocr(self, file_path: str) -> str:
        """
        使用百度云通用文字识别（标准版）提取文字。
        
        API 文档: https://ai.baidu.com/ai-doc/OCR/zk3h7xz52
        """
        import time

        try:
            from config.api_keys_manager import APIKeyManager
            config = APIKeyManager.get_ocr_service_config('baidu')
            if not config:
                logger.debug("[OCR-百度] 未启用或未配置，跳过")
                return ""
        except Exception as e:
            logger.debug(f"[OCR-百度] 读取配置异常: {e}")
            return ""

        api_key = config.get('api_key', '')
        secret_key = config.get('secret_key', '')
        if not api_key or not secret_key:
            logger.warning("[OCR-百度] api_key 或 secret_key 为空，跳过百度云 OCR")
            return ""

        try:
            import requests
            import urllib.parse

            # 1. 获取 / 复用 access_token
            access_token = self._get_baidu_access_token(config)
            if not access_token:
                return ""

            # 2. 读取图片并编码为 base64
            with open(file_path, "rb") as f:
                img_base64 = base64.b64encode(f.read()).decode("utf-8")

            # 3. 调用通用文字识别
            api_url = config.get(
                'api_url',
                'https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic'
            )
            url = f"{api_url}?access_token={access_token}"
            payload = "image=" + urllib.parse.quote_plus(img_base64)
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
            }

            resp = requests.post(url, headers=headers, data=payload.encode("utf-8"), timeout=15)
            resp.encoding = "utf-8"
            result = resp.json()

            # 4. 解析结果
            if 'error_code' in result:
                error_code = result.get('error_code')
                error_msg = result.get('error_msg', '')
                logger.warning(
                    f"[OCR-百度] API 错误 (code={error_code}): {error_msg}。"
                    "云端 OCR 不可用，将尝试本地 OCR 引擎。"
                )
                # token 过期时清除缓存，下次重新获取
                if error_code in (110, 111):
                    ImageParser._baidu_access_token = ""
                    ImageParser._baidu_token_expires_at = 0.0
                return ""

            words_list = result.get('words_result', [])
            text = '\n'.join(item.get('words', '') for item in words_list)
            logger.debug(
                f"[OCR-百度] 成功: {len(words_list)} 行, "
                f"{len(text)} 字符, log_id={result.get('log_id', 'N/A')}"
            )
            return text.strip()

        except requests.exceptions.Timeout:
            logger.warning("[OCR-百度] 请求超时 (15s)，将尝试本地 OCR 引擎")
            return ""
        except requests.exceptions.ConnectionError:
            logger.warning("[OCR-百度] 网络连接失败，将尝试本地 OCR 引擎")
            return ""
        except Exception as e:
            logger.warning(f"[OCR-百度] 异常: {e}，将尝试本地 OCR 引擎")
            return ""

    def _get_baidu_access_token(self, config: dict) -> str:
        """
        获取百度云 access_token，带类级别缓存（有效期内复用）。
        
        Returns:
            access_token 字符串，失败返回空字符串
        """
        import time

        # 缓存仍有效（提前 5 分钟刷新）
        if (ImageParser._baidu_access_token
                and time.time() < ImageParser._baidu_token_expires_at - 300):
            return ImageParser._baidu_access_token

        try:
            import requests

            token_url = config.get(
                'token_url',
                'https://aip.baidubce.com/oauth/2.0/token'
            )
            params = {
                "grant_type": "client_credentials",
                "client_id": config['api_key'],
                "client_secret": config['secret_key'],
            }
            resp = requests.post(token_url, params=params, timeout=10)
            data = resp.json()

            token = data.get('access_token', '')
            expires_in = data.get('expires_in', 0)  # 通常 2592000 秒（30天）

            if not token:
                error = data.get('error_description', data.get('error', '未知错误'))
                logger.warning(
                    f"[OCR-百度] 获取 access_token 失败: {error}。"
                    "请检查 api_keys.json 中 baidu.api_key / secret_key 是否正确。"
                )
                return ""

            # 缓存
            ImageParser._baidu_access_token = token
            ImageParser._baidu_token_expires_at = time.time() + expires_in
            logger.info(
                f"[OCR-百度] access_token 获取成功，有效期 {expires_in // 86400} 天"
            )
            return token

        except Exception as e:
            logger.warning(f"[OCR-百度] 获取 access_token 异常: {e}")
            return ""

    # ---- EasyOCR (本地) ----

    def _try_easyocr(self, file_path: str) -> str:
        """
        尝试使用 EasyOCR 提取文字
        
        注意：EasyOCR 使用 OpenCV，在 Windows 上不支持中文路径。
        改用 PIL 读取图片并转换为 numpy 数组传递给 EasyOCR。
        """
        try:
            import easyocr
            import numpy as np
            from PIL import Image
            
            # 使用类级别缓存避免重复加载模型
            if not hasattr(ImageParser, '_ocr_reader'):
                logger.info("[OCR-EasyOCR] 首次加载模型...")
                ImageParser._ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                logger.info("[OCR-EasyOCR] 模型加载完成")
            
            # 使用 PIL 读取图片（支持中文路径）
            img = Image.open(file_path)
            # 转换为 RGB（EasyOCR 需要 RGB 格式）
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # 转换为 numpy 数组
            img_array = np.array(img)
            
            # 使用 numpy 数组调用 EasyOCR（避免中文路径问题）
            results = ImageParser._ocr_reader.readtext(img_array, detail=0)
            text = '\n'.join(results)
            return text.strip() if text.strip() else ""
            
        except ImportError:
            logger.debug("[OCR-EasyOCR] 未安装，尝试其他 OCR 引擎")
            return ""
        except Exception as e:
            logger.warning(f"[OCR-EasyOCR] 提取失败: {e}")
            return ""

    # ---- Tesseract (本地) ----

    def _try_pytesseract(self, file_path: str) -> str:
        """尝试使用 pytesseract (Tesseract-OCR) 提取文字"""
        try:
            import pytesseract
            from PIL import Image
            
            img = Image.open(file_path)
            # 中文 + 英文识别
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            return text.strip() if text.strip() else ""
            
        except ImportError:
            logger.debug("[OCR-Tesseract] pytesseract 未安装，跳过")
            return ""
        except Exception as e:
            logger.warning(f"[OCR-Tesseract] 提取失败: {e}")
            return ""
    
    def generate_thumbnail(self, file_path: str, output_path: str,
                          size: tuple = (200, 200)) -> bool:
        """生成缩略图"""
        try:
            from PIL import Image
            
            with Image.open(file_path) as img:
                # 转换为 RGB
                if img.mode not in ('RGB', 'L'):
                    if img.mode in ('RGBA', 'LA', 'PA'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'PA':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1])
                        img = background
                    else:
                        img = img.convert('RGB')
                
                # 生成缩略图（保持宽高比）
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # 确保输出目录存在
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                img.save(output_path, 'JPEG', quality=80, optimize=True)
                
                return True
        except Exception as e:
            logger.error(f"生成缩略图失败: {e}")
            return False
