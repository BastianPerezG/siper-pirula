from django.views.generic import TemplateView

# Views Core

class DashboardView(TemplateView):
    template_name = "core/dashboard.html"