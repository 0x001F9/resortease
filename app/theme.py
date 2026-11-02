from functools import wraps

from django.shortcuts import redirect


DAISYUI_THEMES = (
    "light",
    "dark",
    "cupcake",
    "bumblebee",
    "emerald",
    "corporate",
    "synthwave",
    "retro",
    "cyberpunk",
    "valentine",
    "halloween",
    "garden",
    "forest",
    "aqua",
    "lofi",
    "pastel",
    "fantasy",
    "wireframe",
    "black",
    "luxury",
    "dracula",
    "cmyk",
    "autumn",
    "business",
    "acid",
    "lemonade",
    "night",
    "coffee",
    "winter",
    "dim",
    "nord",
    "sunset",
    "caramellatte",
    "abyss",
    "silk",
)

DEFAULT_THEME = "forest"
THEME_COOKIE_NAME = "resortease_theme"


def valid_theme(theme):
    return theme if theme in DAISYUI_THEMES else DEFAULT_THEME


def theme_context(request):
    return {
        "current_theme": valid_theme(request.COOKIES.get(THEME_COOKIE_NAME)),
        "daisyui_themes": DAISYUI_THEMES,
    }


def with_theme(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        request.theme = valid_theme(request.COOKIES.get(THEME_COOKIE_NAME))
        return view_func(request, *args, **kwargs)

    return wrapper
