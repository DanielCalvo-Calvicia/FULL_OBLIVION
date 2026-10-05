"""The final environment of one service: its layers merged, checked, and traced back to the file each value came from.

Layers, lowest to highest priority (a later layer overrides an earlier one):

1. ``defaults``              the service repo's own ``.env.example``
2. ``catalogue``             ``[services.<name>.env]`` in config/catalogue.toml (what a deployed machine needs by default)
3. ``computed``              SERVICE_HOST / SERVICE_PORT (or the service's own names) and the base URLs of the services it calls
4. ``services/all.toml``     ``[env]``: a value once, for every service that uses the variable
5. ``local/all.toml``        yours, same idea
6. ``services/<name>.toml``  ``[env]``: this service's own settings
7. ``local/<name>.toml``     yours: private overrides and keys

Each value is reported with the layer that set it, so ``oblivion.py env`` answers "where did this come from?".
"""

from __future__ import annotations

from domain.entities.environment import ResolvedEnv
from domain.entities.host import EnvLayer, Host
from domain.rules.dotenv import parse_env
from domain.rules.env_names import computed_variables, known_variables
from domain.rules.topology import service_url

LAYER_DEFAULTS, LAYER_CATALOGUE, LAYER_COMPUTED = "defaults", "catalogue", "computed"


def resolve_env(host: Host, name: str, defaults_text: str | None) -> ResolvedEnv:
    instance = host.services[name]
    spec = instance.spec
    resolved = ResolvedEnv()

    is_known, documented = known_variables(spec, defaults_text)  # without the example we cannot tell typos
    if defaults_text is not None:
        for key, value in parse_env(defaults_text).items():
            resolved.set(LAYER_DEFAULTS, key, value)
    for key, value in spec.env.items():
        resolved.set(LAYER_CATALOGUE, key, value)

    bind = "0.0.0.0" if instance.runtime == "docker" else host.bind
    resolved.set(LAYER_COMPUTED, spec.host_var, bind)
    resolved.set(LAYER_COMPUTED, spec.port_var, str(instance.port))
    for target, var in spec.consumes.items():
        url = service_url(host, instance, target)
        if url:
            resolved.set(LAYER_COMPUTED, var, url)
    computed = computed_variables(spec)

    def how_to_set(key: str) -> str:
        return f'set {key} = "..." in config/local/{name}.toml (or in config/local/all.toml for every service that uses it)'

    def apply(layer: EnvLayer) -> None:
        for key, value in layer.values.items():
            if layer.shared and (key == "SERVICE_NAME" or key in computed or not is_known(key)):
                continue  # all.toml only reaches the services that use the variable
            resolved.set(layer.label, key, value)
            if layer.shared:
                continue
            if key in computed:
                resolved.warnings.append(
                    f"{name}: {key} is computed from the layout (address, port, URLs of the other services); the value in "
                    f"{layer.label} wins here, but the other services still use the computed one, so they will not find each other"
                )
            elif documented and not is_known(key):
                resolved.warnings.append(f"{name}: {key} is set in {layer.label} but the service does not document it (typo?)")

    for layer in instance.layers:
        apply(layer)

    if spec.require_any and not any(resolved.values.get(key) for key in spec.require_any):
        resolved.warnings.append(
            f"{name}: none of {', '.join(spec.require_any)} is set, so it will report itself not available; "
            f"{how_to_set('GROQ_API_KEY')}"
        )

    for key, value in resolved.values.items():
        if "${" in value:  # python-dotenv expands ${NAME} in every value, quoted or not, and offers no way to stop it
            resolved.errors.append(
                f"{name}: {key} contains '${{', which python-dotenv would expand when the service reads its .env; "
                "change the value"
            )

    for rule in spec.require:
        if all(resolved.values.get(k) == v for k, v in rule.when.items()) and not resolved.values.get(rule.key):
            condition = ", ".join(f"{k}={v}" for k, v in rule.when.items())
            resolved.errors.append(
                f"{name}: {rule.key} is required" + (f" when {condition}" if condition else "") + f"; {how_to_set(rule.key)}"
            )
    return resolved
