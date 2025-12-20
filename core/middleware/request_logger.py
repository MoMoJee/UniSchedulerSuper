import logging
import json
from logger import logger

class RequestLogMiddleware:
    """
    中间件：记录所有进入的请求的详细信息，用于调试 Token 认证问题。
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 在视图处理之前记录请求
        self.log_request(request)
        
        response = self.get_response(request)
        
        return response

    def log_request(self, request):
        try:
            # 获取所有 Headers
            # request.headers 是一个 CaseInsensitiveMapping，转换为 dict
            headers = dict(request.headers)
            
            # 构建日志数据
            log_message = [
                f"=== Incoming Request Debug Info ===",
                f"Path: {request.path}",
                f"Method: {request.method}",
                f"Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}",
            ]
            
            # 特别检查 Authorization
            auth = request.headers.get('Authorization')
            if auth:
                log_message.append(f"Authorization Header: '{auth}'")
                if auth.startswith('Token '):
                    token = auth.split(' ')[1]
                    log_message.append(f"Token Value: '{token}'")
                else:
                    log_message.append(f"Authorization format warning: Should start with 'Token '")
            else:
                log_message.append("WARNING: No Authorization header present!")

            # 记录 GET 参数
            if request.GET:
                log_message.append(f"GET Params: {request.GET.dict()}")

            # 记录 Body (如果是 JSON)
            if request.content_type == 'application/json':
                try:
                    body = json.loads(request.body)
                    log_message.append(f"Body (JSON): {json.dumps(body, indent=2, ensure_ascii=False)}")
                except:
                    log_message.append(f"Body: {request.body.decode('utf-8', errors='ignore')}")
            
            log_message.append("=====================================")
            
            # 写入日志
            logger.info("\n".join(log_message))
            
        except Exception as e:
            logger.error(f"Error in RequestLogMiddleware: {e}")
