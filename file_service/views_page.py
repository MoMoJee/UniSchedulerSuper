from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def files_page(request):
    """云盘管理页"""
    return render(request, 'file_service/files.html')
