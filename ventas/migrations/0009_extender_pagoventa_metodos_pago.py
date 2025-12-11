# Generated manually for métodos de pago enhancement

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ventas', '0008_alter_auditoriadescuento_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagoventa',
            name='estado',
            field=models.CharField(
                choices=[
                    ('PENDIENTE', 'Pendiente'),
                    ('COMPLETADO', 'Completado'),
                    ('RECHAZADO', 'Rechazado'),
                    ('ANULADO', 'Anulado'),
                ],
                default='COMPLETADO',
                help_text='Estado del pago. Pendiente para transferencias no confirmadas.',
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='vuelto',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Vuelto entregado al cliente (solo para pagos en efectivo)',
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='codigo_referencia',
            field=models.CharField(
                blank=True,
                help_text='Código o número de referencia de la transferencia',
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='banco',
            field=models.CharField(
                blank=True,
                help_text='Banco desde donde se realizó la transferencia',
                max_length=100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='cuenta_origen',
            field=models.CharField(
                blank=True,
                help_text='Número de cuenta desde donde se realizó la transferencia',
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='titular_transferencia',
            field=models.CharField(
                blank=True,
                help_text='Nombre del titular de la cuenta origen',
                max_length=200,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='referencia_transaccion',
            field=models.CharField(
                blank=True,
                help_text='Referencia de transacción de la pasarela de pago',
                max_length=100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='token_tarjeta',
            field=models.CharField(
                blank=True,
                help_text='Token de la transacción (para auditoría, no almacenar datos sensibles)',
                max_length=200,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='ultimos_digitos',
            field=models.CharField(
                blank=True,
                help_text='Últimos 4 dígitos de la tarjeta',
                max_length=4,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='fecha_confirmacion',
            field=models.DateTimeField(
                blank=True,
                help_text='Fecha en que se confirmó el pago (para transferencias)',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='usuario_confirma',
            field=models.ForeignKey(
                blank=True,
                help_text='Usuario que confirmó el pago',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='pagos_confirmados',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='pagoventa',
            name='observaciones',
            field=models.TextField(
                blank=True,
                help_text='Observaciones o notas sobre el pago',
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name='pagoventa',
            options={'ordering': ['-fecha_hora']},
        ),
    ]

