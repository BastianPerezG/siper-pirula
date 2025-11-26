from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string



def _get_logo_url():
    base = getattr(settings, "SITE_URL", "http://localhost:8000")
    return f"{base}{settings.STATIC_URL}img/logo_gran_pirula_marron.jpg"



def _enviar_email_template(destinatario, subject, template_html, template_txt, context):
    if not destinatario:
        return

    context = {
        **context,
        "subject": subject,
        "logo_url": _get_logo_url(),
    }

    cuerpo_html = render_to_string(template_html, context)
    cuerpo_txt = render_to_string(template_txt, context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=cuerpo_txt,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@granpirula.local"),
        to=[destinatario],
    )
    msg.attach_alternative(cuerpo_html, "text/html")
    msg.send(fail_silently=False)


def enviar_correo_pedido_creado(pedido):
    subject = f"SIPER Pirula - Pedido recibido ({pedido.codigo})"
    _enviar_email_template(
        destinatario=pedido.correo,
        subject=subject,
        template_html="emails/pedido_creado.html",
        template_txt="emails/pedido_creado.txt",
        context={"pedido": pedido},
    )


def enviar_correo_cambio_estado(pedido):
    if not pedido.correo:
        return

    try:
        estado_display = pedido.get_estado_display()
    except Exception:
        estado_display = str(pedido.estado)

    try:
        es_listo = pedido.estado == pedido.EST_LISTO
    except AttributeError:
        es_listo = (str(pedido.estado).upper() == "LISTO")

    subject = (
        f"SIPER Pirula - Tu pedido {pedido.codigo} está LISTO para retirar"
        if es_listo
        else f"SIPER Pirula - Actualización de tu pedido ({pedido.codigo})"
    )

    _enviar_email_template(
        destinatario=pedido.correo,
        subject=subject,
        template_html="emails/pedido_cambio_estado.html",
        template_txt="emails/pedido_cambio_estado.txt",
        context={
            "pedido": pedido,
            "estado_display": estado_display,
            "es_listo": es_listo,
        },
    )
