import argparse
import yaml
import sys
from pathlib import Path

# Import the attacks base dataclasses (for type hints, not strictly needed at runtime)
from .base import AttackConfig, Trigger

# Import the tool registry from the main project
from tools.registry import create_default_registry


def load_config(config_path: Path) -> AttackConfig:
    with config_path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    # Construct dataclasses
    trigger = Trigger(**data['trigger'])
    config = AttackConfig(
        name=data['name'],
        description=data.get('description', ''),
        trigger=trigger,
        payload=data['payload'],
        delay_messages=data.get('delay_messages'),
    )
    return config


def execute_payload(config: AttackConfig, provider: str):
    registry = create_default_registry()
    tool_name = config.payload.get('tool')
    args = config.payload.get('args', {})

    if provider == 'mock':
        print(f"[MOCK] Would execute tool '{tool_name}' with args {args}")
        # Simulate a tool output containing the payload if indirect
        if config.payload.get('malicious_field'):
            print(f"[MOCK] Injected malicious field: {config.payload['malicious_field']}")
    else:
        # Real provider – invoke the actual tool
        result = registry.execute(tool_name, args)
        print(f"[REAL] Tool '{tool_name}' returned: {result}")
        if config.payload.get('malicious_field'):
            print(f"[REAL] Malicious field injected: {config.payload['malicious_field']}")


def maybe_delay(config: AttackConfig):
    if config.delay_messages:
        for msg in config.delay_messages:
            print(f"[DELAY] {msg.get('role', 'assistant')}: {msg.get('content', '')}")


def main():
    parser = argparse.ArgumentParser(description='Run a memory‑poisoning attack')
    parser.add_argument('--type', required=True, choices=['direct', 'indirect', 'sleeper'], help='Attack type')
    parser.add_argument('--config-name', required=True, help='Base name of the YAML config (without .yaml)')
    parser.add_argument('--provider', required=True, choices=['mock', 'ollama'], help='Execution provider')
    args = parser.parse_args()

    config_path = Path(__file__).parent / args.type / f"{args.config_name}.yaml"
    if not config_path.is_file():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)
    print(f"Loaded attack config: {config.name}\nDescription: {config.description}\nTrigger: {config.trigger}\nPayload: {config.payload}\n")

    # Simple trigger check – for this demo we just evaluate keyword equality
    if config.trigger.type == 'keyword' and config.trigger.value.lower() in "dummy":
        print("[TRIGGER] Condition met – proceeding.")
    else:
        print("[TRIGGER] Condition not met – proceeding anyway for demo purposes.")

    maybe_delay(config)
    execute_payload(config, args.provider)

if __name__ == "__main__":
    main()
