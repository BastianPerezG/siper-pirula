from django import forms
from django.forms import inlineformset_factory
from .models import Producto, MovimientoInventario, Compra, CompraItem

class ProductoCrearForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ["ean", "nombre", "categoria", "precio", "costo", "stock_min", "ubicacion", "activo"]
        widgets = {
            "ean": forms.TextInput(attrs={"readonly": "readonly"}),
        }


class MovimientoCrearForm(forms.ModelForm):
    class Meta:
        model = MovimientoInventario
        fields = ["tipo", "cantidad", "comentario"]


class CompraForm(forms.ModelForm):
    class Meta:
        model = Compra
        fields = ["proveedor", "doc_tipo", "doc_num", "comentario"]


CompraItemFormSet = inlineformset_factory(
    parent_model=Compra,
    model=CompraItem,
    fields=["producto", "cantidad", "costo_unit"],
    extra=3,          # cuántas filas vacías trae por defecto
    can_delete=True,  # permitir eliminar filas
)