# core/views.py
from django.views.generic import TemplateView, ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.db.models import Q
from django.contrib.staticfiles.storage import staticfiles_storage
import os
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from .models import PerfilUsuario, Negocio, BitacoraAccion
from .forms import UsuarioCrearForm, UsuarioEditarForm
from .mixins import RolRequeridoMixin, rol_requerido
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.db.models import Q

from core.utils import registrar_bitacora_estructurada
from .mixins import RolRequeridoMixin, rol_requerido
#correo
from django.contrib.auth.views import PasswordResetView
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.conf import settings
from .emails import enviar_correo_restablecer_password # Importamos nuestra función de envío

# Views Core

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"
    
    def dispatch(self, request, *args, **kwargs):
        # Solo usuarios internos (con perfil) pueden acceder al dashboard
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        
        perfil = getattr(request.user, "perfilusuario", None)
        if not perfil or not perfil.activo:
            from django.shortcuts import render
            return render(request, "403.html", status=403)
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        from django.utils import timezone
        from django.db.models import Sum, Count
        from datetime import timedelta
        
        context = super().get_context_data(**kwargs)
        hoy = timezone.now().date()
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        perfil = getattr(self.request.user, "perfilusuario", None)
        
        # Solo calcular métricas para ADMIN y CAJERO
        if perfil and perfil.rol in ['ADMIN', 'CAJERO']:
            try:
                from ventas.models import Venta
                from pedidos.models import Pedido
                from inventario.models import Producto
                
                negocio = perfil.negocio
                
                # Ventas de hoy
                ventas_hoy = Venta.objects.filter(
                    negocio=negocio,
                    fecha__date=hoy,
                    estado=Venta.EST_CERRADA
                )
                context['ventas_hoy_count'] = ventas_hoy.count()
                context['ventas_hoy_total'] = ventas_hoy.aggregate(
                    total=Sum('monto_total')
                )['total'] or 0
                
                # Ventas de la semana
                ventas_semana = Venta.objects.filter(
                    negocio=negocio,
                    fecha__date__gte=inicio_semana,
                    estado=Venta.EST_CERRADA
                )
                context['ventas_semana_total'] = ventas_semana.aggregate(
                    total=Sum('monto_total')
                )['total'] or 0
                
                # Pedidos pendientes (no finalizados)
                pedidos_pendientes = Pedido.objects.filter(
                    negocio=negocio,
                ).exclude(
                    estado_preparacion__in=[
                        Pedido.PREP_RETIRADO, 
                        Pedido.PREP_CANCELADO, 
                        Pedido.PREP_NO_RETIRA
                    ]
                )
                context['pedidos_pendientes'] = pedidos_pendientes.count()
                
                # Pedidos por estado
                context['pedidos_recibidos'] = pedidos_pendientes.filter(
                    estado_preparacion=Pedido.PREP_RECIBIDO
                ).count()
                context['pedidos_preparando'] = pedidos_pendientes.filter(
                    estado_preparacion=Pedido.PREP_PREPARANDO
                ).count()
                context['pedidos_listos'] = pedidos_pendientes.filter(
                    estado_preparacion=Pedido.PREP_LISTO
                ).count()
                
                # Stock crítico
                from django.db.models import F
                stock_critico = Producto.objects.filter(
                    negocio=negocio,
                    activo=True,
                    stock__lte=F('stock_minimo')
                )
                context['stock_critico_count'] = stock_critico.count()
                context['productos_stock_critico'] = stock_critico[:5]
                
                # Productos sin stock
                context['sin_stock_count'] = Producto.objects.filter(
                    negocio=negocio,
                    activo=True,
                    stock=0
                ).count()
                
            except Exception as e:
                # Si hay error en las importaciones, no mostramos métricas
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Error cargando métricas del dashboard: {str(e)}")
        
        return context


# ---------------------------
# Login / logout interno
# ---------------------------

