"""Every page's header: three places in the bar, everything else behind the ⋮ menu (static/theme.js).

The menu is written into each page rather than built by script, so six copies exist. These
tests keep them the same.
"""

import re

import pytest

BAR = ["/", "/dashboard", "/map"]
MENU = ["/field-guide", "/api/export.csv", "/docs", "/developers", "/about"]


def section(page: str, pattern: str) -> str:
    match = re.search(pattern, page, re.S)
    assert match, pattern
    return match.group(1)


def links(html: str) -> list[str]:
    return [h for h in re.findall(r'href="([^"]+)"', html) if h != "#"]  # "#" is the check page's ID guide


@pytest.mark.parametrize("path", ["/", "/dashboard", "/about", "/site/any-spot", "/developers"])
def test_the_bar_holds_three_places_and_the_menu_holds_the_rest(client, path):
    page = client.get(path).text
    assert links(section(page, r"<nav>(.*?)</nav>")) == BAR
    menu = section(page, r'<details class="menu">(.*?)</details>')
    assert links(menu) == MENU
    assert "data-theme-switch" in menu  # the light/dark switch lives in the menu
    assert "data-open-guide" in menu and '<script src="/static/guide.js">' in page  # the ID guide opens on any page


def test_the_map_floats_the_same_menu(client):
    page = client.get("/map").text
    menu = section(page, r'<details class="menu floating">(.*?)</details>')
    assert links(menu) == MENU
    assert "data-theme-switch" in menu
    assert "data-open-guide" in menu and '<script src="/static/guide.js">' in page


def test_the_id_guide_works_offline_on_the_check_page(client):
    assert '"/static/guide.js"' in client.get("/sw.js").text  # cached with the shell, like theme.js
