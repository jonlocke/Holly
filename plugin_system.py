import importlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger(__name__)

PLUGIN_API_VERSION = "1.0"
DEFAULT_PLUGIN_TIMEOUT_SECONDS = 2.0
ALLOWED_PLUGIN_PERMISSIONS = {"network", "filesystem", "messaging"}
EVENT_MESSAGE = "message"
EVENT_COMMAND = "command"
EVENT_BEFORE_RESPONSE = "before_response"
EVENT_AFTER_RESPONSE = "after_response"
HOOK_EVENT_MAP = {
    "on_message": EVENT_MESSAGE,
    "on_command": EVENT_COMMAND,
    "on_before_response": EVENT_BEFORE_RESPONSE,
    "on_after_response": EVENT_AFTER_RESPONSE,
}


class PluginError(Exception):
    pass


class PluginManifestError(PluginError):
    pass


class PluginLoadError(PluginError):
    pass


class PluginPermissionError(PluginError):
    pass


class PluginTimeoutError(PluginError):
    pass


@dataclass(slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
    plugin_api_version: str
    entrypoint: str
    description: str
    required_config_keys: list[str]
    permissions: list[str]
    enabled: bool


@dataclass(slots=True)
class PluginRuntime:
    manifest: PluginManifest
    path: Path
    module_name: str
    module: ModuleType
    instance: Any
    enabled: bool = False


class EventBus:
    def __init__(self, manager: "PluginManager"):
        self.manager = manager
        self._subscribers: dict[str, list[str]] = {event: [] for event in HOOK_EVENT_MAP.values()}
        self._lock = threading.Lock()

    def subscribe(self, event_name: str, plugin_id: str) -> None:
        with self._lock:
            subscribers = self._subscribers.setdefault(event_name, [])
            if plugin_id not in subscribers:
                subscribers.append(plugin_id)

    def unsubscribe(self, plugin_id: str) -> None:
        with self._lock:
            for subscribers in self._subscribers.values():
                while plugin_id in subscribers:
                    subscribers.remove(plugin_id)

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        with self._lock:
            subscriber_ids = list(self._subscribers.get(event_name, []))

        results: list[dict[str, Any]] = []
        for plugin_id in subscriber_ids:
            result = self.manager._invoke_event(plugin_id, event_name, *args, **kwargs)
            if result is not None:
                results.append(result)
        return results


class PluginManager:
    def __init__(
        self,
        plugins_root: Path | str,
        app_context: dict[str, Any],
        *,
        plugin_api_version: str = PLUGIN_API_VERSION,
        default_timeout_seconds: float = DEFAULT_PLUGIN_TIMEOUT_SECONDS,
        trusted_plugins: set[str] | None = None,
    ):
        self.plugins_root = Path(plugins_root)
        self.app_context = app_context
        self.plugin_api_version = plugin_api_version
        self.default_timeout_seconds = default_timeout_seconds
        self.trusted_plugins = trusted_plugins or set()
        self._runtimes: dict[str, PluginRuntime] = {}
        self._command_registry: dict[str, str] = {}
        self._tool_registry: dict[str, str] = {}
        self._lock = threading.RLock()
        self.event_bus = EventBus(self)

    @property
    def command_registry(self) -> dict[str, str]:
        with self._lock:
            return dict(self._command_registry)

    @property
    def runtimes(self) -> dict[str, PluginRuntime]:
        with self._lock:
            return dict(self._runtimes)

    @property
    def tool_registry(self) -> dict[str, str]:
        with self._lock:
            return dict(self._tool_registry)

    def discover(self) -> list[tuple[Path, PluginManifest]]:
        manifests: list[tuple[Path, PluginManifest]] = []
        if not self.plugins_root.exists():
            return manifests

        for manifest_path in sorted(self.plugins_root.rglob("manifest.json")):
            try:
                manifests.append((manifest_path.parent, self._load_manifest(manifest_path)))
            except PluginManifestError as exc:
                logger.warning("Skipping invalid plugin manifest '%s': %s", manifest_path, exc)
        return manifests

    def load_all_enabled(self) -> list[str]:
        loaded_ids: list[str] = []
        for plugin_dir, manifest in self.discover():
            if not manifest.enabled:
                continue
            try:
                self.load_plugin(plugin_dir, manifest=manifest)
                loaded_ids.append(manifest.id)
            except PluginError as exc:
                logger.warning("Failed to load plugin '%s': %s", manifest.id, exc)
        return loaded_ids

    def load_plugin(self, plugin_dir: Path | str, *, manifest: PluginManifest | None = None) -> PluginRuntime:
        plugin_path = Path(plugin_dir)
        manifest = manifest or self._load_manifest(plugin_path / "manifest.json")
        self._validate_manifest(manifest)
        self._ensure_plugin_allowed(manifest)

        module_name, class_name = self._split_entrypoint(manifest.entrypoint)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise PluginLoadError(f"Unable to import module '{module_name}': {exc}") from exc

        try:
            plugin_cls = getattr(module, class_name)
        except AttributeError as exc:
            raise PluginLoadError(
                f"Entrypoint '{manifest.entrypoint}' did not resolve to a class."
            ) from exc

        instance = plugin_cls()
        self._validate_plugin_contract(instance, manifest)
        runtime = PluginRuntime(
            manifest=manifest,
            path=plugin_path,
            module_name=module_name,
            module=module,
            instance=instance,
        )

        with self._lock:
            if manifest.id in self._runtimes:
                raise PluginLoadError(f"Plugin '{manifest.id}' is already loaded.")
            self._runtimes[manifest.id] = runtime

        try:
            self._invoke_lifecycle(runtime, "on_load", self.app_context)
            self._register_hooks(runtime)
            runtime.enabled = True
        except Exception:
            with self._lock:
                self._runtimes.pop(manifest.id, None)
            self.event_bus.unsubscribe(manifest.id)
            self._unregister_tools(manifest.id)
            raise

        logger.info("Loaded plugin '%s' version %s", manifest.id, manifest.version)
        return runtime

    def unload_plugin(self, plugin_id: str) -> None:
        with self._lock:
            runtime = self._runtimes.get(plugin_id)
        if not runtime:
            return

        self.event_bus.unsubscribe(plugin_id)
        self._unregister_commands(plugin_id)
        self._unregister_tools(plugin_id)
        try:
            self._invoke_lifecycle(runtime, "on_unload")
        finally:
            with self._lock:
                self._runtimes.pop(plugin_id, None)
            runtime.enabled = False

    def reload_plugin(self, plugin_id: str) -> PluginRuntime:
        with self._lock:
            runtime = self._runtimes.get(plugin_id)
        if not runtime:
            raise PluginLoadError(f"Plugin '{plugin_id}' is not loaded.")

        manifest_path = runtime.path / "manifest.json"
        self.unload_plugin(plugin_id)
        return self.load_plugin(runtime.path, manifest=self._load_manifest(manifest_path))

    def enable_plugin(self, plugin_id: str) -> PluginRuntime:
        manifest_path = self.plugins_root / plugin_id / "manifest.json"
        if not manifest_path.exists():
            raise PluginLoadError(f"Plugin '{plugin_id}' was not found.")
        return self.load_plugin(manifest_path.parent, manifest=self._load_manifest(manifest_path))

    def disable_plugin(self, plugin_id: str) -> None:
        self.unload_plugin(plugin_id)

    def dispatch_message(self, message: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return self.event_bus.emit(EVENT_MESSAGE, message, context)

    def dispatch_command(self, command: str, args: list[str], context: dict[str, Any]) -> list[dict[str, Any]]:
        owner = self.command_registry.get(command)
        if not owner:
            return []
        result = self._invoke_event(owner, EVENT_COMMAND, command, args, context)
        return [result] if result is not None else []

    def dispatch_before_response(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        return self.event_bus.emit(EVENT_BEFORE_RESPONSE, context)

    def dispatch_after_response(self, response: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return self.event_bus.emit(EVENT_AFTER_RESPONSE, response, context)

    def dispatch_tool(self, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        normalized_name = str(tool_name or "").strip()
        if not normalized_name:
            return None

        owner = self.tool_registry.get(normalized_name)
        if not owner:
            return None

        with self._lock:
            runtime = self._runtimes.get(owner)
        if not runtime or not runtime.enabled:
            return None

        method = getattr(runtime.instance, "call_tool", None)
        if not callable(method):
            return None

        try:
            return self._call_with_timeout(runtime, method, normalized_name, arguments or {}, context)
        except PluginTimeoutError as exc:
            logger.warning("Plugin '%s' timed out in call_tool: %s", owner, exc)
        except Exception as exc:
            logger.warning("Plugin '%s' failed in call_tool: %s", owner, exc)
        return None

    def _invoke_event(self, plugin_id: str, event_name: str, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        with self._lock:
            runtime = self._runtimes.get(plugin_id)
        if not runtime or not runtime.enabled:
            return None

        method_name = next((hook for hook, event in HOOK_EVENT_MAP.items() if event == event_name), None)
        if not method_name:
            return None

        method = getattr(runtime.instance, method_name, None)
        if not callable(method):
            return None

        try:
            return self._call_with_timeout(runtime, method, *args, **kwargs)
        except PluginTimeoutError as exc:
            logger.warning("Plugin '%s' timed out in %s: %s", plugin_id, method_name, exc)
        except Exception as exc:
            logger.warning("Plugin '%s' failed in %s: %s", plugin_id, method_name, exc)
        return None

    def _invoke_lifecycle(self, runtime: PluginRuntime, method_name: str, *args: Any) -> Any:
        method = getattr(runtime.instance, method_name, None)
        if not callable(method):
            return None
        return self._call_with_timeout(runtime, method, *args)

    def _register_hooks(self, runtime: PluginRuntime) -> None:
        for hook_name, event_name in HOOK_EVENT_MAP.items():
            if callable(getattr(runtime.instance, hook_name, None)):
                self.event_bus.subscribe(event_name, runtime.manifest.id)

        commands = getattr(runtime.instance, "commands", {}) or {}
        if not isinstance(commands, dict):
            raise PluginLoadError(f"Plugin '{runtime.manifest.id}' commands must be a dict.")

        tools = getattr(runtime.instance, "tools", {}) or {}
        if not isinstance(tools, dict):
            raise PluginLoadError(f"Plugin '{runtime.manifest.id}' tools must be a dict.")

        with self._lock:
            for command_name in commands:
                normalized = self._normalize_command_name(command_name)
                existing = self._command_registry.get(normalized)
                if existing and existing != runtime.manifest.id:
                    raise PluginLoadError(
                        f"Command '{normalized}' is already registered by plugin '{existing}'."
                    )
                self._command_registry[normalized] = runtime.manifest.id

            for tool_name in tools:
                normalized_tool = str(tool_name or "").strip()
                if not normalized_tool:
                    raise PluginLoadError(f"Plugin '{runtime.manifest.id}' declared an empty tool name.")
                existing_tool = self._tool_registry.get(normalized_tool)
                if existing_tool and existing_tool != runtime.manifest.id:
                    raise PluginLoadError(
                        f"Tool '{normalized_tool}' is already registered by plugin '{existing_tool}'."
                    )
                self._tool_registry[normalized_tool] = runtime.manifest.id

    def _unregister_commands(self, plugin_id: str) -> None:
        with self._lock:
            stale_commands = [name for name, owner in self._command_registry.items() if owner == plugin_id]
            for name in stale_commands:
                self._command_registry.pop(name, None)

    def _unregister_tools(self, plugin_id: str) -> None:
        with self._lock:
            stale_tools = [name for name, owner in self._tool_registry.items() if owner == plugin_id]
            for name in stale_tools:
                self._tool_registry.pop(name, None)

    def _call_with_timeout(self, runtime: PluginRuntime, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            try:
                result["value"] = func(*args, **kwargs)
            except BaseException as exc:  # pragma: no cover - passed through below.
                error["value"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        timeout_seconds = float(getattr(runtime.instance, "timeout_seconds", self.default_timeout_seconds))
        thread.join(timeout_seconds)
        if thread.is_alive():
            raise PluginTimeoutError(
                f"Plugin '{runtime.manifest.id}' exceeded timeout of {timeout_seconds:.2f}s."
            )
        if "value" in error:
            raise error["value"]
        return result.get("value")

    def _load_manifest(self, manifest_path: Path) -> PluginManifest:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PluginManifestError(f"Unable to read manifest: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"Manifest is not valid JSON: {exc}") from exc

        required_fields = {
            "id", "name", "version", "plugin_api_version", "entrypoint", "description", "required_config_keys", "permissions", "enabled"
        }
        missing = sorted(required_fields - payload.keys())
        if missing:
            raise PluginManifestError(f"Manifest is missing fields: {', '.join(missing)}")

        manifest = PluginManifest(
            id=str(payload["id"]).strip(),
            name=str(payload["name"]).strip(),
            version=str(payload["version"]).strip(),
            plugin_api_version=str(payload["plugin_api_version"]).strip(),
            entrypoint=str(payload["entrypoint"]).strip(),
            description=str(payload["description"]).strip(),
            required_config_keys=list(payload["required_config_keys"]),
            permissions=list(payload["permissions"]),
            enabled=bool(payload["enabled"]),
        )
        self._validate_manifest(manifest)
        return manifest

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        if not manifest.id:
            raise PluginManifestError("Manifest id must not be empty.")
        if manifest.plugin_api_version != self.plugin_api_version:
            raise PluginManifestError(
                f"Plugin '{manifest.id}' expects API {manifest.plugin_api_version}, "
                f"but Holly provides {self.plugin_api_version}."
            )
        if ":" not in manifest.entrypoint:
            raise PluginManifestError("Manifest entrypoint must use module.path:ClassName format.")
        invalid_permissions = sorted(set(manifest.permissions) - ALLOWED_PLUGIN_PERMISSIONS)
        if invalid_permissions:
            raise PluginManifestError(
                f"Plugin '{manifest.id}' declares unsupported permissions: {', '.join(invalid_permissions)}"
            )
        if not isinstance(manifest.required_config_keys, list):
            raise PluginManifestError("Manifest required_config_keys must be a list.")

    def _validate_plugin_contract(self, instance: Any, manifest: PluginManifest) -> None:
        if str(getattr(instance, "id", "")).strip() != manifest.id:
            raise PluginLoadError(f"Plugin class id must match manifest id '{manifest.id}'.")
        if str(getattr(instance, "version", "")).strip() != manifest.version:
            raise PluginLoadError(f"Plugin class version must match manifest version '{manifest.version}'.")
        if not callable(getattr(instance, "on_load", None)):
            raise PluginLoadError(f"Plugin '{manifest.id}' must define on_load(app_context).")
        if not callable(getattr(instance, "on_unload", None)):
            raise PluginLoadError(f"Plugin '{manifest.id}' must define on_unload().")

    def _split_entrypoint(self, entrypoint: str) -> tuple[str, str]:
        module_name, class_name = entrypoint.split(":", maxsplit=1)
        return module_name.strip(), class_name.strip()

    def _ensure_plugin_allowed(self, manifest: PluginManifest) -> None:
        if self.trusted_plugins and manifest.id not in self.trusted_plugins:
            raise PluginPermissionError(f"Plugin '{manifest.id}' is not on the trusted allowlist.")

        config = self.app_context.get("config", {})
        plugin_config = config.get("plugins", {}).get(manifest.id, {}) if isinstance(config, dict) else {}
        missing_keys = [key for key in manifest.required_config_keys if key not in plugin_config]
        if missing_keys:
            raise PluginPermissionError(
                f"Plugin '{manifest.id}' is missing required config keys: {', '.join(missing_keys)}"
            )

    def _normalize_command_name(self, command_name: str) -> str:
        command_name = command_name.strip()
        if not command_name.startswith("/"):
            command_name = f"/{command_name}"
        return command_name.lower()
