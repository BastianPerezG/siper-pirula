# core/views.py
from django.views.generic import TemplateView, ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.models import User

from .models import PerfilUsuario, Negocio
from .forms import UsuarioCrearForm, UsuarioEditarForm
from .mixins import RolRequeridoMixin, rol_requerido

from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.db.models import Q

from .mixins import RolRequeridoMixin, rol_requerido

# Views Core

class DashboardView(TemplateView):
    template_name = "core/dashboard.html"


# ---------------------------
# Login / logout interno
# ---------------------------

def login_interno_view(request):
    """
    Login para trabajadores (caja, mesón, administrador).
    """
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            perfil = getattr(user, "perfilusuario", None)

            if not perfil or not perfil.activo:
                messages.error(
                    request,
                    "Tu cuenta no está habilitada para el sistema interno. "
                    "Contacta a un administrador."
                )
            else:
                login(request, user)
                messages.success(request, "Sesión iniciada correctamente.")
                next_url = request.GET.get("next") or reverse_lazy("core:dashboard")
                return redirect(next_url)
    else:
        form = AuthenticationForm(request)

    return render(request, "core/login_interno.html", {"form": form})


def logout_interno_view(request):
    logout(request)
    messages.info(request, "Sesión cerrada.")
    return redirect("core:login_interno")


# ---------------------------
# Gestión de usuarios internos
# ---------------------------

class UsuarioListaView(RolRequeridoMixin, ListView):
    """
    Lista de usuarios internos con filtros por rol, estado y nombre/correo.
    Solo Administrador puede acceder.
    """
    model = PerfilUsuario
    template_name = "core/usuarios_lista.html"
    context_object_name = "usuarios"
    roles_requeridos = ["ADMIN"]

    def get_queryset(self):
        qs = (
            PerfilUsuario.objects
            .select_related("user", "negocio")
            .order_by("user__first_name", "user__username")
        )

        rol = self.request.GET.get("rol", "")
        estado = self.request.GET.get("estado", "")
        q = (self.request.GET.get("q") or "").strip()

        if rol:
            qs = qs.filter(rol=rol)

        if estado == "activos":
            qs = qs.filter(activo=True)
        elif estado == "inactivos":
            qs = qs.filter(activo=False)

        if q:
            qs = qs.filter(
                Q(user__username__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__email__icontains=q)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roles"] = PerfilUsuario.ROL_CHOICES
        ctx["rol_actual"] = self.request.GET.get("rol", "")
        ctx["estado_actual"] = self.request.GET.get("estado", "")
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx


class UsuarioCrearView(RolRequeridoMixin, CreateView):
    model = PerfilUsuario
    form_class = UsuarioCrearForm
    template_name = "core/usuario_form.html"
    success_url = reverse_lazy("core:usuarios_lista")
    roles_requeridos = ["ADMIN"]

    def form_valid(self, form):
        negocio = Negocio.objects.first()  
        form.save(negocio=negocio)
        messages.success(self.request, "Usuario creado correctamente.")
        return redirect("core:usuarios_lista")


class UsuarioEditarView(RolRequeridoMixin, UpdateView):
    model = PerfilUsuario
    form_class = UsuarioEditarForm
    template_name = "core/usuario_form.html"
    success_url = reverse_lazy("core:usuarios_lista")
    roles_requeridos = ["ADMIN"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        perfil = self.get_object()
        kwargs["user_instance"] = perfil.user
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Usuario actualizado correctamente.")
        return redirect("core:usuarios_lista")


@rol_requerido("ADMIN")
def usuario_toggle_activo_view(request, pk):
    """
    Activa/desactiva un usuario rápidamente desde la lista.
    """
    perfil = get_object_or_404(PerfilUsuario, pk=pk)
    perfil.activo = not perfil.activo
    perfil.save(update_fields=["activo"])

    # sincronizamos con is_active del User
    perfil.user.is_active = perfil.activo
    perfil.user.save(update_fields=["is_active"])

    estado_txt = "activado" if perfil.activo else "desactivado"
    messages.info(request, f"Usuario {perfil.user.username} {estado_txt}.")
    return redirect("core:usuarios_lista")