def login_interno_view(request):
    """
    Login para trabajadores (caja, mesón, administrador).
    Incluye lógica de bloqueo por intentos fallidos.
    """
    if request.method == "POST":
        # 1. Recuperar usuario para verificar bloqueo antes de validar credenciales
        username = request.POST.get("username")
        user_obj = None
        perfil_obj = None
        
        try:
            user_obj = User.objects.get(username=username)
            perfil_obj = getattr(user_obj, "perfilusuario", None)
        except User.DoesNotExist:
            pass
            
        # Verificar si está bloqueado
        if perfil_obj and perfil_obj.bloqueado_hasta:
            if perfil_obj.bloqueado_hasta > timezone.now():
                wait_minutes = int((perfil_obj.bloqueado_hasta - timezone.now()).total_seconds() / 60) + 1
                messages.error(
                    request, 
                    f"Cuenta bloqueada temporalmente por intentos fallidos. Inténtalo de nuevo en {wait_minutes} minutos."
                )
                # Retornamos el form vacío o con el username preservado
                form = AuthenticationForm(request) 
                return render(request, "core/login_interno.html", {"form": form})
            else:
                # El tiempo pasó, reseteamos el bloqueo automáticamente
                
                # --- Registro Bitácora Desbloqueo Automático ---
                try:
                    registrar_bitacora_estructurada(
                        negocio=perfil_obj.negocio,
                        usuario=user_obj,  # El propio usuario desencadena el desbloqueo al intentar login
                        nombre_modelo="Usuario",
                        tipo_accion="USUARIO_DESBLOQUEADO",
                        accion=f"Usuario {user_obj.username} desbloqueado automáticamente al expirar tiempo de bloqueo.",
                        entidad_id=user_obj.pk,
                        detalles={
                            'usuario_desbloqueado_id': user_obj.pk,
                            'motivo': 'Expiración de tiempo de bloqueo',
                            'bloqueado_hasta_anterior': str(perfil_obj.bloqueado_hasta)
                        }
                    )
                except Exception:
                    pass
                # -----------------------------------------------

                perfil_obj.bloqueado_hasta = None
                perfil_obj.intentos_fallidos = 0
                perfil_obj.save()

        # 2. Autenticación normal
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
                # --- Éxito: Resetear intentos fallidos ---
                if perfil.intentos_fallidos > 0:
                    perfil.intentos_fallidos = 0
                    perfil.bloqueado_hasta = None
                    perfil.save()

                detalles_registro = {
                    'usuario_id': user.pk,
                    'rol_principal': perfil.rol, # Asumiendo que 'perfil.rol' existe
                    # Opcional: registrar la IP del cliente
                    'ip_address': request.META.get('REMOTE_ADDR'), 
                }
                
                registrar_bitacora_estructurada(
                    negocio=user.perfilusuario.negocio,
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
            # --- Fallo: Incrementar intentos ---
            # Si el formulario no es válido, puede ser usuario incorrecto o contraseña incorrecta.
            # Solo incrementamos si encontramos al usuario (obtenido al inicio).
            if perfil_obj:
                perfil_obj.intentos_fallidos += 1
                MAX_INTENTOS = 3
                
                if perfil_obj.intentos_fallidos >= MAX_INTENTOS:
                    perfil_obj.bloqueado_hasta = timezone.now() + timedelta(minutes=10) # 10 minutos de bloqueo
                    perfil_obj.save(update_fields=['intentos_fallidos', 'bloqueado_hasta'])
                    
                    # --- Registro Bitácora Bloqueo ---
                    try:
                        registrar_bitacora_estructurada(
                            negocio=perfil_obj.negocio,
                            usuario=user_obj,
                            nombre_modelo="Usuario",
                            tipo_accion="USUARIO_BLOQUEADO",
                            accion=f"Usuario {user_obj.username} bloqueado por múltiples intentos fallidos.",
                            entidad_id=user_obj.pk,
                            detalles={
                                'usuario_bloqueado_id': user_obj.pk,
                                'intentos_fallidos': perfil_obj.intentos_fallidos,
                                'bloqueado_hasta': str(perfil_obj.bloqueado_hasta)
                            }
                        )
                    except Exception:
                        pass
                    # ---------------------------------

                    messages.error(request, "Cuenta bloqueada por múltiples intentos fallidos. Intente en 10 minutos.")
                else:
                    perfil_obj.save(update_fields=['intentos_fallidos'])
                    restantes = MAX_INTENTOS - perfil_obj.intentos_fallidos
                    # Warning adicional
                    messages.warning(request, f"Contraseña incorrecta. Te quedan {restantes} intentos antes del bloqueo.")
            
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
                negocio=request.user.perfilusuario.negocio,
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

@rol_requerido("ADMIN")
def usuario_desbloquear_view(request, pk):
    """
    Desbloquea un usuario reseteando sus intentos fallidos y fecha de bloqueo.
    """
    perfil = get_object_or_404(PerfilUsuario, pk=pk)
    
    perfil.intentos_fallidos = 0
    perfil.bloqueado_hasta = None
    perfil.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
    
    # Registro en bitácora
    try:
        registrar_bitacora_estructurada(
            negocio=perfil.negocio,
            usuario=request.user,
            nombre_modelo="Usuario",
            tipo_accion="USUARIO_DESBLOQUEADO", # Usamos un tipo específico
            accion=f"Usuario '{perfil.user.username}' (ID: {perfil.user.pk}) desbloqueado manualmente por {request.user.username}.",
            entidad_id=perfil.user.pk,
            detalles={
                'usuario_desbloqueado_id': perfil.user.pk,
                'admin_responsable_id': request.user.pk,
            }
        )
    except Exception:
        pass

    messages.success(request, f"Usuario {perfil.user.username} desbloqueado correctamente.")
    return redirect("core:usuarios_lista")


class CustomPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    success_url = reverse_lazy("password_reset_done")
    # email_template_name y subject_template_name ya no son necesarios si sobreescribimos el envío, 
    # pero los dejamos por compatibilidad si algo falla.

    def form_valid(self, form):
        email = form.cleaned_data.get('email')
        
        # 1. Buscar usuarios
        users = list(User.objects.filter(email=email, is_active=True))
        
        if not users:
            # Por seguridad, no decimos que el usuario no existe,
            # pero podemos logear el intento fallido si queremos.
            pass
        
        # 2. Enviar correo "a mano" usando nuestra función `enviar_correo_restablecer_password` (Resend)
        # Esto reemplaza el form.save() de Django que usa el SMTP nativo.
        for user in users:
            # Generar token y uid
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Construir URL absoluta
            # Si tienes configurado un SITE_URL en settings, úsalo, sino construye uno básico
            protocol = 'https' if self.request.is_secure() else 'http'
            domain = self.request.get_host()
            reset_url = f"{protocol}://{domain}{reverse_lazy('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})}"
            
            # Enviar correo personalizado
            try:
                enviar_correo_restablecer_password(user, reset_url)
                
                # Registro en Bitácora
                registrar_bitacora_estructurada(
                    negocio=user.perfilusuario.negocio if hasattr(user, 'perfilusuario') else None,
                    usuario=user,
                    nombre_modelo="Usuario",
                    tipo_accion="SOLICITUD_RESET_PASSWORD",
                    accion=f"Email de recuperación enviado a {user.username} via Resend.",
                    entidad_id=user.pk,
                    detalles={
                        'email_solicitante': email,
                        'servicio_email': 'Resend API',
                    }
                )
            except Exception as e:
                print(f"Error enviando correo recovery a {email}: {e}")
        
        # Redirigir a "Done"
        return redirect(self.success_url)


class BitacoraListView(LoginRequiredMixin, ListView):
    model = BitacoraAccion
    template_name = 'core/bitacora/bitacoras.html'
    context_object_name = 'logs'
    paginate_by = 50 

    # Definimos las áreas funcionales disponibles para el filtro
    AREAS_FUNCIONALES = [
        'Venta', 'Inventario', 'PedidoOnline', 'Caja', 'Usuario','Log'
    ]
    
    # Tipos de acción disponibles
    TIPOS_ACCION = [
        ('CREACION_USUARIO', 'Creación de Usuario'),
        ('EDICION_USUARIO', 'Edición de Usuario'),
        ('USUARIO_ACTIVADO', 'Usuario Activado'),
        ('USUARIO_DESACTIVADO', 'Usuario Desactivado'),
        ('USUARIO_BLOQUEADO', 'Usuario Bloqueado'),
        ('USUARIO_DESBLOQUEADO', 'Usuario Desbloqueado'),
        ('SOLICITUD_RESET_PASSWORD', 'Solicitud Reset Password'),
        ('LOGIN', 'Inicio de Sesión'),
        ('LOGOUT', 'Cierre de Sesión'),
        ('CAMBIO_ESTADO', 'Cambio de Estado'),
        ('CAMBIO_ESTADO_PREPARACION', 'Cambio Estado Preparación'),
        ('CANCELACION_PEDIDO', 'Cancelación'),
        ('NO_RETIRA_PEDIDO', 'No Retira'),
    ]

    def get_queryset(self):
        from django.utils import timezone
        from datetime import datetime, timedelta
        
        # 1. Obtener el QuerySet base
        queryset = super().get_queryset().select_related('usuario', 'negocio').order_by('-fecha_hora')
        
        # 2. Filtro por área
        filtro_area = self.request.GET.get('area')
        if filtro_area and filtro_area in self.AREAS_FUNCIONALES:
            queryset = queryset.filter(nombre_modelo__iexact=filtro_area)
        
        # 3. Filtro por tipo de acción
        filtro_tipo = self.request.GET.get('tipo_accion')
        if filtro_tipo:
            queryset = queryset.filter(tipo_accion=filtro_tipo)
        
        # 4. Filtro por usuario
        filtro_usuario = self.request.GET.get('usuario')
        if filtro_usuario:
            queryset = queryset.filter(usuario_id=filtro_usuario)
        
        # 5. Filtro por rango de fechas
        fecha_desde = self.request.GET.get('fecha_desde')
        fecha_hasta = self.request.GET.get('fecha_hasta')
        
        if fecha_desde:
            try:
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d')
                queryset = queryset.filter(fecha_hora__gte=fecha_desde_obj)
            except ValueError:
                pass
        
        if fecha_hasta:
            try:
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d')
                # Incluir todo el día hasta las 23:59:59
                fecha_hasta_obj = fecha_hasta_obj.replace(hour=23, minute=59, second=59)
                queryset = queryset.filter(fecha_hora__lte=fecha_hasta_obj)
            except ValueError:
                pass
        
        # 6. Búsqueda de texto en acción
        q = (self.request.GET.get('q') or '').strip()
        if q:
            queryset = queryset.filter(accion__icontains=q)
            
        return queryset

    def get_context_data(self, **kwargs):
        from django.contrib.auth.models import User
        
        context = super().get_context_data(**kwargs)
        
        # Pasar opciones de filtro
        context['areas_funcionales'] = self.AREAS_FUNCIONALES
        context['tipos_accion'] = self.TIPOS_ACCION
        context['usuarios'] = User.objects.filter(is_active=True).order_by('username')
        
        # Pasar valores actuales de filtros
        context['area_activa'] = self.request.GET.get('area', '')
        context['tipo_accion_activo'] = self.request.GET.get('tipo_accion', '')
        context['usuario_activo'] = self.request.GET.get('usuario', '')
        context['fecha_desde'] = self.request.GET.get('fecha_desde', '')
        context['fecha_hasta'] = self.request.GET.get('fecha_hasta', '')
        context['q'] = self.request.GET.get('q', '')
        
        # Contar total de resultados (sin paginación)
        context['total_resultados'] = self.get_queryset().count()
        
        return context


@login_required
def bitacora_export_csv(request):
    """Exporta los resultados filtrados de la bitácora a CSV"""
    import csv
    from django.http import HttpResponse
    from django.utils import timezone
    
    # Reutilizar la lógica de filtrado del ListView
    view = BitacoraListView()
    view.request = request
    queryset = view.get_queryset()
    
    # Crear respuesta CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bitacora_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    response.write('\ufeff')  # BOM para Excel UTF-8
    
    writer = csv.writer(response)
    
    # Encabezados
    writer.writerow([
        'Fecha/Hora',
        'Usuario',
        'Área',
        'Tipo Acción',
        'Acción',
        'ID Entidad',
    ])
    
    # Datos
    for log in queryset[:1000]:  # Limitar a 1000 registros
        writer.writerow([
            log.fecha_hora.strftime('%Y-%m-%d %H:%M:%S'),
            log.usuario.username if log.usuario else 'Sistema',
            log.nombre_modelo,
            log.tipo_accion,
            log.accion,
            log.entidad_id,
        ])
    
    return response


@login_required
def bitacora_export_pdf(request):
    """Exporta los resultados filtrados de la bitácora a PDF usando xhtml2pdf"""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.utils import timezone
    from xhtml2pdf import pisa
    from io import BytesIO
    
    # Reutilizar la lógica de filtrado del ListView
    view = BitacoraListView()
    view.request = request
    queryset = view.get_queryset()[:500]  # Limitar a 500 para PDF
    
    # Obtener filtros aplicados
    filtros_aplicados = []
    if request.GET.get('area'):
        filtros_aplicados.append(f"Área: {request.GET.get('area')}")
    if request.GET.get('tipo_accion'):
        filtros_aplicados.append(f"Tipo: {request.GET.get('tipo_accion')}")
    if request.GET.get('usuario'):
        user = User.objects.filter(id=request.GET.get('usuario')).first()
        if user:
            filtros_aplicados.append(f"Usuario: {user.username}")
    if request.GET.get('fecha_desde'):
        filtros_aplicados.append(f"Desde: {request.GET.get('fecha_desde')}")
    if request.GET.get('fecha_hasta'):
        filtros_aplicados.append(f"Hasta: {request.GET.get('fecha_hasta')}")
    if request.GET.get('q'):
        filtros_aplicados.append(f"Búsqueda: {request.GET.get('q')}")
 
    # Construir ruta absoluta manualmente para entornos de desarrollo donde staticfiles_storage.path puede fallar
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_gran_pirula_negro.jpg')

    # Contexto para el template
    context = {
        'logs': queryset,
        'fecha_generacion': timezone.now(),
        'usuario_exportacion': request.user,
        'filtros_aplicados': filtros_aplicados,
        'total_registros': queryset.count(),
        'logo_absolute_path': logo_path,
    }
    
    # Renderizar HTML
    html_string = render_to_string('core/bitacora/bitacora_pdf.html', context)
    
    # Generar PDF con xhtml2pdf
    from core.utils import link_callback
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result, link_callback=link_callback)
    
    if pdf.err:
        return HttpResponse('Error al generar PDF', status=500)
    
    # Crear respuesta
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bitacora_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    return response


@login_required
def bitacora_detalle_view(request, pk):
    """Vista de detalle para una entrada de bitácora"""
    import json
    
    log = get_object_or_404(BitacoraAccion, pk=pk)
    
    # Formatear JSON para mejor visualización
    detalles_formateados = json.dumps(log.detalles, indent=2, ensure_ascii=False) if log.detalles else '{}'
    
    context = {
        'log': log,
        'detalles_json': detalles_formateados,
    }
    
    return render(request, 'core/bitacora/bitacora_detalle.html', context)