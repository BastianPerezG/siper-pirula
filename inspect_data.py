import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siper_pirula.settings')
django.setup()

from ventas.models import Venta
from core.models import Negocio

def inspect():
    print("--- Inspecting Sales Data ---")
    
    # 1. Count by Status
    print("\nStats by State:")
    for status in [Venta.EST_ABIERTA, Venta.EST_CERRADA, Venta.EST_ANULADA]:
        count = Venta.objects.filter(estado=status).count()
        print(f"  {status}: {count}")

    # 2. Check recent sales (last 10)
    print("\nLast 10 Sales:")
    last_sales = Venta.objects.all().order_by('-fecha')[:10]
    for v in last_sales:
        local_date = timezone.localtime(v.fecha)
        print(f"  #{v.pk} | {local_date} | {v.estado} | {v.negocio.nombre} | ${v.monto_total} | Pedido: {v.pedido_id}")

    # 3. Check for 'stuck' POS sales (ABIERTA but created recently)
    print("\nRecent OPEN Sales (Possible Stacked POS Sales):")
    open_sales = Venta.objects.filter(estado=Venta.EST_ABIERTA).order_by('-fecha')[:10]
    for v in open_sales:
         local_date = timezone.localtime(v.fecha)
         print(f"  #{v.pk} | {local_date} | Items: {v.items.count()} | Created by: {v.usuario_creador if hasattr(v, 'usuario_creador') else 'Unknown'}")

    # 4. Check Business Info
    print("\nNegocios:")
    for n in Negocio.objects.all():
        print(f"  ID: {n.pk} | {n.nombre}")

if __name__ == "__main__":
    inspect()
