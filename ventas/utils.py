from core.models import PerfilUsuario

# Topes de descuento por rol (%)
# ---------------------------------------------------------------------
# Por ejemplo:
#   - CAJERO: hasta 10% sin autorización
#   - MESON: hasta 5% (o 0 si no quieres que descuente)
#   - ADMIN: sin límite (100% para efectos prácticos)
TOPES_DESCUENTO_PCT = {
    PerfilUsuario.ROL_CAJERO: 10,
    PerfilUsuario.ROL_MESON: 5,
    PerfilUsuario.ROL_ADMIN: 100,
}

def get_perfil_usuario(user):
    """
    Devuelve el PerfilUsuario asociado o None.
    """
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "perfilusuario", None)


def get_tope_descuento_pct(user):
    """
    Devuelve el porcentaje máximo de descuento que el usuario
    puede aplicar SIN autorización especial.
    Si no tiene perfil o está inactivo, se asume 0%.
    """
    perfil = get_perfil_usuario(user)

    if not perfil or not perfil.activo:
        return 0

    return TOPES_DESCUENTO_PCT.get(perfil.rol, 0)


def puede_autorizar_descuento_mayor(user):
    """
    Helper para futuro:
    Indica si este usuario puede autorizar descuentos por encima del tope
    (por ejemplo, administradores).
    """
    perfil = get_perfil_usuario(user)
    if not perfil or not perfil.activo:
        return False

    # Por ahora solo ADMIN puede autorizar descuentos especiales.
    return perfil.rol == PerfilUsuario.ROL_ADMIN