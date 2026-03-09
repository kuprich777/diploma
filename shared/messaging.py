"""Shared async messaging library for inter-service communication via RabbitMQ.

Provides:
    - RabbitMQConnection: lifecycle management with exponential-backoff reconnect
    - publish_event: standardised topic-exchange publisher with envelope schema
    - publish_event_safe: fire-and-forget wrapper (swallows exceptions)
    - subscribe: durable consumer with auto-ack / nack-to-DLX error handling

Routing key conventions:
    energy.state_changed      energy_service  → all consumers
    water.state_changed       water_service   → all consumers
    transport.state_changed   transport_service → all consumers
    risk.updated              risk_engine     → all consumers

Envelope schema (every published message):
    {
      "scenario_id":    str,
      "run_id":         str,
      "version_A":      str,   # dependency-matrix version (from risk_engine)
      "version_w":      str,   # weights version (from risk_engine)
      "sector":         str,
      "timestamp_step": int,   # UTC Unix epoch seconds
      "payload":        dict   # domain-specific data
    }

Dead-letter topology:
    DLX exchange : infrastructure_events.dlx   (fanout, durable)
    DLQ queue    : infrastructure_events.dead_letters  (durable)
    All service queues are declared with x-dead-letter-exchange pointing to DLX.
    A handler that raises an exception triggers nack(requeue=False) → DLX routing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

try:
    import aio_pika
    from aio_pika import DeliveryMode, ExchangeType, Message

    _AIO_PIKA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AIO_PIKA_AVAILABLE = False

logger = logging.getLogger("messaging")

# Dead-letter exchange / queue names shared across all services
DLX_EXCHANGE = "infrastructure_events.dlx"
DLQ_NAME = "infrastructure_events.dead_letters"

# Retry delays for initial connection (seconds): 2 → 4 → 8
_RETRY_DELAYS = [2.0, 4.0, 8.0]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class RabbitMQConnection:
    """Manages a single AMQP connection with exponential-backoff startup.

    Uses aio-pika's ``connect_robust`` so that the connection (and its
    channels) automatically recover from transient broker restarts.

    Usage::

        mq = RabbitMQConnection("amqp://guest:guest@rabbitmq:5672/")
        await mq.connect()
        await publish_event(mq.channel, ...)
        await mq.close()
    """

    def __init__(self, url: str) -> None:
        if not _AIO_PIKA_AVAILABLE:
            raise RuntimeError(
                "aio-pika is not installed. "
                "Add 'aio-pika' to your service's requirements."
            )
        self._url = url
        self._connection: Any = None
        self._channel: Any = None

    async def connect(self) -> None:
        """Open a robust AMQP connection with exponential backoff.

        Attempts up to ``len(_RETRY_DELAYS)`` connections, waiting
        2 / 4 / 8 seconds between tries. Raises ``RuntimeError`` if
        all attempts are exhausted.
        """
        last_exc: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                self._connection = await aio_pika.connect_robust(self._url)
                self._channel = await self._connection.channel()
                await self._channel.set_qos(prefetch_count=10)
                logger.info("✅ RabbitMQ connected (attempt %d)", attempt)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "⚠️  RabbitMQ connection attempt %d/%d failed: %s. "
                    "Retrying in %.1f s …",
                    attempt,
                    len(_RETRY_DELAYS),
                    exc,
                    delay,
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"RabbitMQ unavailable after {len(_RETRY_DELAYS)} attempts"
        ) from last_exc

    async def close(self) -> None:
        """Gracefully close the AMQP connection."""
        try:
            if self._connection and not self._connection.is_closed:
                await self._connection.close()
                logger.info("🔌 RabbitMQ connection closed")
        except Exception as exc:
            logger.warning("Error closing RabbitMQ connection: %s", exc)

    @property
    def channel(self) -> Any:
        """Return the active channel; raises if not connected."""
        if self._channel is None:
            raise RuntimeError("RabbitMQ channel not available — call connect() first")
        return self._channel

    @property
    def is_connected(self) -> bool:
        """True if the underlying connection is open."""
        return (
            self._connection is not None
            and not self._connection.is_closed
            and self._channel is not None
        )


# ---------------------------------------------------------------------------
# DLX helpers
# ---------------------------------------------------------------------------


async def _ensure_dlx(channel: Any) -> None:
    """Declare the dead-letter exchange and queue (idempotent)."""
    dlx = await channel.declare_exchange(
        DLX_EXCHANGE, ExchangeType.FANOUT, durable=True
    )
    dlq = await channel.declare_queue(DLQ_NAME, durable=True)
    await dlq.bind(dlx)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


async def publish_event(
    channel: Any,
    exchange_name: str,
    routing_key: str,
    payload: dict[str, Any],
    *,
    scenario_id: str = "",
    run_id: str = "",
    sector: str = "",
    version_A: str = "v1.0",
    version_w: str = "v1.0",
    correlation_id: str | None = None,
) -> None:
    """Publish a domain event with a standard envelope to a topic exchange.

    The exchange is declared durable and is created if it does not yet exist
    (idempotent).

    Args:
        channel:       Active aio-pika channel.
        exchange_name: Name of the topic exchange.
        routing_key:   Routing key, e.g. ``"energy.state_changed"``.
        payload:       Domain-specific data dict (placed under ``"payload"``).
        scenario_id:   Experiment scenario identifier.
        run_id:        Experiment run identifier.
        sector:        Source sector name (``"energy"`` / ``"water"`` / …).
        version_A:     Dependency-matrix version tag.
        version_w:     Weights version tag.
        correlation_id: Optional idempotency / tracing ID.
    """
    exchange = await channel.declare_exchange(
        exchange_name, ExchangeType.TOPIC, durable=True
    )

    envelope: dict[str, Any] = {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "version_A": version_A,
        "version_w": version_w,
        "sector": sector,
        "timestamp_step": int(datetime.now(tz=timezone.utc).timestamp()),
        "payload": payload,
    }

    message = Message(
        body=json.dumps(envelope).encode(),
        content_type="application/json",
        correlation_id=correlation_id or str(uuid.uuid4()),
        delivery_mode=DeliveryMode.PERSISTENT,
    )

    await exchange.publish(message, routing_key=routing_key)
    logger.debug(
        "📤 Published routing_key=%s sector=%s scenario=%s run=%s",
        routing_key,
        sector,
        scenario_id,
        run_id,
    )


async def publish_event_safe(
    channel: Any,
    exchange_name: str,
    routing_key: str,
    payload: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Fire-and-forget wrapper around :func:`publish_event`.

    Catches and logs all exceptions so that a broker failure never
    propagates to the calling HTTP endpoint.
    """
    try:
        await publish_event(channel, exchange_name, routing_key, payload, **kwargs)
    except Exception as exc:
        logger.warning("📤 Publish failed (non-critical) [%s]: %s", routing_key, exc)


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


