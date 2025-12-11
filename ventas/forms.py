from django import forms
from django.forms import inlineformset_factory
from .models import CodigoAutorizacionDescuento, Venta, VentaItem, CajaTurno, ArqueoParcial, PagoVenta, DescuentoReglaRol, AuditoriaDescuento
from inventario.models import Producto
from .utils import get_tope_descuento_ticket
from django.contrib.auth import get_user_model

User = get_user_model()
# Forms de Ventas


class VentaFiltroForm(forms.Form):
    """
    Formulario para filtrar y buscar ventas.
    """
    # Búsqueda
    q = forms.CharField(
        required=False,
        label="Buscar",
        widget=forms.TextInput(attrs={
            "placeholder": "ID, número de documento...",
            "class": "form-input"
        }),
        help_text="Buscar por ID de venta o número de documento"
    )
    
    # Filtros
    estado = forms.ChoiceField(
        required=False,
        label="Estado",
        choices=[
            ("", "Todos"),
            (Venta.EST_ABIERTA, "Abierta"),
            (Venta.EST_CERRADA, "Cerrada"),
            (Venta.EST_ANULADA, "Anulada"),
        ],
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    metodo_pago = forms.ChoiceField(
        required=False,
        label="Método de pago",
        choices=[
            ("", "Todos"),
            (Venta.MED_EFECTIVO, "Efectivo"),
            (Venta.MED_DEBITO, "Tarjeta débito"),
            (Venta.MED_CREDITO, "Tarjeta crédito"),
            (Venta.MED_TRANSFERENCIA, "Transferencia"),
        ],
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    doc_tipo = forms.ChoiceField(
        required=False,
        label="Tipo de documento",
        choices=[
            ("", "Todos"),
            (Venta.DOC_BOLETA, "Boleta"),
            (Venta.DOC_FACTURA, "Factura"),
            (Venta.DOC_SIN_DOC, "Sin documento"),
        ],
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    fecha_desde = forms.DateField(
        required=False,
        label="Fecha desde",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-input"
        })
    )
    
    fecha_hasta = forms.DateField(
        required=False,
        label="Fecha hasta",
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": "form-input"
        })
    )


class VentaForm(forms.ModelForm):
    """
    Formulario para crear/editar ventas.
    Nota: 
    - medio_pago NO está aquí porque se selecciona en el checkout.
    - doc_num NO está aquí porque se genera automáticamente.
    """
    class Meta:
        model = Venta
        fields = ["doc_tipo", "comentario"]
    # el campo negocio se setea en la vista


class VentaItemForm(forms.ModelForm):
    # Campos extra SOLO de formulario (no están en la BD)
    motivo_descuento = forms.CharField(
        label="Motivo del descuento",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "Explica por qué se aplica el descuento",
            }
        ),
    )
    codigo_autorizacion = forms.CharField(
        label="Código de autorización",
        required=False,
        help_text="Solo si el descuento supera tu tope permitido.",
    )

    class Meta:
        model = VentaItem
        fields = ["producto", "cantidad", "precio_unit", "descuento_pct"]

    def __init__(self, *args, negocio=None, usuario=None, **kwargs):
        """
        - negocio: para limitar el queryset de productos.
        - usuario: para validar tope de descuento por rol.
        """
        self.usuario = usuario
        super().__init__(*args, **kwargs)

        qs = Producto.objects.filter(activo=True)
        if negocio is not None:
            qs = qs.filter(negocio=negocio)
        self.fields["producto"].queryset = qs

        # ✅ permitimos filas completamente vacías
        self.fields["producto"].required = False
        self.fields["cantidad"].required = False
        self.fields["precio_unit"].required = False
        self.fields["descuento_pct"].required = False

        # Solo lectura: se completa automáticamente desde el JS
        self.fields["precio_unit"].widget.attrs["readonly"] = True

    def clean_descuento_pct(self):
        """
        Valida rango y tope por rol.
        """
        pct = self.cleaned_data.get("descuento_pct") or 0
        pct_float = float(pct)

        if pct_float < 0:
            raise forms.ValidationError("El descuento no puede ser negativo.")
        if pct_float > 100:
            raise forms.ValidationError("El descuento no puede superar el 100%.")

        max_pct = get_tope_descuento_ticket(self.usuario)
        if pct_float > max_pct:
            raise forms.ValidationError(
                f"No puedes aplicar más de {max_pct}% de descuento. "
                "Si necesitas un descuento mayor, solicita autorización de un supervisor "
                "e ingresa su código en el campo correspondiente."
            )

        return pct

    def clean(self):
        cleaned = super().clean()

        producto = cleaned.get("producto")
        cantidad = cleaned.get("cantidad")
        precio = cleaned.get("precio_unit")
        pct = cleaned.get("descuento_pct") or 0
        motivo = (cleaned.get("motivo_descuento") or "").strip()

        # ✅ 1) Si la fila viene COMPLETAMENTE vacía → la dejamos pasar en silencio
        if not producto and not cantidad and not precio and not pct and not motivo:
            # La vista luego simplemente no guardará este ítem
            return cleaned

        # ✅ 2) A partir de aquí, consideramos que la fila "existe" y exigimos datos
        if not producto:
            self.add_error("producto", "Este campo es obligatorio.")
        if not cantidad:
            self.add_error("cantidad", "Este campo es obligatorio.")
        if not precio:
            self.add_error("precio_unit", "Este campo es obligatorio.")

        # ✅ 3) Motivo obligatorio si hay descuento
        if float(pct or 0) > 0 and not motivo:
            self.add_error(
                "motivo_descuento",
                "Debes ingresar un motivo cuando aplicas un descuento.",
            )

        return cleaned


