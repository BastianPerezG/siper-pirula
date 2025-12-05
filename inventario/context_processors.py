
from .models import Producto

def stock_critico_context(request):
    """
    Entrega la cantidad de productos en stock crítico
    para mostrar en el navbar.
    """
    if not request.user.is_authenticated:
        return {}

    perfil = getattr(request.user, "perfilusuario", None)
    negocio = getattr(perfil, "negocio", None)
    if not negocio:
        return {}

    qs = Producto.objects.filter(negocio=negocio, activo=True)
    cantidad = sum(1 for p in qs if p.stock_actual < p.stock_min)

    return {"stock_critico_count": cantidad}