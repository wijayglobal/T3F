from urllib.parse import urlparse

from django import template

register = template.Library()


@register.filter
def get(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def domain_label(slug):
    """"home-science" -> "Home science"."""
    return (slug or "").replace("-", " ").capitalize()


@register.filter
def safe_url(url):
    """The URL if it is http(s), else "" — imported rows skip form validation, so never trust
    a stored link to be free of `javascript:` or `data:` schemes before putting it in an href."""
    url = (url or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else ""