VentaItemFormSet = inlineformset_factory(
    Venta,
    VentaItem,
    form=VentaItemForm,
    extra=3,
    can_delete=True,
)

class VentaCheckoutForm(forms.Form):
    # Constantes para tipos de descuento
    TIPO_NINGUNO = "NINGUNO"
    TIPO_PORCENTAJE = "PORCENTAJE"
    TIPO_MONTO = "MONTO"
    
    # Info solo de lectura para mostrar en plantilla
    total_bruto = forms.IntegerField(disabled=True, required=False, label="Total bruto")

    # Tipo de descuento: ninguno / porcentaje / monto fijo
    TIPO_DESC = (
        (TIPO_NINGUNO, "Sin descuento"),
        (TIPO_PORCENTAJE, "Porcentaje"),
        (TIPO_MONTO, "Monto fijo"),
    )
    tipo_descuento = forms.ChoiceField(choices=TIPO_DESC, initial=TIPO_NINGUNO)

    descuento_pct = forms.DecimalField(
        max_digits=5, decimal_places=2, required=False, label="Descuento (%)"
    )
    descuento_monto = forms.IntegerField(
        required=False, label="Descuento ($)", min_value=0
    )
    motivo_descuento = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Motivo del descuento"},
        ),
    )
    codigo_autorizacion = forms.CharField(
        required=False,
        label="Código de autorización (si se requiere)",
    )

    # Pago - Método principal
    metodo_pago = forms.ChoiceField(
        choices=PagoVenta.METODOS,
        label="Método de pago"
    )
    monto_pagado = forms.IntegerField(
        min_value=0,
        label="Monto pagado",
        help_text="Ingresa el monto recibido del cliente"
    )
    
    # Vuelto (solo para efectivo)
    vuelto = forms.IntegerField(
        required=False,
        min_value=0,
        label="Vuelto",
        help_text="Se calcula automáticamente si el monto pagado es mayor al total"
    )
    
    # Campos para transferencia bancaria
    codigo_referencia_transferencia = forms.CharField(
        required=False,
        max_length=50,
        label="Código de referencia",
        help_text="Código o número que el cliente debe usar como referencia de transferencia"
    )
    banco_transferencia = forms.CharField(
        required=False,
        max_length=100,
        label="Banco",
        help_text="Banco desde donde se realizó la transferencia"
    )
    cuenta_origen_transferencia = forms.CharField(
        required=False,
        max_length=50,
        label="Cuenta origen",
        help_text="Número de cuenta desde donde se realizó la transferencia"
    )
    titular_transferencia = forms.CharField(
        required=False,
        max_length=200,
        label="Titular de la cuenta",
        help_text="Nombre del titular de la cuenta origen"
    )
    
    # Campos para tarjetas (para futura integración)
    ultimos_digitos_tarjeta = forms.CharField(
        required=False,
        max_length=4,
        label="Últimos 4 dígitos",
        help_text="Últimos 4 dígitos de la tarjeta"
    )
    referencia_transaccion = forms.CharField(
        required=False,
        max_length=100,
        label="Referencia de transacción",
        help_text="Referencia proporcionada por la pasarela de pago"
    )
    
    # Observaciones del pago
    observaciones_pago = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Observaciones sobre el pago (opcional)"}),
        label="Observaciones"
    )

    def __init__(self, *args, user=None, total_bruto=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.total_bruto_val = int(total_bruto)
        self.fields["total_bruto"].initial = self.total_bruto_val

        tope = get_tope_descuento_ticket(user) if user else 0
        self.fields["descuento_pct"].help_text = (
            f"Tu tope sin autorización es {tope}% sobre el ticket."
        )
        
        # Inicializar campos según método de pago si viene en initial
        if 'initial' in kwargs:
            metodo = kwargs['initial'].get('metodo_pago', PagoVenta.MET_EFECTIVO)
            self._configurar_campos_por_metodo(metodo)
        else:
            # Por defecto, mostrar campos de efectivo
            self._configurar_campos_por_metodo(PagoVenta.MET_EFECTIVO)
    
    def _configurar_campos_por_metodo(self, metodo):
        """Configura qué campos son requeridos según el método de pago"""
        # Resetear todos los campos opcionales
        campos_transferencia = [
            'codigo_referencia_transferencia',
            'banco_transferencia',
            'cuenta_origen_transferencia',
            'titular_transferencia'
        ]
        campos_tarjeta = [
            'ultimos_digitos_tarjeta',
            'referencia_transaccion'
        ]
        
        for campo in campos_transferencia + campos_tarjeta:
            self.fields[campo].required = False
        
        # Configurar según método
        if metodo == PagoVenta.MET_TRANSFERENCIA:
            # Para transferencias, el código de referencia es obligatorio
            self.fields['codigo_referencia_transferencia'].required = True
            self.fields['codigo_referencia_transferencia'].help_text = (
                "Código obligatorio que el cliente debe usar como referencia"
            )
        elif metodo in [PagoVenta.MET_DEBITO, PagoVenta.MET_CREDITO]:
            # Para tarjetas, los campos son opcionales por ahora (se llenarán con pasarela)
            pass
        # Para efectivo, no hay campos adicionales requeridos

    def clean(self):
        cleaned = super().clean()

        tipo = cleaned.get("tipo_descuento")
        pct = cleaned.get("descuento_pct") or 0
        monto = cleaned.get("descuento_monto") or 0
        motivo = (cleaned.get("motivo_descuento") or "").strip()

        # Normalizamos según tipo
        if tipo == self.TIPO_NINGUNO:
            cleaned["descuento_pct"] = 0
            cleaned["descuento_monto"] = 0
        elif tipo == self.TIPO_PORCENTAJE:
            if pct <= 0:
                self.add_error("descuento_pct", "Ingresa un porcentaje válido.")
            cleaned["descuento_monto"] = 0
        elif tipo == self.TIPO_MONTO:
            if monto <= 0:
                self.add_error("descuento_monto", "Ingresa un monto válido.")
            cleaned["descuento_pct"] = 0

        # Motivo obligatorio si hay cualquier tipo de descuento
        if (pct > 0 or monto > 0) and not motivo:
            self.add_error(
                "motivo_descuento",
                "Debes ingresar un motivo para aplicar el descuento.",
            )

        # Validar monto pagado y calcular vuelto
        total_bruto = self.total_bruto_val
        total_desc = monto if monto > 0 else int(total_bruto * float(pct) / 100)
        total_neto = total_bruto - total_desc
        if total_neto < 0:
            raise forms.ValidationError("El total no puede quedar negativo.")

        metodo_pago = cleaned.get("metodo_pago")
        monto_pagado = cleaned.get("monto_pagado") or 0
        
        # Validaciones según método de pago
        if metodo_pago == PagoVenta.MET_EFECTIVO:
            # Para efectivo, el monto pagado puede ser mayor (hay vuelto)
            if monto_pagado < total_neto:
                raise forms.ValidationError(
                    f"El monto pagado (${monto_pagado}) es menor al total a pagar (${total_neto})."
                )
            # Calcular vuelto automáticamente
            vuelto_calculado = monto_pagado - total_neto
            cleaned["vuelto"] = vuelto_calculado
        elif metodo_pago == PagoVenta.MET_TRANSFERENCIA:
            # Para transferencias, el monto debe ser exacto y el código es obligatorio
            if monto_pagado != total_neto:
                raise forms.ValidationError(
                    f"El monto de transferencia debe ser exactamente ${total_neto}."
                )
            codigo_ref = cleaned.get("codigo_referencia_transferencia", "").strip()
            if not codigo_ref:
                self.add_error(
                    "codigo_referencia_transferencia",
                    "El código de referencia es obligatorio para transferencias."
                )
            # Las transferencias quedan pendientes por defecto
            cleaned["vuelto"] = 0
        else:
            # Para tarjetas, el monto debe ser exacto
            if monto_pagado != total_neto:
                raise forms.ValidationError(
                    f"El monto pagado con tarjeta debe ser exactamente ${total_neto}."
                )
            cleaned["vuelto"] = 0

        cleaned["total_descuento_monto"] = total_desc
        cleaned["total_neto"] = total_neto

        return cleaned
    

class AperturaCajaForm(forms.ModelForm):
    class Meta:
        model = CajaTurno
        fields = ["monto_inicial"]


class ArqueoParcialForm(forms.ModelForm):
    class Meta:
        model = ArqueoParcial
        fields = ["monto_contado", "observacion"]
        widgets = {
            "monto_contado": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "step": "1",
                    "min": "0",
                    "autofocus": True,
                }
            ),
            "observacion": forms.Textarea(
                attrs={
                    "class": "form-textarea",
                    "rows": 3,
                    "placeholder": "Comentarios u observaciones (opcional)",
                }
            ),
        }


