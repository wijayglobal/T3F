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
