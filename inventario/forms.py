from django import forms
from django.forms import inlineformset_factory

from .models import Producto, MovimientoInventario, Compra, CompraItem, Proveedor


# -------------------------
#  Productos
# -------------------------
class ProductoCrearForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            "ean",
            "nombre",
            "categoria",
            "precio",
            "costo",
            "stock_min",
            "ubicacion",
            "activo",
        ]
        widgets = {
            # El EAN lo obtenemos desde el escáner, no se edita a mano
            "ean": forms.TextInput(attrs={"readonly": "readonly"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pequeño detalle de UX: focus en el nombre
        self.fields["nombre"].widget.attrs.setdefault("autofocus", "autofocus")


# -------------------------
#  Movimientos manuales de inventario
# -------------------------
class MovimientoCrearForm(forms.ModelForm):
    class Meta:
        model = MovimientoInventario
        fields = ["tipo", "cantidad", "comentario"]


# -------------------------
#  Compras
# -------------------------
class CompraForm(forms.ModelForm):
    class Meta:
        model = Compra
        fields = ["proveedor", "doc_tipo", "doc_num", "comentario"]

    def __init__(self, *args, **kwargs):
        # Sacamos negocio de kwargs para que NO llegue a BaseModelForm
        negocio = kwargs.pop("negocio", None)
        super().__init__(*args, **kwargs)

        # Si quieres que el combo de proveedores muestre solo los del negocio:
        if negocio is not None:
            self.fields["proveedor"].queryset = Proveedor.objects.filter(
                negocio=negocio, activo=True
            )


class CompraItemForm(forms.ModelForm):
    class Meta:
        model = CompraItem
        fields = ["producto", "cantidad", "costo_unit"]

    def __init__(self, *args, **kwargs):
        # Igual que arriba: sacamos negocio de kwargs
        negocio = kwargs.pop("negocio", None)
        super().__init__(*args, **kwargs)

        if negocio is not None:
            self.fields["producto"].queryset = Producto.objects.filter(
                negocio=negocio, activo=True
            )


CompraItemFormSet = inlineformset_factory(
    Compra,
    CompraItem,
    form=CompraItemForm,
    extra=1,          # antes 3 ó más
    can_delete=True,
)