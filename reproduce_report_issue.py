import os
import django
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import datetime

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siper_pirula.settings')
django.setup()

from django.contrib.auth import get_user_model
from core.models import Negocio, PerfilUsuario
from inventario.models import Producto, Categoria
from ventas.models import Venta, VentaItem, PagoVenta

CustomUser = get_user_model()

def reproduce():
    print("--- Starting Reproduction Script ---")
    
    # 1. Get or Create Negocio and User
    user = CustomUser.objects.filter(is_superuser=True).first()
    if not user:
        print("No superuser found. Aborting.")
        return

    try:
        perfil = user.perfilusuario
        negocio = perfil.negocio
        print(f"Using Negocio: {negocio.nombre} and User: {user.username}")
    except:
        print("User has no profile or negocio. Aborting.")
        return

    # 2. Create Dummy Data
    from inventario.models import Proveedor, MovimientoInventario
    proveedor, _ = Proveedor.objects.get_or_create(negocio=negocio, nombre="Prov Test")
    categoria, _ = Categoria.objects.get_or_create(negocio=negocio, nombre="Cat Test")
    
    producto, _ = Producto.objects.get_or_create(
        negocio=negocio,
        sku="TEST001",
        defaults={'nombre': 'Producto Test', 'precio': 1000, 'costo': 500, 'categoria': categoria, 'proveedor': proveedor}
    )
    print(f"Product: {producto.nombre}")

    # Add initial stock
    MovimientoInventario.objects.create(
        producto=producto,
        tipo=MovimientoInventario.TIPO_ENTRADA,
        cantidad=100,
        comentario="Initial stock for test"
    )
    
    # 3. Simulate POS Sale Creation
    print("Simulating POS Sale...")
    
    venta = Venta.objects.create(
        negocio=negocio,
        estado=Venta.EST_ABIERTA, # Initially Open
        doc_tipo=Venta.DOC_BOLETA,
        medio_pago=Venta.MED_EFECTIVO
    )
    
    item = VentaItem.objects.create(
        venta=venta,
        producto=producto,
        cantidad=1,
        precio_unit=producto.precio
    )
    
    # Checkout Logic (Simulated)
    # Validate status change
    venta.monto_total = item.subtotal
    venta.estado = Venta.EST_CERRADA # Changed to CLOSED
    venta.save()
    
    PagoVenta.objects.create(
        venta=venta,
        metodo=PagoVenta.MET_EFECTIVO,
        monto=venta.monto_total,
        estado=PagoVenta.ESTADO_COMPLETADO,
        usuario_registra=user
    )
    
    print(f"Sale #{venta.pk} created. State: {venta.estado}. Date: {venta.fecha}")

    # 4. Simulate Report Logic
    print("Testing Report Query...")
    
    hoy_sistema = timezone.now().date()
    desde = hoy_sistema
    hasta = hoy_sistema
    
    print(f"Filtering from {desde} to {hasta}")
    
    ventas_reporte = Venta.objects.filter(
        negocio=negocio,
        estado=Venta.EST_CERRADA,
    )
    
    # Apply Date Filter
    ventas_reporte = ventas_reporte.filter(fecha__date__gte=desde, fecha__date__lte=hasta)
    
    if ventas_reporte.filter(pk=venta.pk).exists():
        print("SUCCESS: The sale appears in the report query.")
    else:
        print("FAILURE: The sale DOES NOT appear in the report query.")
        print(f"Sale Date (Local): {timezone.localtime(venta.fecha)}")
        print(f"Sale Date (Date): {timezone.localtime(venta.fecha).date()}")
        print(f"Filter Range: {desde} - {hasta}")

if __name__ == "__main__":
    reproduce()
