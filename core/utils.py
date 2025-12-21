# core/utils.py

from core.models import BitacoraAccion
from django.contrib.auth.models import User
from typing import Optional, Dict
import os
from django.conf import settings
from django.contrib.staticfiles import finders
from io import BytesIO
from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa
from urllib.parse import unquote

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
    # Decodificar URI (%20 -> espacio)
    uri = unquote(uri)
    
    # Manejar prefijo file://
    if uri.startswith("file:///"):
        uri = uri[8:]
    elif uri.startswith("file://"):
        uri = uri[7:]
        
    # Normalizar ruta (backslashes en windows)
    uri = os.path.normpath(uri)

    # 1. Chequeo directo (Ruta absoluta)
    if os.path.exists(uri):
        return uri

    # 2. Chequeo relativo a STATIC_ROOT (si está definido) y BASE_DIR/static
    try:
        # Intento manual con staticfiles (si STATIC_ROOT existe)
        if settings.STATIC_ROOT:
            static_path = os.path.join(settings.STATIC_ROOT, uri)
            if os.path.exists(static_path):
                return static_path
        
        # Intento manual con static source (desarrollo)
        base_static = os.path.join(settings.BASE_DIR, 'static', uri)
        if os.path.exists(base_static):
            return base_static
            
        # Intento con MEDIA_ROOT
        if settings.MEDIA_ROOT:
            media_path = os.path.join(settings.MEDIA_ROOT, uri)
            if os.path.exists(media_path):
                return media_path

    except Exception as e:
        print(f"Error checking paths: {e}")

    # 3. Fallback a Django finders (último recurso)
    try:
        result = finders.find(uri)
        if result:
            if not isinstance(result, (list, tuple)):
                result = [result]
            result = list(os.path.realpath(path) for path in result)
            return result[0]
    except Exception as e:
        pass

    return uri

def render_to_pdf(template_src, context_dict={}):
    """
    Renderiza un template a PDF usando xhtml2pdf.
    """
    template = get_template(template_src)
    html  = template.render(context_dict)
    result = BytesIO()
    
    # link_callback se usa para resolver rutas de imágenes y css
    # Se pasa el encoding UTF-8 para evitar problemas de caracteres
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result, link_callback=link_callback)
    
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return HttpResponse("Error generating PDF", status=500)