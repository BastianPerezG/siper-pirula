# inventario/utils.py

from django.contrib.contenttypes.models import ContentType
from .models import RegistroBitacora
from django.contrib.auth import get_user_model

User = get_user_model()

def registrar_accion(usuario: User, categoria: str, accion_tipo: str, mensaje: str, objeto_afectado=None, detalles: dict = None):
    """
    Función de utilidad para crear un registro en la Bitácora de Acciones.

    Args:
        usuario (User): Usuario que realizó la acción.
        categoria (str): Categoría general (Ej: 'INVENTARIO', 'VENTA').
        accion_tipo (str): Tipo específico de acción (Ej: 'STOCK_AJUSTE', 'ANULACION').
        mensaje (str): Mensaje de resumen para la lista de la bitácora.
        objeto_afectado (models.Model, opcional): El objeto Django afectado (Ej: un Producto, una Venta).
        detalles (dict, opcional): Diccionario con datos JSON expandidos (Ej: motivos, valores_previos).
    """
    
    content_type_obj = None
    object_id_val = None

    if objeto_afectado:
        # Usar ContentType para registrar qué modelo fue afectado.
        content_type_obj = ContentType.objects.get_for_model(objeto_afectado)
        object_id_val = objeto_afectado.pk

    RegistroBitacora.objects.create(
        usuario=usuario,
        categoria=categoria,
        accion_tipo=accion_tipo,
        mensaje_resumen=mensaje,
        content_type=content_type_obj,
        object_id=object_id_val,
        detalles_json=detalles
    )