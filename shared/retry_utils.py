"""Retry-Utilities mit Exponential Backoff (nur stdlib, keine extra Dependencies).

Usage:
    # Als Decorator
    @retry(max_attempts=3, base_delay=2.0)
    def fetch_weather():
        ...

    # Als Funktion
    result = with_retry(some_func, arg1, arg2, max_attempts=3, default=None)
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Tuple, Type

# Eigener Logger ohne Import aus aktienbot – verwendet nur stdlib logging
logger = logging.getLogger("polymarket.retry")


def with_retry(
    func: Callable,
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    default: Any = None,
    label: str = "",
    **kwargs: Any,
) -> Any:
    """
    Ruft func(*args, **kwargs) mit exponential backoff auf.

    Args:
        func:           Aufzurufende Funktion
        max_attempts:   Maximale Versuche (default: 3)
        base_delay:     Startverzoegerung in Sekunden (default: 1.0)
        max_delay:      Maximale Verzoegerung (default: 60.0)
        backoff_factor: Multiplikator pro Versuch (default: 2.0)
        retry_on:       Exception-Typen die Retry ausloesen
        default:        Rueckgabewert wenn alle Versuche fehlschlagen
        label:          Name fuer Logging (default: func.__name__)

    Returns:
        Rueckgabewert von func oder default nach Erschoepfung aller Versuche
    """
    name = label or getattr(func, "__name__", "unknown")

    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except retry_on as e:
            if attempt == max_attempts:
                logger.warning(
                    f"[RETRY] {name}: alle {max_attempts} Versuche fehlgeschlagen ({e})"
                )
                return default
            delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
            logger.warning(
                f"[RETRY] {name}: Versuch {attempt}/{max_attempts} fehlgeschlagen "
                f"({type(e).__name__}: {e}) — warte {delay:.1f}s"
            )
            time.sleep(delay)
        except Exception:
            # Nicht-retry-bare Exception sofort durchlassen
            raise

    return default


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    default: Any = None,
) -> Callable:
    """
    Decorator fuer automatisches Retry mit exponential backoff.

    Beispiele:
        @retry(max_attempts=3, base_delay=2.0)
        def fetch_forecast(city): ...

        @retry(max_attempts=5, base_delay=1.0, retry_on=(ConnectionError, TimeoutError))
        def call_weather_api(url): ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return with_retry(
                func, *args,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                retry_on=retry_on,
                default=default,
                label=func.__name__,
                **kwargs,
            )
        return wrapper
    return decorator
