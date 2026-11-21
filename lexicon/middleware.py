"""Security headers Django 5.1 does not set on its own."""
from django.conf import settings

# Scripts only from our own origin (no inline scripts or event handlers anywhere in the templates).
# Styles allow 'unsafe-inline' for the few style="" attributes; fonts come from Google Fonts.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
])

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    """Add Content-Security-Policy, Permissions-Policy and Cross-Origin-Opener-Policy.

    A view can opt in to being framed by other sites by setting `response.frame_ancestors`
    (see `views.embed_card`); everything else refuses framing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEBUG and response.status_code >= 500:
            return response  # Django's technical error page relies on inline scripts
        ancestors = getattr(response, "frame_ancestors", "'none'")
        csp = CONTENT_SECURITY_POLICY.replace("frame-ancestors 'none'", f"frame-ancestors {ancestors}")
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
