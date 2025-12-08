from django import forms
from django.forms import inlineformset_factory
from .models import Venta, VentaItem, CajaTurno, ArqueoParcial
from inventario.models import Producto
from .utils import get_tope_descuento_pct

# Forms de Ventas


class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ["doc_tipo", "doc_num", "medio_pago", "comentario"]
    # el campo negocio NO se muestra, se setea en la vista


class VentaItemForm(forms.ModelForm):
    class Meta:
        model = VentaItem
        fields = ["producto", "cantidad", "precio_unit", "descuento_pct"]

    def __init__(self, *args, negocio=None, usuario=None, **kwargs):
        """
        - negocio: para limitar el queryset de productos.
        - usuario: para validar tope de descuento.
        """
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        qs = Producto.objects.filter(activo=True)
        if negocio is not None:
            qs = qs.filter(negocio=negocio)
        self.fields["producto"].queryset = qs
        # Sólo lectura: se completa solo
        self.fields["precio_unit"].widget.attrs["readonly"] = True

    def clean_descuento_pct(self):
        """
        Regla 2.3:
        - Aplica un tope de descuento por usuario.
        - Si lo supera, bloquea la acción (primera versión).
        """
        pct = self.cleaned_data.get("descuento_pct") or 0
        max_pct = get_tope_descuento_pct(self.usuario)

        # Normalizamos a float por si viene Decimal
        pct_float = float(pct)

        if pct_float < 0:
            raise forms.ValidationError("El descuento no puede ser negativo.")

        if pct_float > max_pct:
            raise forms.ValidationError(
                f"No puedes aplicar más de {max_pct}% de descuento. "
                "Si necesitas un descuento mayor, solicita autorización de un supervisor."
            )

        return pct


VentaItemFormSet = inlineformset_factory(
    Venta,
    VentaItem,
    form=VentaItemForm,
    extra=3,
    can_delete=True,
)


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