class CierreCajaForm(forms.ModelForm):
    class Meta:
        model = CajaTurno
        fields = ["monto_contado_cierre", "observacion_cierre"]


class DescuentoReglaRolForm(forms.ModelForm):
    """
    Formulario para administrar el tope de descuento por rol.
    Por ahora solo manejamos max_pct_ticket.
    """

    class Meta:
        model = DescuentoReglaRol
        fields = ["rol", "max_pct_ticket", "activo"]
        widgets = {
            "rol": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "max_pct_ticket": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
            "activo": forms.CheckboxInput(
                attrs={
                    "class": "form-checkbox",
                }
            ),
        }

    def clean_max_pct_ticket(self):
        """
        Validamos que el porcentaje esté entre 0 y 100.
        """
        pct = self.cleaned_data.get("max_pct_ticket") or 0
        if pct < 0:
            raise forms.ValidationError("El porcentaje no puede ser negativo.")
        if pct > 100:
            raise forms.ValidationError("El porcentaje no puede ser mayor a 100%.")
        return pct


class CodigoAutorizacionDescuentoForm(forms.ModelForm):
    """
    Formulario para crear/editar códigos de autorización de descuento.
    """

    class Meta:
        model = CodigoAutorizacionDescuento
        fields = ["codigo", "usuario_autorizador", "max_pct_ticket", "valido_hasta", "activo"]
        widgets = {
            "codigo": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": "Ej: SUPERVISOR01",
                }
            ),
            "usuario_autorizador": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "max_pct_ticket": forms.NumberInput(
                attrs={
                    "class": "form-input",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
            "valido_hasta": forms.DateTimeInput(
                attrs={
                    "class": "form-input",
                    "type": "datetime-local",
                }
            ),
            "activo": forms.CheckboxInput(
                attrs={
                    "class": "form-checkbox",
                }
            ),
        }

    def clean_codigo(self):
        """
        Normalizamos el código para evitar duplicados tipo 'abc' vs 'ABC '.
        """
        codigo = (self.cleaned_data.get("codigo") or "").strip().upper()
        if not codigo:
            raise forms.ValidationError("El código no puede estar vacío.")
        return codigo

    def clean_max_pct_ticket(self):
        pct = self.cleaned_data.get("max_pct_ticket") or 0
        if pct < 0:
            raise forms.ValidationError("El porcentaje no puede ser negativo.")
        if pct > 100:
            raise forms.ValidationError("El porcentaje no puede ser mayor a 100%.")
        return pct


class AuditoriaDescuentoFiltroForm(forms.Form):
    """
    Filtros simples para la vista de auditoría de descuentos.
    Se usa solo para construir el formulario y filtrar el queryset.
    """

    fecha_desde = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-input",
            }
        ),
    )
    fecha_hasta = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-input",
            }
        ),
    )
    usuario_aplica = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        label="Cajero",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )
    usuario_autoriza = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        label="Autorizador",
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )
    nivel = forms.ChoiceField(
        required=False,
        label="Nivel",
        choices=[("", "Todos")] + list(AuditoriaDescuento.NIVELES),
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )

    def filtrar_queryset(self, qs):
        """
        Aplica los filtros al queryset de AuditoriaDescuento.
        Se llama desde la vista una vez que el form es válido.
        """
        if not self.is_valid():
            return qs

        cd = self.cleaned_data

        if cd.get("fecha_desde"):
            qs = qs.filter(fecha_hora__date__gte=cd["fecha_desde"])
        if cd.get("fecha_hasta"):
            qs = qs.filter(fecha_hora__date__lte=cd["fecha_hasta"])
        if cd.get("usuario_aplica"):
            qs = qs.filter(usuario_aplica=cd["usuario_aplica"])
        if cd.get("usuario_autoriza"):
            qs = qs.filter(usuario_autoriza=cd["usuario_autoriza"])
        if cd.get("nivel"):
            qs = qs.filter(nivel=cd["nivel"])

        return qs