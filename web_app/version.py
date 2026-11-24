from web_app.runtime_config import RuntimeConfig


APP_VERSION = RuntimeConfig.load().version
