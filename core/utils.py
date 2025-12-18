# core/utils.py

from core.models import BitacoraAccion
from django.contrib.auth.models import User
from typing import Optional, Dict
import os
from django.conf import settings
from django.contrib.staticfiles import finders

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

def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those
    resources
    """
    result = finders.find(uri)
    if result:
        if not isinstance(result, (list, tuple)):
            result = [result]
        result = list(os.path.realpath(path) for path in result)
        path=result[0]
    else:
        sUrl = settings.STATIC_URL        # Typically /static/
        sRoot = settings.STATIC_ROOT      # Typically /home/userX/project_static/
        mUrl = settings.MEDIA_URL         # Typically /media/
        mRoot = settings.MEDIA_ROOT       # Typically /home/userX/project_static/media/

        if uri.startswith(mUrl):
            path = os.path.join(mRoot, uri.replace(mUrl, ""))
        elif uri.startswith(sUrl):
            path = os.path.join(sRoot, uri.replace(sUrl, ""))
        else:
            return uri

    # make sure that file exists
    if not os.path.isfile(path):
            # raise Exception(
            #     'media URI must start with %s or %s' % (sUrl, mUrl)
            # )
            pass
    return path

