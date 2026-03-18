# =============================================================================
# PARALLEL MARKET PROCESSING OPTIMIZATIONS
# =============================================================================
#
# Optimiert die Verarbeitung mehrerer Weather Markets durch:
# - Thread Pool für I/O-intensive Operations (API Calls)
# - Process Pool für CPU-intensive Calculations
# - Batch Processing für ähnliche Operations
# - Memory-efficient Data Structures
#
# =============================================================================

import logging
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Callable, Any, Tuple
from threading import Lock

logger = logging.getLogger(__name__)

# =============================================================================
# THREAD-SAFE RESULT ACCUMULATOR
# =============================================================================

@dataclass
class ProcessingResult:
    """Result of parallel market processing."""
    market_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    processing_time: float = 0.0

class ThreadSafeAccumulator:
    """Thread-safe accumulator for parallel processing results."""

    def __init__(self):
        self._results: List[ProcessingResult] = []
        self._lock = Lock()

    def add(self, result: ProcessingResult):
        """Add a result thread-safely."""
        with self._lock:
            self._results.append(result)

    def get_results(self) -> List[ProcessingResult]:
        """Get all accumulated results."""
        with self._lock:
            return self._results.copy()

    def get_successful(self) -> List[ProcessingResult]:
        """Get only successful results."""
        with self._lock:
            return [r for r in self._results if r.success]

    def get_failed(self) -> List[ProcessingResult]:
        """Get only failed results."""
        with self._lock:
            return [r for r in self._results if not r.success]

# =============================================================================
# PARALLEL PROCESSING STRATEGIES
# =============================================================================

def process_markets_parallel_io(
    markets: List[Any],
    processor_func: Callable[[Any], Any],
    max_workers: int = 8,
    timeout_per_market: float = 15.0
) -> List[ProcessingResult]:
    """
    Process markets in parallel using ThreadPoolExecutor for I/O operations.

    Optimal for:
    - API calls (weather forecasts)
    - Database queries
    - File I/O operations

    Args:
        markets: List of weather markets to process
        processor_func: Function to process each market
        max_workers: Maximum number of threads
        timeout_per_market: Timeout per market in seconds

    Returns:
        List of ProcessingResults
    """
    accumulator = ThreadSafeAccumulator()

    def process_single_market(market):
        """Process a single market with error handling and timing."""
        start_time = time.time()
        try:
            result = processor_func(market)
            processing_time = time.time() - start_time

            return ProcessingResult(
                market_id=getattr(market, 'market_id', str(market)),
                success=True,
                result=result,
                processing_time=processing_time
            )
        except Exception as e:
            processing_time = time.time() - start_time
            logger.warning(f"Market processing failed: {e}")

            return ProcessingResult(
                market_id=getattr(market, 'market_id', str(market)),
                success=False,
                error=str(e),
                processing_time=processing_time
            )

    # Process markets in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_market = {
            executor.submit(process_single_market, market): market
            for market in markets
        }

        # Collect results with timeout
        for future in as_completed(future_to_market, timeout=timeout_per_market * len(markets)):
            try:
                result = future.result(timeout=timeout_per_market)
                accumulator.add(result)
            except Exception as e:
                market = future_to_market[future]
                accumulator.add(ProcessingResult(
                    market_id=getattr(market, 'market_id', str(market)),
                    success=False,
                    error=f"Timeout or execution error: {e}",
                    processing_time=timeout_per_market
                ))

    return accumulator.get_results()

def process_markets_parallel_cpu(
    markets: List[Any],
    processor_func: Callable[[Any], Any],
    max_workers: int = 4
) -> List[ProcessingResult]:
    """
    Process markets in parallel using ProcessPoolExecutor for CPU operations.

    Optimal for:
    - Mathematical calculations (probability models)
    - Large ensemble computations
    - Data transformations

    Args:
        markets: List of markets to process
        processor_func: Function to process each market
        max_workers: Maximum number of processes (typically CPU cores)

    Returns:
        List of ProcessingResults
    """
    # Note: ProcessPoolExecutor requires functions to be pickle-able
    # This works best with pure functions without complex class dependencies

    results = []

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_market = {
                executor.submit(processor_func, market): market
                for market in markets
            }

            # Collect results
            for future in as_completed(future_to_market):
                market = future_to_market[future]
                start_time = time.time()
                try:
                    result = future.result()
                    processing_time = time.time() - start_time

                    results.append(ProcessingResult(
                        market_id=getattr(market, 'market_id', str(market)),
                        success=True,
                        result=result,
                        processing_time=processing_time
                    ))
                except Exception as e:
                    processing_time = time.time() - start_time
                    logger.warning(f"CPU processing failed for market: {e}")

                    results.append(ProcessingResult(
                        market_id=getattr(market, 'market_id', str(market)),
                        success=False,
                        error=str(e),
                        processing_time=processing_time
                    ))

    except Exception as e:
        logger.error(f"ProcessPoolExecutor failed: {e}")
        # Fallback to sequential processing
        return process_markets_sequential(markets, processor_func)

    return results

