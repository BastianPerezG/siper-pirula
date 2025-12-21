import os
import django
from django.conf import settings
from django.utils import timezone
import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siper_pirula.settings')
django.setup()

from ventas.models import Venta

def verify():
    print("--- Verifying Timezone Mismatch ---")
    
    # 1. Current Times
    now_utc = timezone.now()
    now_local = timezone.localtime(now_utc)
    
    print(f"Now UTC:   {now_utc}  -> Date: {now_utc.date()}")
    print(f"Now Local: {now_local} -> Date: {now_local.date()}")
    
    # 2. Simulate View Logic
    hoy_sistema = now_utc.date() # EXISTING BUGGY CODE
    hoy_local = now_local.date() # CORRECT CODE
    
    print(f"View uses 'hoy_sistema' (UTC date): {hoy_sistema}")
    
    # 3. Filter check
    # If we find a sale that is 'today' in local time, but 'yesterday' or mismatching in UTC?
    # Actually, the issue is usually when Local < UTC (South America is UTC-3/4).
    # So 22:00 Local (21st) = 01:00 UTC (22nd).
    # View thinks today is 22nd.
    # Database (correctly converting) thinks sale is 21st.
    # Filter `fecha__date = 22nd`.
    # Sale (21st) != 22nd. -> Not shown in "Ventas Hoy".
    
    if hoy_sistema != hoy_local:
        print("!! CRITICAL: UTC Date and Local Date DO NOT MATCH !!")
        print("This confirms the bug for 'Ventas Hoy' logic.")
    else:
        print("Dates match right now (mid-day?). The bug only appears late at night.")
        
    # 4. Check actual filter behavior on a Dummy Sale
    # Let's create a sale 'now'.
    # Note: We can't easily force the DB to think it's 'late night' without mocking,
    # but we can check what the DB thinks 'now' is compared to our python dates.
    
    v = Venta.objects.first() # grab any sale
    if v:
        qs = Venta.objects.filter(pk=v.pk, fecha__date=hoy_local)
        print(f"Finding sale #{v.pk} using Local Date ({hoy_local}): {qs.exists()}")
        
        qs_utc = Venta.objects.filter(pk=v.pk, fecha__date=hoy_sistema)
        print(f"Finding sale #{v.pk} using UTC Date ({hoy_sistema}): {qs_utc.exists()}")
        
        if qs.exists() and not qs_utc.exists():
             print("!! CONFIRMED: Sale found with Local Date but NOT with UTC Date (if dates differ).")

if __name__ == "__main__":
    verify()
