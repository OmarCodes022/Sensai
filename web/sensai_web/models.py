"""Which models Ollama has, and switching the chat to one of them."""
from sensai_web.errors import ApiError
from sensai_web.health import fetch_tags, installed


def models(app) -> dict:
    reachable, _latency, names = fetch_tags(app.health.host)
    return {"current": app.model, "reachable": reachable, "installed": sorted(names)}


def set_model(app, name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ApiError(400, "bad_model", "Choose a model.")
    name = name.strip()
    reachable, _latency, names = fetch_tags(app.health.host)
    if not reachable:
        raise ApiError(503, "ollama_unreachable", "Ollama is not reachable, so the model cannot be checked.")
    if not installed(name, names):
        raise ApiError(404, "model_unknown", f"{name} is not installed. Run: ollama pull {name}")
    with app.mutex:
        app.require_idle()
        app.model = app.active.session.model = name
        app.health.set_model(name)
    return name
