# core/forms.py
from symtable import Symbol
from django import forms
from django.contrib.auth.models import User
from .models import PerfilUsuario

class UsuarioCrearForm(forms.ModelForm):
    """
    Form para crear usuario interno + perfil.
    """
    nombre = forms.CharField(label="Nombre completo", max_length=150)
    email = forms.EmailField(label="Correo electrónico")
    username = forms.CharField(label="Nombre de usuario", max_length=150)

    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        label="Repite la contraseña",
        widget=forms.PasswordInput,
    )

    rol = forms.ChoiceField(
        choices=PerfilUsuario.ROL_CHOICES,
        label="Rol",
    )

    telefono = forms.CharField(
        label="Teléfono",
        max_length=30,
        required=False,
    )
 
    class Meta:
        model = PerfilUsuario
        fields = ["rol", "telefono"]

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya existe.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Ya existe un usuario con este correo.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        # Verificar que las contraseñas coincidan
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        # Validaciones de seguridad
        if p1:
            # Largo mínimo
            if len(p1) < 6:
                raise forms.ValidationError("La contraseña debe tener al menos 6 caracteres.")

            # Mayúscula
            if not any(c.isupper() for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos una letra mayúscula.")

            # Número
            if not any(c.isdigit() for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos un número.")

            # Símbolo
            symbols = "!@#$%^&*()_+-={}[]|:;<>,.?/~`"
            if not any(c in symbols for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos un símbolo.")

            # Espacios no permitidos
            if " " in p1:
                raise forms.ValidationError("La contraseña no debe contener espacios.")

        return cleaned

    def save(self, negocio, commit=True):
        """
        Crea el User y el PerfilUsuario asociado al negocio.
        """
        username = self.cleaned_data["username"]
        email = self.cleaned_data["email"]
        password = self.cleaned_data["password1"]
        nombre = self.cleaned_data["nombre"]
        rol = self.cleaned_data["rol"]
        telefono = self.cleaned_data.get("telefono")

        # Crear User
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )
        # Partimos simple: guardamos el nombre completo en first_name
        user.first_name = nombre
        user.save()

        perfil = PerfilUsuario(
            user=user,
            negocio=negocio,
            rol=rol,
            telefono=telefono,
            activo=True,
        )

        if commit:
            perfil.save()
        return perfil


class UsuarioEditarForm(forms.ModelForm):
    """
    Edita datos básicos del perfil y del User asociado.
    (No cambia la contraseña aquí.)
    """
    nombre = forms.CharField(label="Nombre completo", max_length=150)
    email = forms.EmailField(label="Correo electrónico")
    username = forms.CharField(label="Nombre de usuario", max_length=150)

    class Meta:
        model = PerfilUsuario
        fields = ["rol", "telefono", "activo"]

    def __init__(self, *args, **kwargs):
        self.user_instance = kwargs.pop("user_instance")
        super().__init__(*args, **kwargs)
        # rellenar campos desde user
        self.fields["nombre"].initial = (
            self.user_instance.get_full_name() or self.user_instance.first_name
        )
        self.fields["email"].initial = self.user_instance.email
        self.fields["username"].initial = self.user_instance.username

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exclude(pk=self.user_instance.pk).exists():
            raise forms.ValidationError("Este nombre de usuario ya existe.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exclude(pk=self.user_instance.pk).exists():
            raise forms.ValidationError("Ya existe un usuario con este correo.")
        return email

    def save(self, commit=True):
        perfil = super().save(commit=False)

        # Actualizar datos del user
        self.user_instance.username = self.cleaned_data["username"]
        self.user_instance.email = self.cleaned_data["email"]
        self.user_instance.first_name = self.cleaned_data["nombre"]
        self.user_instance.is_active = perfil.activo

        if commit:
            self.user_instance.save()
            perfil.save()
        return perfil
