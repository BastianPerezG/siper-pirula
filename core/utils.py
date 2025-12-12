# core/utils.py

from core.models import BitacoraAccion
from django.contrib.auth.models import User
from typing import Optional, Dict

def registrar_bitacora_estructurada(
    negocio:str,
    usuario: Optional[User], 
    accion: str, # Esto será el título o resumen
    tipo_accion: str, # Ejemplo: 'CREATION', 'EDITION'
    nombre_modelo: str, # Ejemplo: 'Inventario', 'Usuario'
    entidad_id, 
    detalles: Dict = None
):
    """
    Crea un registro de acción estructurado para permitir un renderizado dinámico.
    """
    
    if detalles is None:
        detalles = {}
        
    # Maneja usuarios no autenticados
    if usuario and not usuario.is_authenticated:
        usuario = None
    
    try:
        registro = BitacoraAccion.objects.create(
            negocio=negocio,
            usuario=usuario,
            accion=accion, # El título
            tipo_accion=tipo_accion, # El nuevo campo clave
            nombre_modelo=nombre_modelo, # El nuevo campo clave
            entidad_id=str(entidad_id),
            detalles=detalles
        )
        
        print(f"✅ BITÁCORA ESTRUCTURADA REGISTRADA: ID {registro.pk} | Acción: {registro.accion} | Modelo: {registro.nombre_modelo}")
        
    except Exception as e:
        # Se debe loggear el error
        print(f"❌ ERROR AL REGISTRAR BITÁCORA ESTRUCTURADA: {e}")