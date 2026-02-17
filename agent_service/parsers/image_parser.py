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
            
            # 3. OCR 文字提取（仅在模型不支持 vision 时执行）
            if skip_ocr:
                ocr_text = ""
            else:
                ocr_text = self._extract_text_ocr(file_path)
            
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
        按优先级尝试：EasyOCR → pytesseract → 返回空。
        根据 api_keys.json 中的 ocr_services 配置决定可用引擎。
        """
        # 1. 尝试 EasyOCR
        text = self._try_easyocr(file_path)
        if text:
            return text
        
        # 2. 尝试 pytesseract（Tesseract-OCR）
        text = self._try_pytesseract(file_path)
        if text:
            return text
        
        # 3. 所有 OCR 引擎均不可用
        logger.warning("所有 OCR 引擎均不可用 (EasyOCR/Tesseract)，跳过文字提取。"
                     "图片将通过 base64 直接发送给支持视觉的模型。")
        return ""
    
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
                logger.info("首次加载 EasyOCR 模型...")
                ImageParser._ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                logger.info("EasyOCR 模型加载完成")
            
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
            logger.debug("EasyOCR 未安装，尝试其他 OCR 引擎")
            return ""
        except Exception as e:
            logger.warning(f"EasyOCR 提取失败: {e}")
            return ""
    
    def _try_pytesseract(self, file_path: str) -> str:
        """尝试使用 pytesseract (Tesseract-OCR) 提取文字"""
        # 检查 api_keys.json 中 tesseract 是否启用
        try:
            from config.api_keys_manager import APIKeyManager
            config = APIKeyManager._load_config()
            ocr_config = config.get('ocr_services', {})
            tesseract_config = ocr_config.get('tesseract', {})
            if not tesseract_config.get('enabled', False):
                logger.debug("Tesseract 在配置中未启用")
                return ""
        except Exception:
            pass  # 配置读取失败，仍然尝试
        
        try:
            import pytesseract
            from PIL import Image
            
            img = Image.open(file_path)
            # 中文 + 英文识别
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            return text.strip() if text.strip() else ""
            
        except ImportError:
            logger.debug("pytesseract 未安装，跳过 Tesseract OCR")
            return ""
        except Exception as e:
            logger.warning(f"Tesseract OCR 提取失败: {e}")
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
