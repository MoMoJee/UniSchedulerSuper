import json
import time
from logger import logger

class RequestLogMiddleware:
    """
    中间件：记录所有 HTTP 请求到统一日志文件
    格式类似标准访问日志：IP - Method Path Status ResponseTime
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 记录开始时间
        start_time = time.time()
        
        # 处理请求
        response = self.get_response(request)
        
        # 计算响应时间
        duration = time.time() - start_time
        
        # 记录访问日志
        self.log_request(request, response, duration)
        
        return response

    def log_request(self, request, response, duration):
        try:
            # 获取客户端 IP
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR', '-')
            
            # 获取用户信息
            user = '-'
            if hasattr(request, 'user') and request.user.is_authenticated:
                user = request.user.username
            
            # 构建日志消息（类似 Apache/Nginx 格式）
            log_message = (
                f'{ip} - {user} - '
                f'"{request.method} {request.get_full_path()}" '
                f'{response.status_code} '
                f'{response.get("Content-Length", "-")} '
                f'{duration:.3f}s'
            )

            # 根据状态码选择日志级别
            if response.status_code >= 500:
                logger.error(log_message)
            elif 400 <= response.status_code < 500:
                logger.warning(log_message)
            elif 300 <= response.status_code < 400:
                logger.info(log_message)
            else:
                logger.debug(log_message)
            
        except Exception as e:
            logger.error(f"Error in RequestLogMiddleware: {e}")


class RequestDebugMiddleware:
    """
    调试中间件：记录详细的请求信息（包括 headers, body 等）
    仅在需要深度调试时使用，会产生大量日志
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 在视图处理之前记录请求
        self.log_request_debug(request)
        
        response = self.get_response(request)
        
        return response

    def log_request_debug(self, request):
        try:
            # 获取所有 Headers
            headers = dict(request.headers)
            
            # 构建详细日志
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
            
            # 写入调试日志
            logger.debug("\n".join(log_message))
            
        except Exception as e:
            logger.error(f"Error in RequestDebugMiddleware: {e}")

