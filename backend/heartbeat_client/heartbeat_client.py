"""Core heartbeat client for reporting on-premises deployments to Ziwi service.

The client posts a heartbeat to ``POST /api/v1/heartbeat`` every
``interval_seconds``. The first report includes license metadata so the server
can register a new deployment; subsequent reports omit it. Transient failures
are retried with exponential backoff. Crucially, the client never raises an
uncaught exception: it degrades gracefully (the host application keeps running)
and the server independently decides offline status after too many missed
heartbeats.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from heartbeat_client.config import HeartbeatClientConfig

logger = logging.getLogger("heartbeat_client")

HEARTBEAT_ENDPOINT = "/api/v1/heartbeat"
JOB_ID = "heartbeat_send_once"


class _HeartbeatError(Exception):
    """Base class for internal heartbeat failure signalling."""


class _RetryableError(_HeartbeatError):
    """A transient/non-recoverable error worth retrying (network, 401, 5xx...)."""


class _NeedLicense(_HeartbeatError):
    """Server rejected a new deployment because license info is missing."""


class HeartbeatClient:
    """Asynchronous heartbeat reporter with retry and scheduled dispatch.

    The client is framework-agnostic: call :meth:`send_once` directly, or use
    :meth:`start`/:meth:`stop` to run a background scheduler, or mount it into a
    FastAPI app via :func:`heartbeat_client.fastapi_integration.create_heartbeat_lifespan`.
    """

    def __init__(
        self,
        server_url: str,
        api_key: str,
        deployment_id: str,
        tenant_id: str,
        product: str,
        version: str = "",
        interval_seconds: int = 3600,
        license_issued_at: Optional[datetime] = None,
        license_expires_at: Optional[datetime] = None,
        max_retries: int = 3,
        retry_backoff: int = 10,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the heartbeat client.

        Args:
            server_url: Base URL of the heartbeat service (no trailing slash).
            api_key: Shared secret sent in the ``X-Api-Key`` header.
            deployment_id: Unique deployment instance identifier.
            tenant_id: Owning tenant identifier.
            product: Product code, e.g. ``"mfg"`` or ``"school"``.
            version: Software version string (optional).
            interval_seconds: Heartbeat interval in seconds (default 3600 = 1h).
            license_issued_at: License issue time (required on first report).
            license_expires_at: License expiry time (required on first report).
            max_retries: Number of retry attempts after the first failure.
            retry_backoff: Base backoff seconds for exponential backoff.
            timeout: Per-request timeout in seconds.
        """
        self._server_url = server_url.rstrip("/")
        self._api_key = api_key
        self._deployment_id = deployment_id
        self._tenant_id = tenant_id
        self._product = product
        self._version = version
        self._license_issued_at = license_issued_at
        self._license_expires_at = license_expires_at
        self._interval_seconds = interval_seconds
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._timeout = timeout

        self._registered: bool = False
        self._scheduler: Optional[BackgroundScheduler] = None
        self._running: bool = False

    @classmethod
    def from_config(cls, config: HeartbeatClientConfig) -> "HeartbeatClient":
        """Build a client from a :class:`HeartbeatClientConfig`."""
        return cls(
            server_url=config.server_url,
            api_key=config.api_key,
            deployment_id=config.deployment_id,
            tenant_id=config.tenant_id,
            product=config.product,
            version=config.version,
            interval_seconds=config.interval_seconds,
            license_issued_at=config.license_issued_at,
            license_expires_at=config.license_expires_at,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff_seconds,
            timeout=config.request_timeout,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_once(self) -> Dict[str, Any]:
        """Send a single heartbeat, retrying on failure.

        The first attempt includes license metadata when the deployment is not
        yet registered. A ``400`` on an unregistered deployment triggers one
        extra attempt with license fields forced on. Other failures follow the
        ``max_retries`` + exponential-backoff policy.

        Returns:
            A dict describing the outcome. On success it contains ``status``
            (``"created"`` or ``"updated"``) and ``deployment_id``. On failure
            it contains ``status="error"`` and a ``detail`` key. This method
            never raises an uncaught exception.
        """
        include_license = not self._registered
        attempts = 0
        last_exc: Optional[Exception] = None

        while attempts <= self._max_retries:
            try:
                result = await self._post(include_license)
                self._registered = True
                return result

            except _NeedLicense as exc:
                # New deployment rejected for missing license: retry once with
                # license fields forced on (no backoff for this special case).
                logger.warning(
                    "Heartbeat for %s needs license info: %s",
                    self._deployment_id, exc,
                )
                if self._license_issued_at is None or self._license_expires_at is None:
                    return {
                        "status": "error",
                        "detail": (
                            "New deployment requires license_issued_at and "
                            "license_expires_at, but they are not configured."
                        ),
                    }
                include_license = True
                attempts += 1
                if attempts > self._max_retries:
                    return {"status": "error", "detail": str(exc)}
                continue

            except _RetryableError as exc:
                last_exc = exc
                attempts += 1
                if attempts > self._max_retries:
                    logger.warning(
                        "Heartbeat failed after %d attempt(s) for %s: %s",
                        attempts, self._deployment_id, exc,
                    )
                    return {"status": "error", "detail": str(exc)}
                wait = self._retry_backoff * (2 ** (attempts - 1))
                logger.warning(
                    "Heartbeat attempt %d failed for %s, retrying in %ds: %s",
                    attempts, self._deployment_id, wait, exc,
                )
                await asyncio.sleep(wait)
                continue

            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                logger.warning(
                    "Heartbeat unexpected error for %s: %s",
                    self._deployment_id, exc,
                )
                return {"status": "error", "detail": str(exc)}

        return {
            "status": "error",
            "detail": str(last_exc) if last_exc else "max retries exceeded",
        }

    async def start(self) -> None:
        """Start the background scheduler and send an immediate heartbeat.

        Idempotent: calling :meth:`start` while already running is a no-op.
        """
        if self._running:
            return
        self._running = True

        # Fire an immediate heartbeat on startup.
        await self.send_once()

        # Schedule recurring heartbeats.
        # NOTE: BackgroundScheduler runs jobs in worker threads, so it cannot
        # ``await`` a coroutine. We register the synchronous ``_tick`` wrapper,
        # which drives the async ``send_once`` via ``asyncio.run``. (Registering
        # ``self.send_once`` directly would only produce an un-awaited coroutine
        # object and the periodic heartbeat would never execute.)
        # A seconds-based trigger is used so the interval exactly matches
        # interval_seconds (a minutes-based trigger would silently floor
        # sub-minute intervals to 1 minute).
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(seconds=self._interval_seconds),
            id=JOB_ID,
            name="Send heartbeat",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Heartbeat client started for %s (every %d s)",
            self._deployment_id, self._interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the background scheduler and release resources.

        Idempotent: safe to call when not running.
        """
        if not self._running:
            return
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._running = False
        logger.info("Heartbeat client stopped for %s", self._deployment_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Synchronous scheduler entry-point that runs one async heartbeat.

        ``BackgroundScheduler`` executes jobs on worker threads and therefore
        cannot await coroutines. This wrapper bridges the gap by running
        :meth:`send_once` to completion on a fresh event loop. Any failure is
        already handled (and degraded) inside ``send_once``, so we only guard
        against unexpected scheduler-level errors here.
        """
        try:
            asyncio.run(self.send_once())
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning("Heartbeat tick failed for %s: %s", self._deployment_id, exc)

    def _build_payload(self, include_license: bool) -> Dict[str, Any]:
        """Construct the JSON payload for a heartbeat request."""
        payload: Dict[str, Any] = {
            "deployment_id": self._deployment_id,
            "tenant_id": self._tenant_id,
            "product": self._product,
            "version": self._version,
        }
        if include_license:
            if self._license_issued_at is not None:
                payload["license_issued_at"] = self._license_issued_at.isoformat()
            if self._license_expires_at is not None:
                payload["license_expires_at"] = self._license_expires_at.isoformat()
        return payload

    async def _post(self, include_license: bool) -> Dict[str, Any]:
        """Perform the HTTP POST and translate server responses.

        Raises:
            _NeedLicense: When the server returns 400 for an unregistered
                deployment (license info required).
            _RetryableError: For network errors, 401, 5xx, or other 4xx.
        """
        url = f"{self._server_url}{HEARTBEAT_ENDPOINT}"
        payload = self._build_payload(include_license)
        headers = {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise _RetryableError(f"network error: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 400:
            if not self._registered:
                raise _NeedLicense(
                    "new deployment requires license_issued_at and "
                    "license_expires_at"
                )
            raise _RetryableError(f"bad request (400): {resp.text}")

        if resp.status_code == 401:
            raise _RetryableError("unauthorized (401): invalid or missing API key")

        if resp.status_code >= 500:
            raise _RetryableError(f"server error ({resp.status_code})")

        raise _RetryableError(
            f"client error ({resp.status_code}): {resp.text}"
        )

    @property
    def is_running(self) -> bool:
        """Whether the background scheduler is currently active."""
        return self._running

    @property
    def has_registered(self) -> bool:
        """Whether the deployment has been confirmed registered by the server."""
        return self._registered

    @property
    def next_run(self) -> Optional[datetime]:
        """Datetime of the next scheduled heartbeat, or None if not running."""
        if self._scheduler is None:
            return None
        job = self._scheduler.get_job(JOB_ID)
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time
