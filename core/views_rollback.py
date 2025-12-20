import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from reversion.models import Revision, Version
from .models import AgentTransaction
from logger import logger

@csrf_exempt
@require_http_methods(["POST"])
def rollback_transaction_impl(request):
    """
    回滚指定 session_id 的上一次操作。
    """
    # 鉴权逻辑 (参考 views_events.py)
    if not request.user.is_authenticated:
        # 尝试 Token 认证
        # 注意：这里不能直接调用 views_token.verify_token，因为它是一个 DRF 视图，返回的是 Response 对象
        # 我们需要手动进行 Token 验证
        from rest_framework.authtoken.models import Token
        
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Token '):
            token_key = auth_header.split(' ')[1]
            try:
                token = Token.objects.get(key=token_key)
                request.user = token.user
            except Token.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Invalid Token'}, status=401)
        else:
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)

    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')

        if not session_id:
            return JsonResponse({'status': 'error', 'message': 'Missing session_id'}, status=400)

        # 查找该会话最近一次未回滚的事务
        # 支持 target_timestamp 参数，用于回滚到指定时间点
        target_timestamp = data.get('target_timestamp')
        
        if target_timestamp:
            # 如果指定了时间戳，查找所有在该时间戳之后发生的未回滚事务
            transactions = AgentTransaction.objects.filter(
                session_id=session_id,
                is_reverted=False,
                timestamp__gt=target_timestamp
            ).order_by('-timestamp')
            
            if not transactions.exists():
                return JsonResponse({
                    'status': 'error', 
                    'message': 'No reversible transactions found after the specified timestamp.'
                }, status=404)
                
            reverted_transactions = []
            for transaction in transactions:
                # 执行回滚逻辑 (封装为函数以便复用)
                result = _revert_single_transaction(transaction)
                if result['success']:
                    reverted_transactions.append(result['info'])
                else:
                    # 如果中间出错，可能需要中断或继续，这里选择继续尝试回滚其他的
                    logger.error(f"Failed to revert transaction {transaction.id}: {result['error']}")
            
            return JsonResponse({
                'status': 'success',
                'message': f"Successfully reverted {len(reverted_transactions)} transactions.",
                'data': {
                    'reverted_transactions': reverted_transactions
                }
            })
            
        else:
            # 原有逻辑：只回滚最后一个
            transaction = AgentTransaction.objects.filter(
                session_id=session_id,
                is_reverted=False
            ).order_by('-timestamp').first()

            if not transaction:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'No reversible transaction found for this session.'
                }, status=404)

            result = _revert_single_transaction(transaction)
            if result['success']:
                return JsonResponse({
                    'status': 'success',
                    'message': f"Successfully reverted action: {transaction.description}",
                    'data': result['info']
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': f"Failed to revert transaction: {result['error']}"
                }, status=500)

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in rollback: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def _revert_single_transaction(transaction):
    """
    回滚单个事务的辅助函数
    """
    try:
        reverted_count = 0
        for version in transaction.revision.version_set.all():
            # 找到该对象在此次 Revision 之前的最新版本
            previous_version = Version.objects.filter(
                object_id=version.object_id,
                content_type=version.content_type,
                revision__date_created__lt=transaction.revision.date_created
            ).order_by('-revision__date_created').first()
            
            if previous_version:
                previous_version.revert()
                logger.info(f"Reverted object {version.object_repr} to previous version from {previous_version.revision.date_created}")
                reverted_count += 1
            else:
                # 如果没有前一个版本，说明该对象是在此次操作中创建的
                model_class = version.content_type.model_class()
                try:
                    instance = model_class.objects.get(pk=version.object_id)
                    instance.delete()
                    logger.info(f"Deleted object {version.object_repr} as no previous version was found (Undo Creation)")
                    reverted_count += 1
                except model_class.DoesNotExist:
                    pass

        transaction.is_reverted = True
        transaction.save()
        
        logger.info(f"Successfully reverted transaction {transaction.id}. Reverted {reverted_count} objects.")
        
        return {
            'success': True,
            'info': {
                'action_type': transaction.action_type,
                'timestamp': transaction.timestamp.isoformat(),
                'description': transaction.description
            }
        }
        
    except Exception as e:
        logger.error(f"Error reverting transaction {transaction.id}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in rollback: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
