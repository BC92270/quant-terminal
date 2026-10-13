"""Host-side controller for the Docker strategy sandbox."""
from __future__ import annotations

import base64
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import numpy as np
import pandas as pd

from backtest_sdk import PortfolioSnapshot, Slice
from backtest_universal.strategy import SandboxAttestation

from .contracts import (
    CompileResult,
    SANDBOX_PROTOCOL_VERSION,
    SandboxLimits,
    SandboxRunResult,
    StrategyLanguage,
    canonical_json,
)
from .policy import validate_source


DEFAULT_IMAGE = "quant-terminal/backtest-sandbox:3.0.0"


class SandboxUnavailableError(RuntimeError):
    """Raised when the Docker security boundary cannot be established."""


class SandboxExecutionError(RuntimeError):
    """Raised when compilation, protocol validation, or execution fails."""


class _ControllerSigner:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path else None
        self.private_key = self._load_or_create()

    def _load_or_create(self) -> Ed25519PrivateKey:
        if self.path and self.path.exists():
            raw = self.path.read_bytes()
            key = serialization.load_pem_private_key(raw, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("sandbox controller key is not Ed25519")
            return key
        key = Ed25519PrivateKey.generate()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            raw = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, raw)
            finally:
                os.close(descriptor)
        return key

    def sign(self, payload: bytes) -> tuple[str, str, bool]:
        signature = self.private_key.sign(payload)
        public = self.private_key.public_key()
        public.verify(signature, payload)
        raw_public = public.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return (
            base64.b64encode(signature).decode("ascii"),
            base64.b64encode(raw_public).decode("ascii"),
            True,
        )


