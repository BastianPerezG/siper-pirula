import os
import django
from django.conf import settings
from django.utils import timezone
import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siper_pirula.settings')
django.setup()

from ventas.models import Venta

def run():
    print(f"USE_TZ = {getattr(settings, 'USE_TZ', 'Not Set (Default True?)')}")
    print(f"TIME_ZONE = {getattr(settings, 'TIME_ZONE', 'Not Set')}")
    
    hoy = timezone.now().date()
    print(f"Hoy (Server Timezone): {hoy}")
    
    # Check Sales Today (Local Time)
    print("\n--- Ventas de Hoy (CERRADA) ---")
    start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    ventas = Venta.objects.filter(
        fecha__gte=start_of_day,
        estado=Venta.EST_CERRADA
    )
    print(f"Count: {ventas.count()}")
    for v in ventas:
        print(f"#{v.id} {v.fecha} {v.monto_total} {v.negocio.nombre}")

    # Check Sales Today (Any Status)
    print("\n--- Ventas de Hoy (Cualquier Estado) ---")
    ventas_all = Venta.objects.filter(fecha__gte=start_of_day)
    print(f"Count: {ventas_all.count()}")
    for v in ventas_all:
         print(f"#{v.id} State:{v.estado} {v.fecha} {v.monto_total}")
         
    # List all recent sales to see if dates are weird
    print("\n--- Ultimas 5 Ventas ---")
    for v in Venta.objects.all().order_by('-id')[:5]:
        print(f"#{v.id} State:{v.estado} Date:{v.fecha}")

if __name__ == "__main__":
    run()
