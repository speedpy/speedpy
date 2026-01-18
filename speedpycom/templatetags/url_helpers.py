from django import template

register = template.Library()


@register.filter
def url_starts_with(url_name, prefix):
    """Check if a URL name starts with the given prefix.

    Args:
        url_name: The URL name to check (typically from request.resolver_match.url_name)
        prefix: The prefix to check against

    Returns:
        Boolean indicating if url_name starts with prefix

    Example:
        {% if request.resolver_match.url_name|url_starts_with:'team_http_monitor' %}
            <a href="..." class="active">HTTP Monitors</a>
        {% endif %}
    """
    if not url_name or not prefix:
        return False
    return str(url_name).startswith(str(prefix))


@register.filter
def url_in_prefix_list(url_name, prefixes):
    """Check if URL name starts with any prefix in comma-separated list.

    Args:
        url_name: The URL name to check (typically from request.resolver_match.url_name)
        prefixes: Comma-separated string of prefixes to check

    Returns:
        Boolean indicating if url_name starts with any of the prefixes

    Example:
        {% if request.resolver_match.url_name|url_in_prefix_list:'team_http_monitor,team_status_page' %}
            <div class="monitoring-section">...</div>
        {% endif %}
    """
    if not url_name or not prefixes:
        return False
    prefix_list = [p.strip() for p in str(prefixes).split(',')]
    return any(str(url_name).startswith(p) for p in prefix_list)
