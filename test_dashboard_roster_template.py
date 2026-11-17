from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class AdminUser:
    def is_admin(self):
        return True

    def is_teacher(self):
        return False


def test_dashboard_roster_partial_renders_when_included():
    templates = Path(__file__).parent / "templates"
    environment = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.from_string("{% include 'dashboard_roster.html' %}")

    rendered = template.render(
        current_user=AdminUser(),
        url_for=lambda endpoint: "/" + endpoint,
    )

    assert "Class Register by Learning Area" in rendered
