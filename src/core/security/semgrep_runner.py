"""
Code-Agent — Semgrep Runner.
Executes Semgrep as a subprocess for deterministic OWASP security scanning.
Falls back gracefully if Semgrep is not installed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

import structlog

from src.models.domain import SemgrepFinding, SemgrepReport

logger = structlog.get_logger()

# OWASP mapping for common Semgrep rule categories
_OWASP_MAP: dict[str, str] = {
    "injection": "A03:Injection",
    "sql": "A03:Injection",
    "xss": "A03:Injection",
    "command-injection": "A03:Injection",
    "eval": "A03:Injection",
    "crypto": "A02:Cryptographic Failures",
    "hash": "A02:Cryptographic Failures",
    "ssl": "A02:Cryptographic Failures",
    "tls": "A02:Cryptographic Failures",
    "auth": "A07:Identification and Authentication Failures",
    "password": "A07:Identification and Authentication Failures",
    "session": "A07:Identification and Authentication Failures",
    "deserialization": "A08:Software and Data Integrity Failures",
    "ssrf": "A10:Server-Side Request Forgery",
    "path-traversal": "A01:Broken Access Control",
    "open-redirect": "A01:Broken Access Control",
    "hardcoded": "A07:Identification and Authentication Failures",
    "secret": "A07:Identification and Authentication Failures",
    "log-injection": "A09:Security Logging and Monitoring Failures",
}


class SemgrepRunner:
    """
    Runs Semgrep as a subprocess and parses the results.

    Usage::

        runner = SemgrepRunner()
        report = await runner.scan("/path/to/project")
    """

    def __init__(self, timeout_seconds: int = 120):
        self._timeout = timeout_seconds

    async def scan(self, project_path: str) -> SemgrepReport:
        """
        Run Semgrep on the given project path.

        Returns a SemgrepReport. If Semgrep is not installed or fails,
        returns an empty report with semgrep_available=False.
        """
        log = logger.bind(project_path=project_path)

        # Check if Semgrep is available
        if not shutil.which("semgrep"):
            log.warning("semgrep_not_available", hint="Install with: pip install semgrep")
            return SemgrepReport(semgrep_available=False)

        try:
            log.info("semgrep_scan_started", timeout=self._timeout)
            report = await asyncio.to_thread(self._run_semgrep, project_path)
            log.info(
                "semgrep_scan_completed",
                findings=report.total_findings,
                duration_ms=report.scan_duration_ms,
            )
            return report

        except subprocess.TimeoutExpired:
            log.warning("semgrep_scan_timeout", timeout=self._timeout)
            return SemgrepReport(semgrep_available=True)
        except Exception as e:
            log.error("semgrep_scan_failed", error=str(e))
            return SemgrepReport(semgrep_available=True)

    def _run_semgrep(self, project_path: str) -> SemgrepReport:
        """Execute Semgrep subprocess and parse output."""
        import time

        start = time.time()

        result = subprocess.run(
            [
                "semgrep",
                "--config", "auto",
                "--json",
                "--quiet",
                "--no-git-ignore",
                "--max-target-bytes", "1000000",
                project_path,
            ],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

        elapsed_ms = int((time.time() - start) * 1000)

        # Semgrep returns exit code 1 when findings exist (not an error)
        if result.returncode not in (0, 1):
            logger.warning(
                "semgrep_non_zero_exit",
                code=result.returncode,
                stderr=result.stderr[:500] if result.stderr else "",
            )

        # Parse JSON output
        try:
            raw = json.loads(result.stdout) if result.stdout else {}
        except json.JSONDecodeError:
            logger.warning("semgrep_invalid_json", stdout=result.stdout[:200])
            return SemgrepReport(scan_duration_ms=elapsed_ms)

        findings = self._parse_results(raw)

        return SemgrepReport(
            total_findings=len(findings),
            findings=findings,
            scan_duration_ms=elapsed_ms,
            semgrep_available=True,
        )

    def _parse_results(self, raw: dict) -> list[SemgrepFinding]:
        """Parse Semgrep JSON output into SemgrepFinding objects."""
        findings: list[SemgrepFinding] = []

        for result in raw.get("results", []):
            rule_id = result.get("check_id", "unknown")
            severity = result.get("extra", {}).get("severity", "WARNING").upper()
            message = result.get("extra", {}).get("message", "")
            file_path = result.get("path", "")
            line_start = result.get("start", {}).get("line", 0)
            line_end = result.get("end", {}).get("line", 0)

            # Extract code snippet
            lines = result.get("extra", {}).get("lines", "")
            code_snippet = lines if isinstance(lines, str) else str(lines)

            # Map to OWASP category
            owasp = self._map_owasp(rule_id)

            findings.append(SemgrepFinding(
                rule_id=rule_id,
                severity=severity,
                message=message[:500],
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                code_snippet=code_snippet[:300],
                owasp_category=owasp,
            ))

        return findings

    @staticmethod
    def _map_owasp(rule_id: str) -> str | None:
        """Map a Semgrep rule ID to an OWASP Top 10 category."""
        rule_lower = rule_id.lower()
        for keyword, owasp in _OWASP_MAP.items():
            if keyword in rule_lower:
                return owasp
        return None
