"""
Token 认证相关视图函数
支持 Token 的创建、获取、刷新和删除
"""

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from logger import logger
from core.utils.validators import validate_body

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@validate_body({
    'username': {'type': str, 'required': True, 'comment': '用户名'},
    'password': {'type': str, 'required': True, 'comment': '密码'},
})
def api_login(request):
    """
    API 登录接口 - 用户名密码换取 Token
    
    POST /api/auth/login/
    Body: {
        "username": "用户名",
        "password": "密码"
    }
    
    Returns: {
        "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
        "user_id": 1,
        "username": "admin",
        "email": "admin@example.com"
    }
    """
    try:
        data = request.validated_data
        username = data.get('username')
        password = data.get('password')
        
        # 认证用户
        user = authenticate(username=username, password=password)
        
        if user is None:
            return Response(
                {'error': '用户名或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # 获取或创建 Token
        token, created = Token.objects.get_or_create(user=user)
        
        logger.info(f"User {username} logged in via API, token {'created' if created else 'retrieved'}")
        
        return Response({
            'token': token.key,
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'created': created
        })
        
    except Exception as e:
        logger.error(f"API login error: {str(e)}")
        return Response(
            {'error': f'登录失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_logout(request):
    """
    API 登出接口 - 删除 Token
    
    POST /api/auth/logout/
    Header: Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
    
    Returns: {
        "message": "登出成功"
    }
    """
    try:
        # 删除用户的 Token
        request.user.auth_token.delete()
        logger.info(f"User {request.user.username} logged out via API, token deleted")
        
        return Response({
            'message': '登出成功'
        })
        
    except Exception as e:
        logger.error(f"API logout error: {str(e)}")
        return Response(
            {'error': f'登出失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_token(request):
    """
    获取当前用户的 Token
    
    GET /api/auth/token/
    需要已登录（Session 或 Token）
    
    Returns: {
        "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
        "user_id": 1,
        "username": "admin"
    }
    """
    try:
        # 获取或创建 Token
        token, created = Token.objects.get_or_create(user=request.user)
        
        return Response({
            'token': token.key,
            'user_id': request.user.id,
            'username': request.user.username,
            'created': created
        })
        
    except Exception as e:
        logger.error(f"Get token error: {str(e)}")
        return Response(
            {'error': f'获取 Token 失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh_token(request):
    """
    刷新 Token - 删除旧的，创建新的
    
    POST /api/auth/token/refresh/
    Header: Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
    
    Returns: {
        "token": "新的token字符串",
        "message": "Token 已刷新"
    }
    """
    try:
        # 删除旧 Token
        request.user.auth_token.delete()
        
        # 创建新 Token
        new_token = Token.objects.create(user=request.user)
        
        logger.info(f"User {request.user.username} refreshed token via API")
        
        return Response({
            'token': new_token.key,
            'message': 'Token 已刷新'
        })
        
    except Exception as e:
        logger.error(f"Refresh token error: {str(e)}")
        return Response(
            {'error': f'刷新 Token 失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_token(request):
    """
    删除 Token
    
    DELETE /api/auth/token/
    Header: Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
    
    Returns: {
        "message": "Token 已删除"
    }
    """
    try:
        request.user.auth_token.delete()
        logger.info(f"User {request.user.username} deleted token via API")
        
        return Response({
            'message': 'Token 已删除'
        })
        
    except Exception as e:
        logger.error(f"Delete token error: {str(e)}")
        return Response(
            {'error': f'删除 Token 失败: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verify_token(request):
    """
    验证 Token 是否有效
    
    GET /api/auth/token/verify/
    Header: Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
    
    Returns: {
        "valid": true,
        "user_id": 1,
        "username": "admin"
    }
    """
    return Response({
        'valid': True,
        'user_id': request.user.id,
        'username': request.user.username,
        'email': request.user.email
    })


@login_required
def token_management_page(request):
    """
    已弃用
    Token 管理页面 - 显示用户的 Token 并提供管理功能
    """
    from django.shortcuts import render
    
    try:
        token, created = Token.objects.get_or_create(user=request.user)
        context = {
            'token': token.key,
            'user': request.user,
            'token_created': created
        }
        return render(request, 'token_management.html', context)
    except Exception as e:
        logger.error(f"Token management page error: {str(e)}")
        context = {
            'error': str(e),
            'user': request.user
        }
        return render(request, 'token_management.html', context)
