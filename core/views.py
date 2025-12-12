# core/views.py
from django.views.generic import TemplateView, ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.models import User

from .models import PerfilUsuario, Negocio, BitacoraAccion
from .forms import UsuarioCrearForm, UsuarioEditarForm
from .mixins import RolRequeridoMixin, rol_requerido

from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.db.models import Q

from core.utils import registrar_bitacora_estructurada
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
                detalles_registro = {
                    'usuario_id': user.pk,
                    'rol_principal': perfil.rol, # Asumiendo que 'perfil.rol' existe
                    # Opcional: registrar la IP del cliente
                    'ip_address': request.META.get('REMOTE_ADDR'), 
                }
                
                registrar_bitacora_estructurada(
                    usuario=user,
                    nombre_modelo='Log',      # Modelo que representa la acción del sistema
                    tipo_accion='LOGIN',          # Acción específica para el inicio de sesión
                    accion=f"Inicio de sesión exitoso por el usuario: {user.username} con ID: {user.pk}",
                    entidad_id=user.pk,           # La entidad afectada es el propio usuario
                    detalles=detalles_registro
                )
                
                # --- 🔥 FIN DEL REGISTRO DE BITÁCORA 🔥 ---
                login(request, user)
                messages.success(request, "Sesión iniciada correctamente.")
                next_url = request.GET.get("next") or reverse_lazy("core:dashboard")
                return redirect(next_url)
    else:
        form = AuthenticationForm(request)

    return render(request, "core/login_interno.html", {"form": form})


def logout_interno_view(request):
    # 1. Verificar autenticación y obtener el objeto Negocio (si es necesario)
    if request.user.is_authenticated:
        # Intenta obtener el negocio asociado al usuario o el primero disponible
        try:
            negocio_instancia = Negocio.objects.first() 
        except Negocio.DoesNotExist:
            negocio_instancia = None

        # 2. Registrar el evento ANTES del logout
        if negocio_instancia:
            detalles_registro = {
                    'usuario_id': request.user.pk,
                    'ip_address': request.META.get('REMOTE_ADDR'), 
                }
            registrar_bitacora_estructurada(
                usuario=request.user,
                nombre_modelo="Log",
                tipo_accion="LOGOUT",
                entidad_id=request.user.pk,
                accion=f"Cierre de sesión exitoso por el usuario {request.user.username} con ID: {request.user.pk}.",
                detalles=detalles_registro
            )

    # 3. Cerrar sesión
    logout(request)
    
    # 4. Mensaje y redirección
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
        # 1. Obtener el negocio (como lo tenías)
        negocio = Negocio.objects.first()  
        
        # 2. Guardar el formulario (esto crea PerfilUsuario y el User asociado)
        # El método form.save(negocio=negocio) debe devolver la instancia del PerfilUsuario
        perfil_usuario = form.save(negocio=negocio)
        user = perfil_usuario.user # Asumiendo que PerfilUsuario tiene un campo 'user'
        
        # --- INICIO: REGISTRO DE BITÁCORA ---
        try:
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=self.request.user, # El usuario que realiza la acción (ADMIN)
                nombre_modelo="Usuario",
                tipo_accion="CREACION_USUARIO",
                accion=f"Usuario '{user.username}' (ID: {user.pk}) creado por {self.request.user.username}(ID: {self.request.user.pk}).",
                entidad_id=user.pk,
                detalles={
                    'nuevo_usuario_id': user.pk,
                    'nuevo_usuario_username': user.username,
                    'rol_asignado': perfil_usuario.rol, # Asumiendo que el rol está en PerfilUsuario
                    'negocio_id': negocio.pk,
                    'negocio':str(negocio),
                }
            )
            # Opcional: imprimir en consola para depuración
            # print(f"DEBUG: Bitácora de creación de usuario {user.username} registrada.") 
            
        except Exception as e:
            # Captura y logea el error sin detener el proceso de creación de usuario
            print(f"ERROR BITACORA (Creación de Usuario): {e}") 
        # --- FIN: REGISTRO DE BITÁCORA ---

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
        # Asegurarse de que la instancia de User se pase al formulario
        kwargs["user_instance"] = perfil.user 
        return kwargs

    def form_valid(self, form):
        # 1. Preparación y Captura de Cambios
        # self.object es la instancia de PerfilUsuario ORIGINAL antes de guardar.
        perfil_original = self.object
        user_original = perfil_original.user
        
        # El formulario UsuarioEditarForm probablemente maneja campos de User y PerfilUsuario
        # form.changed_data contiene la lista de campos que fueron realmente modificados.
        
        if form.changed_data:
            cambios = {}
            
            for field_name in form.changed_data:
                # El valor original está en form.initial
                old_value = form.initial.get(field_name, 'N/A')
                # El nuevo valor está en form.cleaned_data
                new_value = form.cleaned_data.get(field_name, 'N/A')

                # Almacenar el cambio de forma estructurada
                cambios[field_name] = {
                    'anterior': str(old_value),
                    'nuevo': str(new_value)
                }

            # 2. Registrar en la bitácora ANTES de guardar el cambio
            # Nota: Algunos prefieren registrar después de guardar para confirmar el éxito, 
            # pero registrar aquí asegura que usamos el `self.object` original.
            
            # El objeto principal es PerfilUsuario, pero el ID de la entidad es el User.
            user_afectado_pk = user_original.pk
            negocio = perfil_original.negocio 
            
            campos_txt = ", ".join(form.changed_data)

            detalles_registro = {
                'usuario_editado_id': user_afectado_pk,
                'usuario_editado_username': user_original.username,
                'rol_asignado_original': perfil_original.rol, # Valor original del rol
                'negocio_id': negocio.pk,
                'admin_responsable_id': self.request.user.pk,
                'cambios_detallados': cambios, 
            }
            
            try:
                registrar_bitacora_estructurada(
                    negocio=negocio, 
                    usuario=self.request.user, # ADMIN
                    nombre_modelo="Usuario",
                    tipo_accion="EDICION_USUARIO",
                    accion=f"Usuario '{user_original.username}' (ID: {user_afectado_pk}) actualizado. Campos modificados: {campos_txt}.",
                    entidad_id=perfil_original.pk,
                    detalles=detalles_registro
                )
            except Exception as e:
                print(f"ERROR BITACORA (Edición de Usuario): {e}") 
        
        # 3. Finalizar la operación de actualización (Guarda los nuevos datos)
        response = super().form_valid(form) 
        messages.success(self.request, "Usuario actualizado correctamente.")
        return response
    
