from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agent_service', '0023_add_last_llm_request_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentsession',
            name='summary_trigger_count',
            field=models.IntegerField(
                default=0,
                help_text='触发本次总结时 state 中的消息数量'
            ),
        ),
    ]
