from django import forms
from django.forms import inlineformset_factory

from .models import (
    Producto, 
    MovimientoInventario, 
    Compra, 
    CompraItem, 
    Proveedor,
    PlantillaProveedorProducto, 
    Promo, 
    PromoItem,
)

# -------------------------
#  Productos
# -------------------------
class ProductoCrearForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            "ean",
            "proveedor",
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
        # Permite ver los proveedores registrados
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
#==================sebastian-prov para mostrar============#
#=========================================================#


   


#==================sebastian-prov=========================#
#=========================================================#
class ProveedorForm(forms.ModelForm):
    """
    Formulario básico para la creación y edición de proveedores/distribuidores.
    """
    class Meta:
        model = Proveedor
        # Excluímos 'negocio' y 'activo' ya que se manejan automáticamente en la vista
        fields = [
            'nombre', 
            #'rut', 
            'contacto', 
            'telefono', 
            'correo', # Usamos 'correo' si es el nombre de campo en tu modelo
        ]
        
        widgets = {
            'nombre': forms.TextInput(attrs={'placeholder': 'Nombre completo o Razón Social'}),
            #'rut': forms.TextInput(attrs={'placeholder': 'Ej: 76.284.425-4'}),
            'contacto': forms.TextInput(attrs={'placeholder': 'Nombre del vendedor o encargado'}),
            'telefono': forms.TextInput(attrs={'placeholder': '+56 9 XXXXXXXX'}),
            'correo': forms.EmailInput(attrs={'placeholder': 'contacto@proveedor.cl'}),
        }
        
        labels = {
            'nombre': 'Nombre / Razón Social',
            #'rut': 'RUT/ID Tributario',
            'contacto': 'Persona de Contacto',
            'telefono': 'Teléfono',
            'correo': 'Correo Electrónico',
        }

#=================sebastian-plantilla-prov================#
#=========================================================#
class PlantillaProveedorProductoForm(forms.ModelForm):
    """
    Formulario para crear y editar la Plantilla Proveedor-Producto.
    Permite al Encargado de Compras/Bodega registrar los detalles específicos 
    (costo, SKU) que aplica un proveedor a un producto de nuestro inventario.
    """
    
    # El campo 'producto' es clave, ya que vincula la plantilla a un producto existente.
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.all(), # El queryset se puede limitar en la vista si es necesario
        help_text="Producto del inventario central que este proveedor suministra.",
        label="Producto del Inventario"
    )
    
    class Meta:
        model = PlantillaProveedorProducto
        fields = [
            'producto',
            'sku_proveedor',
            'precio_sugerido',
            'unidad_venta',
            'formato',
        ]
        
        widgets = {
            'sku_proveedor': forms.TextInput(attrs={'placeholder': 'SKU/Código que usa el proveedor'}),
            'precio_costo_actual': forms.NumberInput(attrs={'placeholder': 'Costo de compra unitario sin IVA'}),
            'precio_sugerido': forms.NumberInput(attrs={'placeholder': 'Precio de venta recomendado (opcional)'}),
            'unidad_venta': forms.TextInput(attrs={'placeholder': 'Ej: Botella, Caja x12, Pack x6'}),
            'formato': forms.TextInput(attrs={'placeholder': 'Ej: 750ml, 1 Litro, 5 Kg'}),
        }
        
        labels = {
            'sku_proveedor': 'SKU del Proveedor',
            'precio_costo_actual': 'Costo Unitario',
            'precio_sugerido': 'Precio Sugerido',
            'unidad_venta': 'Unidad de Venta',
        }
        
    def __init__(self, *args, **kwargs):
        negocio = kwargs.pop('negocio', None)
        super().__init__(*args, **kwargs)
        
        # Opcional: Si el formulario es para crear una nueva plantilla, 
        # limitamos la lista de productos a solo los del negocio del usuario.
        if negocio:
             self.fields['producto'].queryset = Producto.objects.filter(negocio=negocio, activo=True)

        # Si estamos editando (instance existe), el campo 'producto' no debería ser editable
        if self.instance.pk:
            self.fields['producto'].disabled = True


# -------------------------
#  Promociones / Combos
# -------------------------

class PromoForm(forms.ModelForm):
    class Meta:
        model = Promo
        # negocio no se edita aquí, se asigna en la vista
        fields = [
            "nombre",
            "descripcion",
            "imagen",
            "precio_combo",
            "activo",
            "mostrar_en_portada",
            "fecha_inicio",
            "fecha_fin",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 3}),
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}),
        }


PromoItemFormSet = inlineformset_factory(
    Promo,
    PromoItem,
    fields=["producto", "cantidad"],
    extra=1,
    can_delete=True,
)



class MermaForm(forms.ModelForm):
    class Meta:
        model = MovimientoInventario
        fields = ["producto", "cantidad", "comentario"]

    def __init__(self, *args, **kwargs):
        negocio = kwargs.pop("negocio", None)
        super().__init__(*args, **kwargs)

        # Sólo productos activos del negocio
        qs = Producto.objects.filter(activo=True)
        if negocio is not None:
            qs = qs.filter(negocio=negocio)
        self.fields["producto"].queryset = qs.order_by("nombre")

        self.fields["cantidad"].min_value = 1
        self.fields["cantidad"].widget.attrs["class"] = "w-24"

    def clean(self):
        cleaned = super().clean()
        producto = cleaned.get("producto")
        cantidad = cleaned.get("cantidad")

        if producto and cantidad:
            stock = producto.stock_actual or 0
            if cantidad > stock:
                raise forms.ValidationError(
                    f"No puedes registrar más merma ({cantidad}) que el stock disponible ({stock})."
                )

        return cleaned