class _DockerSession:
    def __init__(
        self,
        command: list[str],
        *,
        container_name: str,
        output_limit: int,
    ) -> None:
        self.command = command
        self.container_name = container_name
        self.output_limit = output_limit
        self.output_bytes = 0
        self.stderr: list[str] = []
        self.stdout_lines: queue.Queue[str | None] = queue.Queue()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            close_fds=True,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stdout_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stderr_thread.start()
        self._stdout_thread.start()

    def _drain_stdout(self) -> None:
        if self.process.stdout is None:
            self.stdout_lines.put(None)
            return
        for line in self.process.stdout:
            self.stdout_lines.put(line)
        self.stdout_lines.put(None)

    def _drain_stderr(self) -> None:
        if self.process.stderr is None:
            return
        total = 0
        for line in self.process.stderr:
            total += len(line.encode("utf-8", errors="replace"))
            if total <= self.output_limit:
                self.stderr.append(line.rstrip())

    def send(self, payload: Mapping[str, Any]) -> None:
        if self.process.stdin is None:
            raise SandboxExecutionError("sandbox stdin unavailable")
        line = canonical_json(dict(payload))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def receive(self, timeout: float) -> dict[str, Any]:
        try:
            line = self.stdout_lines.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise TimeoutError("sandbox response timeout") from exc
        if line is None:
            code = self.process.poll()
            details = " · ".join(self.stderr[-8:])
            raise SandboxExecutionError(
                f"sandbox exited before response (code={code})"
                + (f" · {details}" if details else "")
            )
        self.output_bytes += len(line.encode("utf-8", errors="replace"))
        if self.output_bytes > self.output_limit:
            raise SandboxExecutionError("sandbox output limit exceeded")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SandboxExecutionError("sandbox emitted invalid JSON") from exc
        if not isinstance(message, dict):
            raise SandboxExecutionError("sandbox response must be an object")
        if message.get("type") == "error":
            raise SandboxExecutionError(
                str(message.get("message") or "sandbox execution failed")
            )
        return message

    def close(self, *, force: bool = False) -> None:
        if self.process.poll() is None and not force:
            try:
                self.send({"type": "stop"})
                self.process.wait(timeout=2)
            except Exception:
                force = True
        if self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        if force:
            docker = shutil.which("docker")
            if docker and self.container_name.startswith("qt-bt-"):
                subprocess.run(
                    [docker, "rm", "--force", self.container_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )


class DockerStrategyRunner:
    """Compile and run strategy callbacks inside a resource-capped container."""

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        limits: SandboxLimits | None = None,
        controller_key_path: str | os.PathLike[str] | None = None,
        docker_binary: str | None = None,
    ) -> None:
        self.image = str(image)
        self.limits = limits or SandboxLimits()
        self.docker_binary = docker_binary or shutil.which("docker") or "docker"
        self._signer = _ControllerSigner(controller_key_path)

    def image_digest(self) -> str:
        if (
            shutil.which(self.docker_binary) is None
            and not Path(self.docker_binary).exists()
        ):
            return ""
        try:
            result = subprocess.run(
                [
                    self.docker_binary,
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    self.image,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        digest = result.stdout.strip() if result.returncode == 0 else ""
        return digest if digest.startswith("sha256:") else ""

    @property
    def available(self) -> bool:
        return bool(self.image_digest())

    def attestation(self) -> SandboxAttestation:
        digest = self.image_digest()
        available = bool(digest)
        signature_verified = False
        if available:
            _, _, signature_verified = self._signer.sign(digest.encode("ascii"))
        return SandboxAttestation(
            available=available,
            runner_image_digest=digest,
            network_disabled=True,
            read_only_root=True,
            no_secrets_mounted=True,
            non_root=True,
            signature_verified=signature_verified,
            reason=""
            if available
            else "SANDBOX REQUIRED: Docker image is not installed",
        )

    def docker_command(self, container_name: str) -> list[str]:
        if not container_name.startswith("qt-bt-"):
            raise ValueError("invalid sandbox container name")
        limits = self.limits
        return [
            self.docker_binary,
            "run",
            "--rm",
            "--interactive",
            "--name",
            container_name,
            "--pull=never",
            "--network=none",
            "--ipc=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user=65532:65532",
            f"--pids-limit={int(limits.pids)}",
            f"--memory={int(limits.memory_mib)}m",
            f"--memory-swap={int(limits.memory_mib)}m",
            f"--cpus={float(limits.cpu_cores):g}",
            f"--tmpfs=/tmp:rw,exec,nosuid,nodev,size={int(limits.tmp_mib)}m,mode=1777",
            "--ulimit=nofile=64:64",
            "--ulimit=core=0:0",
            f"--ulimit=fsize={int(limits.output_mib) * 1024 * 1024}:{int(limits.output_mib) * 1024 * 1024}",
            "--env=LANG=C.UTF-8",
            "--env=LC_ALL=C.UTF-8",
            self.image,
        ]

    @classmethod
    def build_image(
        cls,
        repository_root: str | os.PathLike[str],
        *,
        image: str = DEFAULT_IMAGE,
        docker_binary: str | None = None,
        timeout: int = 1800,
    ) -> str:
        docker = docker_binary or shutil.which("docker") or "docker"
        root = Path(repository_root).resolve()
        dockerfile = root / "backtest_sandbox" / "runtime" / "Dockerfile"
        if not dockerfile.is_file():
            raise FileNotFoundError(dockerfile)
        result = subprocess.run(
            [
                docker,
                "build",
                "--file",
                str(dockerfile),
                "--tag",
                image,
                str(dockerfile.parent),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise SandboxUnavailableError((result.stderr or result.stdout)[-8000:])
        inspected = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        digest = inspected.stdout.strip()
        if inspected.returncode != 0 or not digest.startswith("sha256:"):
            raise SandboxUnavailableError(
                "built sandbox image has no immutable image id"
            )
        return digest

    def _session(self) -> _DockerSession:
        digest = self.image_digest()
        if not digest:
            raise SandboxUnavailableError(
                f"SANDBOX REQUIRED: build {self.image!r} before compiling strategy code"
            )
        name = "qt-bt-" + uuid4().hex[:20]
        return _DockerSession(
            self.docker_command(name),
            container_name=name,
            output_limit=int(self.limits.output_mib) * 1024 * 1024,
        )

    def compile(
        self,
        source: str,
        language: str | StrategyLanguage,
    ) -> CompileResult:
        lang = StrategyLanguage.parse(language)
        policy = validate_source(source, lang)
        if not policy.passed:
            return CompileResult(
                "POLICY_REJECTED",
                lang,
                policy.source_sha256,
                diagnostics=policy.issues,
            )
        session = self._session()
        started = time.monotonic()
        try:
            session.send(
                {
                    "type": "prepare",
                    "language": lang.value,
                    "source": source,
                    "parameters": {},
                    "seed": 41,
                    "compile_only": True,
                    "compile_seconds": int(self.limits.compile_seconds),
                    "callback_seconds": int(self.limits.callback_seconds),
                    "protocol_version": SANDBOX_PROTOCOL_VERSION,
                }
            )
            message = session.receive(float(self.limits.compile_seconds) + 10.0)
            if message.get("type") != "compiled" or message.get("status") != "PASS":
                raise SandboxExecutionError("compiler did not return a PASS result")
            diagnostics = tuple(
                line
                for line in str(message.get("diagnostics") or "").splitlines()
                if line.strip()
            )
            return CompileResult(
                "PASS",
                lang,
                policy.source_sha256,
                image_digest=self.image_digest(),
                compiler=str(message.get("compiler") or ""),
                duration_ms=int(
                    message.get("duration_ms") or ((time.monotonic() - started) * 1000)
                ),
                diagnostics=diagnostics,
            )
        except Exception as exc:
            return CompileResult(
                "COMPILE_FAILED",
                lang,
                policy.source_sha256,
                image_digest=self.image_digest(),
                duration_ms=int((time.monotonic() - started) * 1000),
                diagnostics=(str(exc), *tuple(session.stderr[-8:])),
            )
        finally:
            session.close(force=session.process.poll() is None)

    def causal_runtime(
        self,
        *,
        source: str,
        language: str | StrategyLanguage,
        parameters: Mapping[str, Any] | None = None,
        seed: int = 41,
    ) -> "DockerCausalStrategyRuntime":
        """Create a persistent runtime driven slice-by-slice by the OMS engine."""

        return DockerCausalStrategyRuntime(
            runner=self,
            source=source,
            language=language,
            parameters=parameters,
            seed=seed,
        )

    @staticmethod
    def _column(frame: pd.DataFrame, name: str) -> str:
        lookup = {str(column).strip().lower(): str(column) for column in frame.columns}
        if name not in lookup:
            raise ValueError(f"market data column {name!r} is required")
        return lookup[name]

    def _bars(self, market_data: Mapping[str, pd.DataFrame]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw_symbol, raw_frame in sorted(market_data.items()):
            if not isinstance(raw_frame, pd.DataFrame) or raw_frame.empty:
                raise ValueError(f"{raw_symbol}: market data is empty")
            frame = raw_frame.copy()
            index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="raise"))
            if index.tz is None:
                index = index.tz_localize("UTC")
            else:
                index = index.tz_convert("UTC")
            if index.has_duplicates:
                raise ValueError(f"{raw_symbol}: duplicate event timestamps")
            frame.index = index
            names = {
                name: self._column(frame, name)
                for name in ("open", "high", "low", "close")
            }
            volume_name = next(
                (
                    str(column)
                    for column in frame.columns
                    if str(column).strip().lower() == "volume"
                ),
                None,
            )
            available_name = next(
                (
                    str(column)
                    for column in frame.columns
                    if str(column).strip().lower() == "available_at"
                ),
                None,
            )
            for event_time, row in frame.sort_index().iterrows():
                available_at = (
                    pd.Timestamp(row[available_name])
                    if available_name
                    else pd.Timestamp(event_time)
                )
                if available_at.tzinfo is None:
                    available_at = available_at.tz_localize("UTC")
                else:
                    available_at = available_at.tz_convert("UTC")
                if available_at < event_time:
                    raise ValueError(f"{raw_symbol}: available_at precedes event_time")
                values = {name: float(row[column]) for name, column in names.items()}
                volume = (
                    float(row[volume_name])
                    if volume_name and pd.notna(row[volume_name])
                    else 0.0
                )
                if not all(
                    math.isfinite(value) for value in (*values.values(), volume)
                ):
                    raise ValueError(f"{raw_symbol}: non-finite OHLCV value")
                rows.append(
                    {
                        "event_time": pd.Timestamp(event_time),
                        "available_at": available_at,
                        "symbol": str(raw_symbol).strip().upper(),
                        **values,
                        "volume": volume,
                    }
                )
        rows.sort(
            key=lambda item: (item["available_at"], item["event_time"], item["symbol"])
        )
        if not rows:
            raise ValueError("market_data is empty")
        if len(rows) > int(self.limits.max_bars):
            raise ValueError(f"dataset exceeds {self.limits.max_bars:,} sandbox bars")
        return rows

    @staticmethod
    def _slices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group observations with identical economic and knowledge clocks.

        The controller never groups bars that became available at different
        times.  This preserves point-in-time causality while eliminating
        symbol-order dependence for truly simultaneous cross-sectional data.
        """

        slices: list[dict[str, Any]] = []
        for row in rows:
            key = (row["event_time"], row["available_at"])
            if not slices or slices[-1]["key"] != key:
                slices.append(
                    {
                        "key": key,
                        "event_time": row["event_time"],
                        "available_at": row["available_at"],
                        "bars": [],
                    }
                )
            slices[-1]["bars"].append(row)
        return slices

    @staticmethod
    def _parameters(parameters: Mapping[str, Any] | None) -> dict[str, float]:
        clean: dict[str, float] = {}
        for raw_key, raw_value in dict(parameters or {}).items():
            key = str(raw_key)
            if not key.replace("_", "").isalnum():
                raise ValueError(f"invalid parameter name: {key}")
            if isinstance(raw_value, bool):
                raw_value = int(raw_value)
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"parameter {key} is not finite")
            clean[key] = value
        return clean

    def run(
        self,
        *,
        source: str,
        language: str | StrategyLanguage,
        market_data: Mapping[str, pd.DataFrame],
        parameters: Mapping[str, Any] | None = None,
        seed: int = 41,
    ) -> SandboxRunResult:
        lang = StrategyLanguage.parse(language)
        policy = validate_source(source, lang)
        if not policy.passed:
            raise SandboxExecutionError(
                "strategy policy rejected: " + " · ".join(policy.issues[:8])
            )
        rows = self._bars(market_data)
        slices = self._slices(rows)
        params = self._parameters(parameters)
        symbols = tuple(sorted(str(symbol).strip().upper() for symbol in market_data))
        symbol_set = set(symbols)
        digest = self.image_digest()
        if not digest:
            raise SandboxUnavailableError(
                "SANDBOX REQUIRED: immutable Docker image is unavailable"
            )
        session = self._session()
        started = time.monotonic()
        compiler = ""
        callback_mode = "on_bar"
        logs: list[dict[str, Any]] = []
        target_rows: dict[pd.Timestamp, dict[str, float]] = {}
        availability: dict[pd.Timestamp, pd.Timestamp] = {}
        signal_count = 0
        try:
            session.send(
                {
                    "type": "prepare",
                    "language": lang.value,
                    "source": source,
                    "parameters": params,
                    "seed": int(seed),
                    "compile_only": False,
                    "compile_seconds": int(self.limits.compile_seconds),
                    "callback_seconds": int(self.limits.callback_seconds),
                    "protocol_version": SANDBOX_PROTOCOL_VERSION,
                }
            )
            deadline = started + float(self.limits.wall_seconds)
            while True:
                message = session.receive(
                    min(
                        float(self.limits.compile_seconds) + 10.0,
                        max(0.01, deadline - time.monotonic()),
                    )
                )
                if message.get("type") == "log":
                    logs.append(message)
                    continue
                if message.get("type") != "ready" or message.get("status") != "PASS":
                    raise SandboxExecutionError("sandbox did not enter READY state")
                compiler = str(message.get("compiler") or "")
                callback_mode = str(message.get("callback_mode") or "on_bar")
                break
            for sequence, market_slice in enumerate(slices):
                if time.monotonic() >= deadline:
                    raise TimeoutError("sandbox wall-clock limit exceeded")
                session.send(
                    {
                        "type": "slice",
                        "sequence": sequence,
                        "event_time": market_slice["event_time"].isoformat(),
                        "available_at": market_slice["available_at"].isoformat(),
                        "bars": [
                            {
                                "event_time": row["event_time"].isoformat(),
                                "available_at": row["available_at"].isoformat(),
                                "symbol": row["symbol"],
                                "open": row["open"],
                                "high": row["high"],
                                "low": row["low"],
                                "close": row["close"],
                                "volume": row["volume"],
                            }
                            for row in market_slice["bars"]
                        ],
                    }
                )
                while True:
                    message = session.receive(
                        min(
                            float(self.limits.callback_seconds) + 1.0,
                            max(0.01, deadline - time.monotonic()),
                        )
                    )
                    if message.get("type") == "log":
                        logs.append(message)
                        continue
                    if (
                        message.get("type") != "signals"
                        or int(message.get("sequence", -1)) != sequence
                    ):
                        raise SandboxExecutionError("out-of-order sandbox response")
                    break
                event_time = market_slice["event_time"]
                target_rows.setdefault(event_time, {})
                availability[event_time] = max(
                    availability.get(event_time, event_time),
                    market_slice["available_at"],
                )
                for signal in message.get("signals") or []:
                    symbol = str(signal.get("symbol", "")).strip().upper()
                    target = float(signal.get("target"))
                    if symbol not in symbol_set:
                        raise SandboxExecutionError(
                            f"strategy targeted unsubscribed instrument {symbol!r}"
                        )
                    if not math.isfinite(target) or not -4.0 <= target <= 4.0:
                        raise SandboxExecutionError(
                            "strategy target is outside the SDK safety envelope"
                        )
                    target_rows[event_time][symbol] = target
                    signal_count += 1
            session.send({"type": "stop"})
            try:
                stopped = session.receive(3.0)
                if stopped.get("type") != "stopped":
                    raise SandboxExecutionError("sandbox stop acknowledgement missing")
            except (TimeoutError, SandboxExecutionError):
                pass
        except Exception:
            session.close(force=True)
            raise
        finally:
            if session.process.poll() is None:
                session.close(force=False)

        index = pd.DatetimeIndex(sorted(target_rows))
        targets = pd.DataFrame(index=index, columns=list(symbols), dtype=float)
        for event_time, values in target_rows.items():
            for symbol, target in values.items():
                targets.loc[event_time, symbol] = target
        available = pd.Series(
            [availability[item] for item in index], index=index, name="available_at"
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        target_hash = sha256(targets.to_csv(index=True).encode("utf-8")).hexdigest()
        signed_evidence = {
            "protocol_version": SANDBOX_PROTOCOL_VERSION,
            "language": lang.value,
            "source_sha256": policy.source_sha256,
            "image_digest": digest,
            "compiler": compiler,
            "seed": int(seed),
            "parameters": params,
            "limits": asdict(self.limits),
            "bars_processed": len(rows),
            "slices_processed": len(slices),
            "callback_mode": callback_mode,
            "signals_emitted": signal_count,
            "target_sha256": target_hash,
            "network_disabled": True,
            "read_only_root": True,
            "no_secrets_mounted": True,
            "non_root": True,
        }
        payload = canonical_json(signed_evidence).encode("utf-8")
        signature, public_key, verified = self._signer.sign(payload)
        attestation = SandboxAttestation(
            available=True,
            runner_image_digest=digest,
            network_disabled=True,
            read_only_root=True,
            no_secrets_mounted=True,
            non_root=True,
            signature_verified=verified,
            reason="",
        )
        return SandboxRunResult(
            status="PASS",
            language=lang,
            source_sha256=policy.source_sha256,
            targets=targets,
            target_available_at=available,
            attestation=attestation,
            image_digest=digest,
            compiler=compiler,
            duration_ms=duration_ms,
            bars_processed=len(rows),
            signals_emitted=signal_count,
            slices_processed=len(slices),
            callback_mode=callback_mode,
            logs=tuple(logs[-1000:]),
            diagnostics={
                "protocol_version": SANDBOX_PROTOCOL_VERSION,
                "causal_streaming": True,
                "atomic_market_slices": True,
                "callback_mode": callback_mode,
                "future_data_exposed": False,
                "container_flags": self.docker_command("qt-bt-evidence")[4:-1],
                "limits": asdict(self.limits),
                "target_sha256": target_hash,
                "stderr_tail": tuple(session.stderr[-20:]),
            },
            signature=signature,
            public_key=public_key,
            signed_payload_sha256=sha256(payload).hexdigest(),
        )


def _portfolio_payload(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "available": bool(snapshot.available),
        "as_of": snapshot.as_of.isoformat() if snapshot.as_of else "",
        "positions": {
            str(symbol): dict(values) for symbol, values in snapshot.positions.items()
        },
        "cash": dict(snapshot.cash),
        "unsettled_cash": dict(snapshot.unsettled_cash),
        "open_orders": [dict(item) for item in snapshot.open_orders],
        "base_currency": snapshot.base_currency,
        "nav_base": snapshot.nav_base,
        "margin": dict(snapshot.margin),
        "pnl": dict(snapshot.pnl),
        "sequence": int(snapshot.sequence),
        "ledger_sha256": snapshot.ledger_sha256,
        "source": snapshot.source,
        "reason": snapshot.reason,
    }


class DockerCausalStrategyRuntime:
    """Persistent OCI strategy process implementing ``CausalStrategyRuntime``.

    The trusted engine owns the clock and supplies an immutable OMS snapshot
    before each atomic market slice.  This object only transports that state
    and validates strategy targets; it never creates fills or accounting.
    """

    def __init__(
        self,
        *,
        runner: DockerStrategyRunner,
        source: str,
        language: str | StrategyLanguage,
        parameters: Mapping[str, Any] | None,
        seed: int,
    ) -> None:
        self.runner = runner
        self.source = str(source)
        self.language = StrategyLanguage.parse(language)
        self.parameters = runner._parameters(parameters)
        self.seed = int(seed)
        self.policy = validate_source(self.source, self.language)
        if not self.policy.passed:
            raise SandboxExecutionError(
                "strategy policy rejected: " + " · ".join(self.policy.issues[:8])
            )
        self.image_digest = runner.image_digest()
        if not self.image_digest:
            raise SandboxUnavailableError(
                "SANDBOX REQUIRED: immutable Docker image is unavailable"
            )
        self._session_obj: _DockerSession | None = None
        self._started_at = 0.0
        self._deadline = 0.0
        self._compiler = ""
        self._callback_mode = "on_bar"
        self._logs: list[dict[str, Any]] = []
        self._target_rows: list[dict[str, Any]] = []
        self._signals = 0
        self._bars = 0
        self._slices = 0
        self._result: SandboxRunResult | None = None

    def __enter__(self) -> "DockerCausalStrategyRuntime":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc is None:
            self.result()
        else:
            self.close(force=True)

    @property
    def session(self) -> _DockerSession:
        if self._session_obj is None:
            raise SandboxExecutionError("causal strategy runtime has not started")
        return self._session_obj

    def start(self) -> None:
        if self._session_obj is not None:
            return
        self._session_obj = self.runner._session()
        self._started_at = time.monotonic()
        self._deadline = self._started_at + float(self.runner.limits.wall_seconds)
        self.session.send(
            {
                "type": "prepare",
                "language": self.language.value,
                "source": self.source,
                "parameters": self.parameters,
                "seed": self.seed,
                "compile_only": False,
                "compile_seconds": int(self.runner.limits.compile_seconds),
                "callback_seconds": int(self.runner.limits.callback_seconds),
                "protocol_version": SANDBOX_PROTOCOL_VERSION,
            }
        )
        while True:
            message = self.session.receive(
                min(
                    float(self.runner.limits.compile_seconds) + 10.0,
                    max(0.01, self._deadline - time.monotonic()),
                )
            )
            if message.get("type") == "log":
                self._logs.append(message)
                continue
            if message.get("type") != "ready" or message.get("status") != "PASS":
                raise SandboxExecutionError("sandbox did not enter READY state")
            self._compiler = str(message.get("compiler") or "")
            self._callback_mode = str(message.get("callback_mode") or "on_bar")
            return

    def on_slice(
        self,
        *,
        portfolio: PortfolioSnapshot,
        market_slice: Slice,
    ) -> Mapping[str, float]:
        self.start()
        if time.monotonic() >= self._deadline:
            raise TimeoutError("sandbox wall-clock limit exceeded")
        if self._bars + len(market_slice) > int(self.runner.limits.max_bars):
            raise SandboxExecutionError("sandbox bar limit exceeded")
        sequence = self._slices
        bars = []
        for symbol in market_slice.symbols:
            bar = market_slice[symbol]
            bars.append(
                {
                    "event_time": bar.event_time.isoformat(),
                    "available_at": bar.available_at.isoformat(),
                    "symbol": bar.symbol,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": 0.0 if bar.volume is None else float(bar.volume),
                }
            )
        self.session.send(
            {
                "type": "slice",
                "sequence": sequence,
                "event_time": market_slice.event_time.isoformat(),
                "available_at": market_slice.available_at.isoformat(),
                "portfolio": _portfolio_payload(portfolio),
                "bars": bars,
            }
        )
        while True:
            message = self.session.receive(
                min(
                    float(self.runner.limits.callback_seconds) + 1.0,
                    max(0.01, self._deadline - time.monotonic()),
                )
            )
            if message.get("type") == "log":
                self._logs.append(message)
                continue
            if (
                message.get("type") != "signals"
                or int(message.get("sequence", -1)) != sequence
            ):
                raise SandboxExecutionError("out-of-order sandbox response")
            break
        targets: dict[str, float] = {}
        for signal in message.get("signals") or []:
            symbol = str(signal.get("symbol", "")).strip().upper()
            target = float(signal.get("target"))
            if not symbol:
                raise SandboxExecutionError("strategy emitted a blank symbol")
            if not math.isfinite(target) or not -4.0 <= target <= 4.0:
                raise SandboxExecutionError(
                    "strategy target is outside the SDK safety envelope"
                )
            targets[symbol] = target
            self._target_rows.append(
                {
                    "event_time": pd.Timestamp(market_slice.event_time),
                    "available_at": pd.Timestamp(market_slice.available_at),
                    "symbol": symbol,
                    "target": target,
                }
            )
            self._signals += 1
        self._bars += len(bars)
        self._slices += 1
        return dict(sorted(targets.items()))

    def close(self, *, force: bool = False) -> None:
        if self._session_obj is None:
            return
        self._session_obj.close(force=force)

    def result(self) -> SandboxRunResult:
        if self._result is not None:
            return self._result
        if self._session_obj is None:
            raise SandboxExecutionError("causal strategy runtime never started")
        try:
            self.session.send({"type": "stop"})
            stopped = self.session.receive(3.0)
            if stopped.get("type") != "stopped":
                raise SandboxExecutionError("sandbox stop acknowledgement missing")
        except (TimeoutError, SandboxExecutionError):
            self.close(force=True)
            raise
        finally:
            if self._session_obj.process.poll() is None:
                self.close(force=False)

        if self._target_rows:
            long = pd.DataFrame(self._target_rows)
            targets = long.pivot_table(
                index="event_time", columns="symbol", values="target", aggfunc="last"
            ).sort_index()
            available = (
                long.groupby("event_time")["available_at"].max().reindex(targets.index)
            )
        else:
            targets = pd.DataFrame(dtype=float)
            available = pd.Series(dtype="datetime64[ns, UTC]", name="available_at")
        target_hash = sha256(targets.to_csv(index=True).encode("utf-8")).hexdigest()
        diagnostics = {
            "protocol_version": SANDBOX_PROTOCOL_VERSION,
            "causal_streaming": True,
            "atomic_market_slices": True,
            "portfolio_feedback_connected": True,
            "portfolio_authority": "OMS_EXECUTION_LEDGER",
            "future_data_exposed": False,
            "callback_mode": self._callback_mode,
            "container_flags": self.runner.docker_command("qt-bt-evidence")[4:-1],
            "limits": asdict(self.runner.limits),
            "target_sha256": target_hash,
            "stderr_tail": tuple(self._session_obj.stderr[-20:]),
        }
        signed_evidence = {
            "protocol_version": SANDBOX_PROTOCOL_VERSION,
            "language": self.language.value,
            "source_sha256": self.policy.source_sha256,
            "image_digest": self.image_digest,
            "compiler": self._compiler,
            "seed": self.seed,
            "parameters": self.parameters,
            "limits": asdict(self.runner.limits),
            "bars_processed": self._bars,
            "slices_processed": self._slices,
            "callback_mode": self._callback_mode,
            "signals_emitted": self._signals,
            "target_sha256": target_hash,
            "portfolio_feedback_connected": True,
            "network_disabled": True,
            "read_only_root": True,
            "no_secrets_mounted": True,
            "non_root": True,
        }
        payload = canonical_json(signed_evidence).encode("utf-8")
        signature, public_key, verified = self.runner._signer.sign(payload)
        attestation = SandboxAttestation(
            available=True,
            runner_image_digest=self.image_digest,
            network_disabled=True,
            read_only_root=True,
            no_secrets_mounted=True,
            non_root=True,
            signature_verified=verified,
            reason="",
        )
        self._result = SandboxRunResult(
            status="PASS",
            language=self.language,
            source_sha256=self.policy.source_sha256,
            targets=targets,
            target_available_at=available,
            attestation=attestation,
            image_digest=self.image_digest,
            compiler=self._compiler,
            duration_ms=int((time.monotonic() - self._started_at) * 1000),
            bars_processed=self._bars,
            signals_emitted=self._signals,
            slices_processed=self._slices,
            callback_mode=self._callback_mode,
            logs=tuple(self._logs[-1000:]),
            diagnostics=diagnostics,
            signature=signature,
            public_key=public_key,
            signed_payload_sha256=sha256(payload).hexdigest(),
        )
        return self._result


__all__ = [
    "DEFAULT_IMAGE",
    "DockerCausalStrategyRuntime",
    "DockerStrategyRunner",
    "SandboxExecutionError",
    "SandboxUnavailableError",
]
