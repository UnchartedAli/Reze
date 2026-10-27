"""
Plugin Manager for Reze.
Loads, validates, enables, and disables extensions safely from reze/plugins directory.
"""

import os
import importlib
import importlib.util
from typing import Dict, Any, Optional
from reze.command_router import router, Command
from reze.logging_config import logger
from reze.exceptions import PluginError

class PluginManager:
    def __init__(self, plugins_dir: str = "reze/plugins"):
        self.plugins_dir = plugins_dir
        self.loaded_plugins: Dict[str, Any] = {}
        self.plugin_commands: Dict[str, list] = {}

    def discover_and_load_all(self):
        """Scan plugins directory and load all valid python plugins."""
        if not os.path.exists(self.plugins_dir):
            return

        for fname in os.listdir(self.plugins_dir):
            if fname.endswith(".py") and not fname.startswith("__"):
                plugin_name = fname[:-3]
                try:
                    self.load_plugin(plugin_name)
                except Exception as e:
                    logger.error("Failed to load plugin %s: %s", plugin_name, e)

    def load_plugin(self, name: str):
        """Load a single plugin safely."""
        file_path = os.path.join(self.plugins_dir, f"{name}.py")
        if not os.path.exists(file_path):
            raise PluginError(f"Plugin file not found: {file_path}")

        spec = importlib.util.spec_from_file_location(f"reze.plugins.{name}", file_path)
        if not spec or not spec.loader:
            raise PluginError(f"Could not load spec for plugin: {name}")

        module = importlib.util.module_from_spec(spec)
        
        # Track commands registered during execution of this plugin
        before_cmds = set(router.commands.keys())
        spec.loader.exec_module(module)
        after_cmds = set(router.commands.keys())
        
        registered_by_plugin = list(after_cmds - before_cmds)
        self.loaded_plugins[name] = module
        self.plugin_commands[name] = registered_by_plugin
        logger.info("Plugin '%s' loaded successfully with commands: %s", name, registered_by_plugin)

    def unload_plugin(self, name: str):
        """Unload plugin and remove its registered commands."""
        if name not in self.loaded_plugins:
            return
        
        # Unregister its commands
        cmds = self.plugin_commands.get(name, [])
        for c in cmds:
            router.unregister(c)
        
        del self.loaded_plugins[name]
        del self.plugin_commands[name]
        logger.info("Plugin '%s' unloaded and commands unregistered.", name)

plugin_manager = PluginManager()
