from django.urls import path

from file_service import views_api

urlpatterns = [
    # 文件列表
    path('', views_api.list_files, name='file_list'),

    # 文件上传
    path('upload/', views_api.upload_files, name='file_upload'),
    path('upload-url/', views_api.upload_from_url, name='file_upload_url'),

    # 文件夹
    path('folders/', views_api.create_folder, name='folder_create'),
    path('folders/<int:folder_id>/', views_api.delete_folder, name='folder_delete'),
    path('folders/<int:folder_id>/rename/', views_api.rename_folder, name='folder_rename'),

    # 搜索
    path('search/', views_api.search_files, name='file_search'),

    # 聊天页文件选择
    path('pick/', views_api.pick_files, name='file_pick'),

    # 配额
    path('quota/', views_api.get_quota, name='file_quota'),

    # 单文件操作
    path('<int:file_id>/', views_api.get_file, name='file_detail'),
    path('<int:file_id>/rename/', views_api.rename_file, name='file_rename'),
    path('<int:file_id>/move/', views_api.move_file, name='file_move'),
    path('<int:file_id>/download/', views_api.download_file, name='file_download'),
    path('<int:file_id>/download-md/', views_api.download_markdown, name='file_download_md'),
    path('<int:file_id>/markdown/', views_api.file_markdown, name='file_markdown'),
]
