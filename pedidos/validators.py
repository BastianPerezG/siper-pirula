# pedidos/validators.py

import re
from django.core.exceptions import ValidationError

RUT_RE = re.compile(r"^0*(\d{1,3}(\.?\d{3}){2})\-?([\dkK])$")

def _calcular_dv(rut_num):
    """
    Algoritmo clásico de DV chileno.
    rut_num: string sólo con números, sin puntos.
    """
    reversed_digits = map(int, reversed(rut_num))
    factors = [2, 3, 4, 5, 6, 7]
    s = 0
    factor_index = 0

    for d in reversed_digits:
        s += d * factors[factor_index]
        factor_index = (factor_index + 1) % len(factors)

    rest = 11 - (s % 11)
    if rest == 11:
        return "0"
    if rest == 10:
        return "K"
    return str(rest)

def validar_rut(value):
    if not value:
        return  # permitimos vacío (por ahora no es obligatorio)

    value = value.strip().upper()
    match = RUT_RE.match(value)
    if not match:
        raise ValidationError("Formato de RUT inválido. Ejemplo válido: 12.345.678-9")

    # limpiar: sacar puntos y guion
    rut_body = re.sub(r"[^0-9]", "", value[:-1])
    dv_ingresado = value[-1]

    dv_calculado = _calcular_dv(rut_body)
    if dv_calculado != dv_ingresado:
        raise ValidationError("RUT inválido. Dígito verificador no coincide.")
