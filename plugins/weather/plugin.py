class Plugin:
    id = "weather"
    version = "0.1.0"
    timeout_seconds = 1.0

    def __init__(self):
        self.app_context = None
        self.commands = {"/weather": "Show configured weather provider status."}

    def on_load(self, app_context):
        self.app_context = app_context

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        provider = (
            self.app_context.get("config", {})
            .get("plugins", {})
            .get("weather", {})
            .get("provider", "demo")
        )
        location = " ".join(args).strip() or "your configured area"
        return {
            "type": "command_response",
            "command": command,
            "content": f"Weather plugin ({provider}) is configured for {location}.",
        }

    def on_before_response(self, context):
        context.setdefault("plugin_notes", []).append("weather:before_response")
        return {"type": "hook", "hook": "before_response"}

    def on_after_response(self, response, context):
        context.setdefault("plugin_notes", []).append(f"weather:after_response:{len(response)}")
        return {"type": "hook", "hook": "after_response"}
