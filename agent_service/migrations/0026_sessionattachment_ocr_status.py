from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent_service', '0025_add_cloud_file_to_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessionattachment',
            name='ocr_status',
            field=models.CharField(
                choices=[
                    ('pending', '待 OCR'),
                    ('processing', 'OCR 中'),
                    ('completed', 'OCR 已完成'),
                    ('failed', 'OCR 失败'),
                    ('skipped', '已跳过 OCR'),
                ],
                default='pending',
                help_text='图片 OCR 状态；用于模型从多模态切换到纯文本时做发送前校验',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='sessionattachment',
            name='ocr_attempted_at',
            field=models.DateTimeField(blank=True, help_text='最近 OCR 执行时间', null=True),
        ),
        migrations.AddField(
            model_name='sessionattachment',
            name='ocr_provider',
            field=models.CharField(blank=True, default='', help_text='最近 OCR 使用的 provider', max_length=50),
        ),
        migrations.AddField(
            model_name='sessionattachment',
            name='ocr_error',
            field=models.TextField(blank=True, default='', help_text='OCR 失败原因'),
        ),
    ]