@rol_requerido("ADMIN")
def usuario_toggle_activo_view(request, pk):
    """
    Activa/desactiva un usuario rápidamente desde la lista.
    """
    perfil = get_object_or_404(PerfilUsuario, pk=pk)
    
    # Toggle (Invertir) el estado en PerfilUsuario
    perfil.activo = not perfil.activo
    perfil.save(update_fields=["activo"])

    # Sincronizamos con is_active del User
    perfil.user.is_active = perfil.activo
    perfil.user.save(update_fields=["is_active"])

    estado_txt = "activado" if perfil.activo else "desactivado"
    
    # --- INICIO: REGISTRO DE BITÁCORA ---
    user_afectado = perfil.user
    negocio = perfil.negocio # Obtenemos el negocio del perfil

    try:
        # Define la acción y el tipo basado en el resultado del toggle
        tipo_accion = "USUARIO_ACTIVADO" if perfil.activo else "USUARIO_DESACTIVADO"
        accion_detalle = f"Usuario '{user_afectado.username}'(ID: {request.user.pk}) {estado_txt} por {request.user.username} (ID: {request.user.pk})."
        
        registrar_bitacora_estructurada(
            negocio=negocio,
            usuario=request.user, # El administrador que realiza la acción
            nombre_modelo="Usuario",
            tipo_accion=tipo_accion,
            accion=accion_detalle,
            entidad_id=user_afectado.pk, # El ID del usuario cuyo estado se cambió
            detalles={
                'usuario_afectado_id': user_afectado.pk,
                'usuario_afectado': user_afectado.username,
                'nuevo_estado': estado_txt,
                'admin_responsable_id': request.user.pk,
                'negocio_id': negocio.pk,
                'negocio':str(negocio),
            }
        )
    except Exception as e:
        # Captura y logea el error sin detener el proceso de toggle
        print(f"ERROR BITACORA (Toggle Usuario): {e}") 
    # --- FIN: REGISTRO DE BITÁCORA ---

    messages.info(request, f"Usuario {perfil.user.username} {estado_txt}.")
    return redirect("core:usuarios_lista")

class BitacoraListView(ListView):
    model = BitacoraAccion
    template_name = 'core/bitacora/bitacoras.html'
    context_object_name = 'logs'
    paginate_by = 50 

    # Definimos las áreas funcionales disponibles para el filtro
    AREAS_FUNCIONALES = [
        'Venta', 'Inventario', 'PedidoOnline', 'Caja', 'Usuario','Log'
    ]

    def get_queryset(self):
        # 1. Obtener el QuerySet base (todos los registros)
        queryset = super().get_queryset().select_related('usuario').order_by('-fecha_hora')
        
        # 2. Leer el parámetro de filtro 'area' de la URL
        filtro_area = self.request.GET.get('area')
        
        if filtro_area and filtro_area in self.AREAS_FUNCIONALES:
            # 3. Aplicar el filtro si se especificó un área válida
            queryset = queryset.filter(nombre_modelo__iexact=filtro_area)
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 4. Pasar las áreas disponibles y el filtro activo a la plantilla
        context['areas_funcionales'] = self.AREAS_FUNCIONALES
        context['area_activa'] = self.request.GET.get('area')
        
        return context