def process_markets_sequential(
    markets: List[Any],
    processor_func: Callable[[Any], Any]
) -> List[ProcessingResult]:
    """
    Sequential processing fallback for compatibility.

    Args:
        markets: List of markets to process
        processor_func: Function to process each market

    Returns:
        List of ProcessingResults
    """
    results = []

    for market in markets:
        start_time = time.time()
        try:
            result = processor_func(market)
            processing_time = time.time() - start_time

            results.append(ProcessingResult(
                market_id=getattr(market, 'market_id', str(market)),
                success=True,
                result=result,
                processing_time=processing_time
            ))
        except Exception as e:
            processing_time = time.time() - start_time
            logger.warning(f"Sequential processing failed: {e}")

            results.append(ProcessingResult(
                market_id=getattr(market, 'market_id', str(market)),
                success=False,
                error=str(e),
                processing_time=processing_time
            ))

    return results

# =============================================================================
# ADAPTIVE PROCESSING STRATEGY
# =============================================================================

def process_markets_adaptive(
    markets: List[Any],
    processor_func: Callable[[Any], Any],
    strategy: str = "auto"
) -> List[ProcessingResult]:
    """
    Adaptively choose the best processing strategy based on workload.

    Args:
        markets: List of markets to process
        processor_func: Function to process each market
        strategy: Processing strategy ("auto", "io", "cpu", "sequential")

    Returns:
        List of ProcessingResults
    """
    num_markets = len(markets)

    if strategy == "auto":
        if num_markets <= 2:
            # Small workload: sequential is fastest due to overhead
            strategy = "sequential"
        elif num_markets <= 10:
            # Medium workload: thread parallelism
            strategy = "io"
        else:
            # Large workload: consider CPU parallelism for computation
            strategy = "io"  # Most weather operations are I/O bound

    # Execute with chosen strategy
    start_time = time.time()

    if strategy == "io":
        results = process_markets_parallel_io(markets, processor_func)
    elif strategy == "cpu":
        results = process_markets_parallel_cpu(markets, processor_func)
    else:  # sequential
        results = process_markets_sequential(markets, processor_func)

    total_time = time.time() - start_time
    successful = len([r for r in results if r.success])

    logger.info(
        f"Parallel processing complete: {successful}/{num_markets} markets "
        f"in {total_time:.2f}s using {strategy} strategy"
    )

    return results

# =============================================================================
# MEMORY OPTIMIZATION UTILITIES
# =============================================================================

def chunk_markets(markets: List[Any], chunk_size: int = 50) -> List[List[Any]]:
    """
    Split markets into smaller chunks for memory-efficient processing.

    Args:
        markets: List of markets
        chunk_size: Maximum size per chunk

    Returns:
        List of market chunks
    """
    return [markets[i:i + chunk_size] for i in range(0, len(markets), chunk_size)]

def process_markets_chunked(
    markets: List[Any],
    processor_func: Callable[[Any], Any],
    chunk_size: int = 50
) -> List[ProcessingResult]:
    """
    Process markets in memory-efficient chunks.

    Args:
        markets: List of markets
        processor_func: Function to process each market
        chunk_size: Markets per chunk

    Returns:
        List of ProcessingResults
    """
    all_results = []
    chunks = chunk_markets(markets, chunk_size)

    logger.info(f"Processing {len(markets)} markets in {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        logger.debug(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} markets)")

        chunk_results = process_markets_adaptive(chunk, processor_func)
        all_results.extend(chunk_results)

        # Optional: Force garbage collection between chunks for large datasets
        if len(chunks) > 10:
            import gc
            gc.collect()

    return all_results