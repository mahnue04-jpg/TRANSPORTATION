"""Local-only configuration. Production and public hosts are rejected."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass


VALID_MODES = frozenset({"mock", "local_pi", "emulator"})
DEFAULT_TIMEOUT_MS = 1500
DEFAULT_RETRY_CEILING = 2
DEFAULT_HEARTBEAT_SEC = 5
DEFAULT_OFFLINE_AFTER = 3
MIN_ANGLE = 0
MAX_ANGLE = 350


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def environment_name() -> str:
    return _env("AMICOR_ENVIRONMENT").lower()


def is_production() -> bool:
    return environment_name() in {"production", "prod"}


def parse_host(value: str) -> str:
    host = (value or "").strip().split("%")[0]
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    if ":" in host and host.count(":") == 1 and not host.startswith(":"):
        host = host.split(":", 1)[0]
    return host.lower()


def is_private_host(host: str) -> bool:
    cleaned = parse_host(host)
    if cleaned in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private or addr.is_link_local)


@dataclass(frozen=True)
class AgentConfig:
    mode: str
    host: str
    timeout_ms: int
    retry_ceiling: int
    heartbeat_sec: int
    offline_after_misses: int
    min_angle: int
    max_angle: int
    debug_controls: bool
    require_token: bool


class ConfigError(ValueError):
    pass


def load_config() -> AgentConfig:
    if is_production():
        mode = "mock"
        debug = False
    else:
        mode = _env("AMICOR_LIFESAVER_HARDWARE_MODE", "mock").lower() or "mock"
        debug = _env("AMICOR_LIFESAVER_EMULATOR_DEBUG", "1") not in {"0", "false", "no"}
    if mode not in VALID_MODES:
        raise ConfigError("Unsupported hardware mode.")
    if is_production() and mode == "local_pi":
        raise ConfigError("Production policy forces mock hardware mode.")
    if is_production() and debug:
        raise ConfigError("Emulator debug controls cannot be enabled in production.")
    host = parse_host(_env("AMICOR_LIFESAVER_PI_HOST", "127.0.0.1") or "127.0.0.1")
    if not is_private_host(host):
        raise ConfigError("Public hosts are rejected for the local Home Hub agent.")
    try:
        timeout_ms = int(_env("LIFESAVER_DEVICE_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)) or DEFAULT_TIMEOUT_MS)
        retry_ceiling = int(_env("LIFESAVER_DEVICE_RETRY_CEILING", str(DEFAULT_RETRY_CEILING)) or DEFAULT_RETRY_CEILING)
        heartbeat_sec = int(_env("LIFESAVER_HEARTBEAT_SEC", str(DEFAULT_HEARTBEAT_SEC)) or DEFAULT_HEARTBEAT_SEC)
        offline_after = int(_env("LIFESAVER_OFFLINE_AFTER_MISSES", str(DEFAULT_OFFLINE_AFTER)) or DEFAULT_OFFLINE_AFTER)
        min_angle = int(_env("LIFESAVER_MOTOR_MIN_ANGLE", str(MIN_ANGLE)) or MIN_ANGLE)
        max_angle = int(_env("LIFESAVER_MOTOR_MAX_ANGLE", str(MAX_ANGLE)) or MAX_ANGLE)
    except ValueError as exc:
        raise ConfigError("Timeout, retry, heartbeat, or angle settings are invalid.") from exc
    if timeout_ms < 200 or timeout_ms > 5000:
        raise ConfigError("Timeout must stay between 200 and 5000 ms.")
    if retry_ceiling < 0 or retry_ceiling > 3:
        raise ConfigError("Unlimited retries are not allowed.")
    if heartbeat_sec < 1 or heartbeat_sec > 30:
        raise ConfigError("Heartbeat interval is invalid.")
    if offline_after < 1 or offline_after > 10:
        raise ConfigError("Offline miss threshold is invalid.")
    if min_angle < 0 or max_angle > 350 or min_angle >= max_angle:
        raise ConfigError("Motor angle range is invalid.")
    return AgentConfig(
        mode=mode,
        host=host,
        timeout_ms=timeout_ms,
        retry_ceiling=retry_ceiling,
        heartbeat_sec=heartbeat_sec,
        offline_after_misses=offline_after,
        min_angle=min_angle,
        max_angle=max_angle,
        debug_controls=debug and not is_production(),
        require_token=mode == "local_pi",
    )
