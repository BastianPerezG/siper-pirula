from decimal import Decimal

from django.utils import timezone
from django.contrib import messages
from core.models import PerfilUsuario
from .models import (
    DescuentoReglaRol,
    CodigoAutorizacionDescuento,
    AuditoriaDescuento,
)

def get_tope_descuento_ticket(user) -> Decimal:
    perfil = getattr(user, "perfilusuario", None)
    if not perfil:
        return Decimal("0")

    try:
        regla = DescuentoReglaRol.objects.get(rol=perfil.rol, activo=True)
    except DescuentoReglaRol.DoesNotExist:
        return Decimal("0")

    return regla.max_pct_ticket or Decimal("0")


def validar_y_auditar_descuento_ticket(
    *,
    user,
    venta,
    total_bruto,
    pct_descuento,
    monto_descuento,
    motivo,
    codigo_ingresado,
    request=None,
) -> bool:
    """
    Valida:
    - motivo obligatorio si hay descuento
    - tope por rol
    - si excede tope → requiere código válido
    Registra auditoría si el descuento se aplica.
    Devuelve True si está todo OK, False si hay error (y muestra mensaje).
    """
    pct = Decimal(pct_descuento or 0)
    monto = int(monto_descuento or 0)

    if pct <= 0 and monto <= 0:
        # Sin descuento → nada que hacer
        return True

    if not motivo.strip():
        if request:
            messages.error(request, "Debes ingresar un motivo para el descuento.")
        return False

    # Normalizamos: si hay % calculamos monto; si hay monto calculamos %
    if pct > 0 and monto == 0:
        monto = int((pct / Decimal("100")) * Decimal(total_bruto))
    elif monto > 0 and pct == 0:
        pct = (Decimal(monto) / Decimal(total_bruto)) * Decimal("100")

    tope_rol = get_tope_descuento_ticket(user)

    usuario_autoriza = None
    codigo_usado = ""

    # ¿Supera tope? → requiere código
    if pct > tope_rol:
        if not codigo_ingresado:
            if request:
                messages.error(
                    request,
                    f"Tu rol permite hasta {tope_rol}% de descuento. "
                    "Debes ingresar un código de autorización para aplicar más.",
                )
            return False

        try:
            codigo = CodigoAutorizacionDescuento.objects.get(codigo=codigo_ingresado)
        except CodigoAutorizacionDescuento.DoesNotExist:
            if request:
                messages.error(request, "Código de autorización inválido.")
            return False

        if not codigo.esta_vigente():
            if request:
                messages.error(request, "El código de autorización no está vigente.")
            return False

        if pct > codigo.max_pct_ticket:
            if request:
                messages.error(
                    request,
                    f"El código solo autoriza hasta {codigo.max_pct_ticket}% de descuento.",
                )
            return False

        usuario_autoriza = codigo.usuario_autorizador
        codigo_usado = codigo.codigo

    # Registrar auditoría
    AuditoriaDescuento.objects.create(
        venta=venta,
        nivel=AuditoriaDescuento.NIVEL_TICKET,
        usuario_aplica=user,
        usuario_autoriza=usuario_autoriza,
        motivo=motivo,
        porc_descuento=pct,
        monto_descuento=monto,
        codigo_usado=codigo_usado,
    )

    return True