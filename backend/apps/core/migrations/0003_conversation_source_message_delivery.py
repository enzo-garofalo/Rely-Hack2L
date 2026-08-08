# E10 · WhatsApp real: origem da conversa (roteia a resposta) e estado de
# entrega da mensagem de saída (falha de transporte fica visível).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_orderversion_context_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='source',
            field=models.CharField(
                choices=[('simulated', 'Chat simulado'), ('whatsapp_web', 'WhatsApp real (gateway)')],
                default='simulated',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='delivery_status',
            field=models.CharField(
                choices=[
                    ('not_applicable', 'Não se aplica'),
                    ('pending', 'Aguardando envio'),
                    ('sent', 'Enviada'),
                    ('failed', 'Falha no envio'),
                ],
                default='not_applicable',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='message',
            name='delivery_error',
            field=models.TextField(blank=True),
        ),
    ]
