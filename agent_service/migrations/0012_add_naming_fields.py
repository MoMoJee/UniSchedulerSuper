# Generated manually for auto-naming feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent_service', '0011_add_summary_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentsession',
            name='is_naming',
            field=models.BooleanField(default=False, help_text='是否正在自动命名'),
        ),
        migrations.AddField(
            model_name='agentsession',
            name='is_auto_named',
            field=models.BooleanField(default=False, help_text='是否已自动命名过'),
        ),
    ]
