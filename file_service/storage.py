import hashlib

from django.utils import timezone


def user_file_upload_to(instance, filename):
    """
    生成用户文件存储路径：user_files/<user_id>/YYYY/MM/<uuid8>_<filename>
    """
    import uuid
    unique = f"{uuid.uuid4().hex[:8]}_{filename}"
    return timezone.now().strftime(f'user_files/{instance.user_id}/%Y/%m/{unique}')


def compute_file_hash(uploaded_file) -> str:
    """
    计算上传文件的 SHA-256 哈希值。
    uploaded_file 需要支持 chunks() 或 read()。
    计算前先 seek(0) 确保从头读取（防止流已被前置操作耗尽），
    计算完毕后再 seek 回起始位置以便后续保存。
    """
    sha256 = hashlib.sha256()
    # 先 seek 到起始位置，防止调用方传入已消费的流
    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)
    if hasattr(uploaded_file, 'chunks'):
        for chunk in uploaded_file.chunks():
            sha256.update(chunk)
    else:
        sha256.update(uploaded_file.read())
    # seek 回起始位置以便后续保存
    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)
    return sha256.hexdigest()
