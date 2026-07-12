import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('agent_service', '0027_agentusagerecord'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentRollbackWindow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('window_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('generation', models.PositiveIntegerField(default=1)),
                ('floor_message_index', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(choices=[('active', '有效'), ('closed', '已关闭')], db_index=True, default='active', max_length=16)),
                ('activation_token', models.CharField(max_length=100, unique=True)),
                ('opened_at', models.DateTimeField(auto_now_add=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rollback_windows', to='agent_service.agentsession')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agent_rollback_windows', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'session', 'status'], name='agent_rollback_window_lookup')],
                'constraints': [models.UniqueConstraint(condition=models.Q(status='active'), fields=('session',), name='agent_one_active_rollback_window')],
            },
        ),
        migrations.AddField(
            model_name='agenttransaction', name='change_set_id',
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agenttransaction', name='message_index',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agenttransaction', name='rollback_window',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transactions', to='agent_service.agentrollbackwindow'),
        ),
        migrations.AddField(
            model_name='agenttransaction', name='source',
            field=models.CharField(blank=True, db_index=True, default='legacy_agent', max_length=32),
        ),
        migrations.AddField(
            model_name='agenttransaction', name='state',
            field=models.CharField(db_index=True, default='applied', max_length=24),
        ),
        migrations.AddField(
            model_name='agenttransaction', name='tool_call_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=255),
        ),
    ]
