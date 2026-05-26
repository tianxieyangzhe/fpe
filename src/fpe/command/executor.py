"""Remote command execution via SSH (paramiko) or local subprocess.

Execution context (namespace, VRF, host, etc.) is read from
:class:`fpe.settings.Settings` — see its docstring for the full list of
supported environment variables.
"""

from __future__ import annotations

import logging
import subprocess

import paramiko

from fpe.models import ExecContext
from fpe.settings import settings

logger = logging.getLogger(__name__)
# paramiko.transport 的 debug 日志过于冗长，默认关闭
logging.getLogger("paramiko.transport").setLevel(logging.WARNING)

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def _env_exec_ctx() -> ExecContext:
    """Build ExecContext from :obj:`settings` (backed by env vars)."""
    return ExecContext(
        namespace=settings.namespace,
        vrf=settings.vrf,
        host=settings.host,
        ip_version=settings.ip_version,
        ingress_if=settings.ingress_if,
    )


def list_network_namespaces(executor: RemoteExecutor) -> list[str]:
    """Return all named network namespaces via ``ip netns list``."""
    raw = executor.run_raw("ip netns list")
    namespaces: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        namespaces.append(line.split()[0])
    return namespaces


def list_network_vrfs(executor: RemoteExecutor, namespace: str | None = None) -> list[str]:
    """Return all VRF names in the given namespace (or root if *namespace* is empty/None)."""
    raw = executor.run_in_context("ip vrf list", namespace=namespace)
    vrfs: list[str] = []
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] and not parts[0].startswith("Name"):
            vrfs.append(parts[0])
    return vrfs


class RemoteExecutor:
    """Remote command execution via SSH, with local subprocess fallback."""

    def __init__(self) -> None:
        self._timeout = settings.ssh_connect_timeout
        self._ssh_user = settings.ssh_user
        self._ssh_port = settings.ssh_port
        self._ssh_key_path = settings.ssh_key_path

    def run(self, cmd: str) -> str:
        """Run *cmd* locally or remotely per ``FPE_HOST``."""
        return self.run_in_context(cmd)

    def run_in_context(self, cmd: str, namespace: str | None = None, vrf: str | None = None) -> str:
        """Run *cmd* in the requested namespace/VRF or the configured defaults."""
        host = settings.host
        ctx = _env_exec_ctx()
        target_namespace = ctx.namespace if namespace is None else namespace
        target_vrf = ctx.vrf if vrf is None else vrf
        # Namespace wraps outer, VRF wraps inner:
        #   ip netns exec {ns} ip vrf exec {vrf} {cmd}
        full_cmd = self._apply_vrf(cmd, target_vrf)
        full_cmd = self._apply_namespace(full_cmd, target_namespace)

        if not host or host in _LOCAL_HOSTS:
            return self._run_local(full_cmd)
        return self._run_ssh(host, full_cmd)

    def run_raw(self, cmd: str) -> str:
        """Run *cmd* without injecting namespace context."""
        host = settings.host
        if not host or host in _LOCAL_HOSTS:
            return self._run_local(cmd)
        return self._run_ssh(host, cmd)

    @staticmethod
    def _apply_namespace(cmd: str, namespace: str | None) -> str:
        if namespace:
            return f"ip netns exec {namespace} {cmd}"
        return cmd

    @staticmethod
    def _apply_vrf(cmd: str, vrf: str | None) -> str:
        if vrf:
            return f"ip vrf exec {vrf} {cmd}"
        return cmd

    def _run_local(self, cmd: str) -> str:
        logger.debug("Running local command: %s", cmd)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=self._timeout,
            )
            if result.returncode != 0:
                logger.warning("Command stderr (rc=%d): %s", result.returncode, result.stderr.strip())
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Command timed out: %s", cmd)
            return ""
        except OSError as e:
            logger.error("Command failed: %s — %s", cmd, e)
            return ""

    def _run_ssh(self, host: str, cmd: str) -> str:
        # bash -lc 模拟登录 shell，使远程 .bashrc 中的 PATH 生效。
        exec_cmd = f"bash -lc '{cmd}'"
        logger.debug("SSH | host=%s | cmd=%s", host, cmd)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs: dict = {
            "hostname": host,
            "username": self._ssh_user,
            "timeout": self._timeout,
        }
        if self._ssh_port != 22:
            connect_kwargs["port"] = self._ssh_port
        if self._ssh_key_path:
            connect_kwargs["key_filename"] = self._ssh_key_path

        try:
            logger.debug("SSH | %s | connecting ...", host)
            ssh.connect(**connect_kwargs)
            logger.debug("SSH | %s | connected, executing ...", host)
            _, stdout, stderr = ssh.exec_command(exec_cmd, timeout=self._timeout)
            output = stdout.read().decode()
            err_text = stderr.read().decode()
            exit_status = stdout.channel.recv_exit_status()
            logger.debug(
                "SSH | %s | rc=%d | stdout=%d bytes | stderr=%d bytes",
                host, exit_status, len(output), len(err_text),
            )
            if output:
                logger.debug("SSH | %s | stdout:\n%s", host, output)
            if exit_status != 0 and err_text.strip():
                logger.warning("SSH rc=%d for %s: %s", exit_status, host, err_text.strip())
            return output
        except Exception as e:
            logger.error("SSH command failed on %s: %s — %s", host, cmd, e)
            return ""
        finally:
            ssh.close()
            logger.debug("SSH | %s | connection closed", host)
