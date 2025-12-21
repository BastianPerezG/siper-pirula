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
) -> tuple[bool, str]:
    """
    Valida:
    - motivo obligatorio si hay descuento
    - tope por rol
    - si excede tope → requiere código válido
    Registra auditoría si el descuento se aplica.
    Devuelve (True, "") si está todo OK, (False, mensaje_error) si hay error.
    """
    pct = Decimal(pct_descuento or 0)
    monto = int(monto_descuento or 0)

    if pct <= 0 and monto <= 0:
        # Sin descuento → nada que hacer
        return (True, "")

    if not motivo.strip():
        motivo = "Descuento en Caja"  # Default reason since field was removed

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
            msg = (
                f"Tu rol permite hasta {tope_rol}% de descuento. "
                "Debes ingresar un código de autorización para aplicar más."
            )
            if request:
                messages.error(request, msg)
            return (False, msg)

        try:
            codigo = CodigoAutorizacionDescuento.objects.get(codigo=codigo_ingresado)
        except CodigoAutorizacionDescuento.DoesNotExist:
            msg = "Código de autorización inválido."
            if request:
                messages.error(request, msg)
            return (False, msg)

        if not codigo.esta_vigente():
            msg = "El código de autorización no está vigente."
            if request:
                messages.error(request, msg)
            return (False, msg)

        if pct > codigo.max_pct_ticket:
            msg = f"El código solo autoriza hasta {codigo.max_pct_ticket}% de descuento."
            if request:
                messages.error(request, msg)
            return (False, msg)

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

    return (True, "")