async def subscribe(
    channel: Any,
    exchange_name: str,
    routing_key_pattern: str,
    queue_name: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Declare exchange / queue / binding and start consuming messages.

    Behaviour:
    - On success: auto-ack (handled by ``message.process()`` context manager).
    - On handler exception: nack with ``requeue=False`` → message routed to
      the dead-letter exchange (``infrastructure_events.dlx``).

    The dead-letter exchange and queue are declared/ensured before the
    consumer queue so the DLX always exists.

    Args:
        channel:              Active aio-pika channel.
        exchange_name:        Topic exchange name.
        routing_key_pattern:  Binding pattern, e.g. ``"energy.state_changed"``.
        queue_name:           Durable queue name for this consumer.
        handler:              Async coroutine called with the decoded envelope
                              dict on every incoming message.
    """
    await _ensure_dlx(channel)

    exchange = await channel.declare_exchange(
        exchange_name, ExchangeType.TOPIC, durable=True
    )

    queue = await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX_EXCHANGE},
    )
    await queue.bind(exchange, routing_key=routing_key_pattern)

    async def _on_message(message: Any) -> None:
        async with message.process(requeue=False):
            try:
                body = json.loads(message.body)
                logger.info(
                    "📨 [%s] routing_key=%s scenario_id=%s run_id=%s",
                    queue_name,
                    message.routing_key,
                    body.get("scenario_id", "?"),
                    body.get("run_id", "?"),
                )
                await handler(body)
            except Exception as exc:
                logger.error(
                    "❌ Handler error in [%s] routing_key=%s: %s — sending to DLX",
                    queue_name,
                    message.routing_key,
                    exc,
                )
                raise  # triggers nack → DLX routing

    await queue.consume(_on_message)
    logger.info(
        "🔔 Subscribed queue=%s exchange=%s pattern=%s",
        queue_name,
        exchange_name,
        routing_key_pattern,
    )
