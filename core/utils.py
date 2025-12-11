from core.models import BitacoraAccion

def registrar_bitacora_simple(
    usuario, 
    accion: str, 
    entidad_id, 
    detalles: dict = None
):
    """Crea un registro de acción en la tabla de bitácora."""
    
    if detalles is None:
        detalles = {}
        
    # Maneja usuarios no autenticados (importante si registras acciones internas)
    if usuario and not usuario.is_authenticated:
        usuario = None
    
    try:
        registro = BitacoraAccion.objects.create(
            usuario=usuario,
            accion=accion,
            entidad_id=str(entidad_id),
            detalles=detalles
        )
        
        # Ahora puedes imprimir el PK del objeto que acabas de crear
        print(f"✅ ¡BITÁCORA REGISTRADA EXITOSAMENTE!: ID {registro.pk} | Acción: {registro.accion}")
        
    except Exception as e:
        # Se debe loggear el error, pero permitir que la transacción continúe.
        print(f"❌ ERROR AL REGISTRAR BITÁCORA SIMPLE: {e}")