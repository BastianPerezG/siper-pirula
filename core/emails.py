"""
Módulo de emails para core (recuperación de contraseña, etc.) usando Django's email backend.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def _get_logo_url():
    """Obtiene la URL del logo para emails."""
    base = getattr(settings, "SITE_URL", "")
    
    if base and "localhost" not in base and "127.0.0.1" not in base:
        return f"{base}{settings.STATIC_URL}img/logo_gran_pirula_marron.jpg"
    
    return ""


def _enviar_email(destinatario, subject, template_html, template_txt, context):
    """
    Envía email usando el backend SMTP de Django.
    Configurado para usar Gmail en settings.py.
    """
    if not destinatario:
        print("⚠️ No hay destinatario para el email")
        return False
    
    # Verificar configuración
    if not settings.EMAIL_HOST_USER:
        print("⚠️ EMAIL_HOST_USER no configurado. Email no enviado.")
        return False

    # Agregar datos comunes al contexto
    context = {
        **context,
        "subject": subject,
        "logo_url": _get_logo_url(),
    }

    # Renderizar templates
    try:
        cuerpo_html = render_to_string(template_html, context)
        cuerpo_txt = render_to_string(template_txt, context)
    except Exception as e:
        print(f"❌ Error al renderizar templates: {e}")
        return False

    # Preparar el email - usar DEFAULT_FROM_EMAIL para el remitente visible
    from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=cuerpo_txt,
            from_email=from_email,
            to=[destinatario],
        )
        email.attach_alternative(cuerpo_html, "text/html")
        
        # Enviar
        email.send(fail_silently=False)
        print(f"✅ Email enviado exitosamente a {destinatario}")
        return True
        
    except Exception as e:
        print(f"❌ Error al enviar email a {destinatario}: {e}")
        return False


def enviar_correo_restablecer_password(usuario, reset_url, uid, token):
    """
    Envía el correo de restablecimiento de contraseña.
    """
    subject = "Restablecer contraseña - El Gran Pirula"
    
    context = {
        "user": usuario,
        "reset_url": reset_url,
        "uid": uid,
        "uidb64": uid,  # Alias para compatibilidad
        "token": token,
    }
    
    print(f"📧 Enviando correo de recuperación a {usuario.email}")
    print(f"🔗 URL: {reset_url}")
    
    return _enviar_email(
        destinatario=usuario.email,
        subject=subject,
        template_html="registration/password_reset_email_html.html",
        template_txt="registration/password_reset_email.html",
        context=context,
    )
