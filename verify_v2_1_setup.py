#!/usr/bin/env python3
"""
Quick verification script for Stock AI v2.1 setup.

Run this after starting the application to verify:
- MongoDB collections created
- Indexes properly set up
- Configuration variables loaded
- Services importable

Usage:
    python verify_v2_1_setup.py
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_header(text):
    """Print section header."""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}{text.center(70)}{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")


def print_success(text):
    """Print success message."""
    print(f"{GREEN}✓{RESET} {text}")


def print_error(text):
    """Print error message."""
    print(f"{RED}✗{RESET} {text}")


def print_warning(text):
    """Print warning message."""
    print(f"{YELLOW}⚠{RESET} {text}")


async def verify_configuration():
    """Verify all v2.1 configuration variables are set."""
    print_header("Configuration Variables")

    try:
        from src.config import settings

        # Outcome Tracking
        checks = [
            ("outcome_auto_track_enabled", bool),
            ("outcome_auto_track_interval_hours", int),
            ("outcome_min_confidence_track", float),
        ]
        print("Outcome Tracking:")
        for var, expected_type in checks:
            if hasattr(settings, var):
                value = getattr(settings, var)
                if isinstance(value, expected_type):
                    print_success(f"  {var} = {value}")
                else:
                    print_error(f"  {var} has wrong type (expected {expected_type.__name__})")
            else:
                print_error(f"  {var} not found")

        # Stop-Loss Monitoring
        checks = [
            ("stop_loss_enabled", bool),
            ("stop_loss_grace_pct", float),
        ]
        print("\nStop-Loss Monitoring:")
        for var, expected_type in checks:
            if hasattr(settings, var):
                value = getattr(settings, var)
                if isinstance(value, expected_type):
                    print_success(f"  {var} = {value}")
                else:
                    print_error(f"  {var} has wrong type")
            else:
                print_error(f"  {var} not found")

        # Drawdown Breaker
        checks = [
            ("drawdown_breaker_enabled", bool),
            ("drawdown_breaker_threshold_pct", float),
            ("drawdown_breaker_auto_reset", bool),
        ]
        print("\nDrawdown Breaker:")
        for var, expected_type in checks:
            if hasattr(settings, var):
                value = getattr(settings, var)
                if isinstance(value, expected_type):
                    print_success(f"  {var} = {value}")
                else:
                    print_error(f"  {var} has wrong type")
            else:
                print_error(f"  {var} not found")

        # Regime Classification
        checks = [
            ("regime_classification_enabled", bool),
            ("regime_index_symbol", str),
        ]
        print("\nRegime Classification:")
        for var, expected_type in checks:
            if hasattr(settings, var):
                value = getattr(settings, var)
                if isinstance(value, expected_type):
                    print_success(f"  {var} = {value}")
                else:
                    print_error(f"  {var} has wrong type")
            else:
                print_error(f"  {var} not found")

        # Liquidity Filter
        checks = [
            ("screener_min_liquidity", int),
            ("screener_liquidity_lookback_days", int),
        ]
        print("\nLiquidity Filter:")
        for var, expected_type in checks:
            if hasattr(settings, var):
                value = getattr(settings, var)
                if isinstance(value, expected_type):
                    print_success(f"  {var} = {value}")
                else:
                    print_error(f"  {var} has wrong type")
            else:
                print_error(f"  {var} not found")

        return True

    except ImportError as e:
        print_error(f"Failed to import config: {e}")
        return False


async def verify_service_imports():
    """Verify all v2.1 services can be imported."""
    print_header("Service Imports")

    services = [
        ("src.services.outcome_tracker", "outcome_tracker"),
        ("src.services.drawdown_breaker", "drawdown_breaker"),
        ("src.services.regime_classifier", "regime_classifier"),
        ("src.models.outcome", "SignalOutcome"),
    ]

    all_success = True
    for module_path, obj_name in services:
        try:
            module = __import__(module_path, fromlist=[obj_name])
            obj = getattr(module, obj_name)
            print_success(f"{module_path}.{obj_name}")
        except ImportError as e:
            print_error(f"{module_path}.{obj_name} - Import failed: {e}")
            all_success = False
        except AttributeError as e:
            print_error(f"{module_path}.{obj_name} - Object not found: {e}")
            all_success = False

    return all_success


async def verify_database_collections():
    """Verify MongoDB collections exist."""
    print_header("MongoDB Collections")

    try:
        from src.services.database import db

        expected_collections = [
            "signal_outcomes",
            "portfolio_peaks",
            "circuit_breaker_state",
            "market_regime",
            "trade_signals",
            "portfolio_snapshots",
        ]

        existing_collections = await db.db.list_collection_names()

        for collection in expected_collections:
            if collection in existing_collections:
                print_success(f"{collection}")
            else:
                print_warning(f"{collection} - Not found (will be created on first use)")

        return True

    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return False


async def verify_indexes():
    """Verify key indexes exist."""
    print_header("MongoDB Indexes")

    try:
        from src.services.database import db

        # Check signal_outcomes indexes
        print("signal_outcomes:")
        try:
            indexes = await db.signal_outcomes.index_information()
            has_compound = any(
                "trading_symbol" in str(idx.get("key", {}))
                for idx in indexes.values()
            )
            has_status = any(
                "status" in str(idx.get("key", {}))
                for idx in indexes.values()
            )
            has_ttl = any(
                idx.get("expireAfterSeconds") == 31536000  # 365 days
                for idx in indexes.values()
            )

            if has_compound:
                print_success("  Compound index (trading_symbol, signal_timestamp)")
            else:
                print_warning("  Compound index missing")

            if has_status:
                print_success("  Status index")
            else:
                print_warning("  Status index missing")

            if has_ttl:
                print_success("  TTL index (365 days)")
            else:
                print_warning("  TTL index missing or incorrect")

        except Exception as e:
            print_warning(f"  Could not verify indexes: {e}")

        # Check trade_signals TTL
        print("\ntrade_signals:")
        try:
            indexes = await db.trade_signals.index_information()
            ttl_index = None
            for idx_info in indexes.values():
                if idx_info.get("expireAfterSeconds") is not None:
                    ttl_index = idx_info
                    break

            if ttl_index:
                ttl_days = ttl_index["expireAfterSeconds"] / 86400
                if ttl_days == 90:
                    print_success(f"  TTL index (90 days)")
                else:
                    print_warning(f"  TTL index ({ttl_days:.0f} days) - Expected 90 days")
            else:
                print_warning("  TTL index missing")

        except Exception as e:
            print_warning(f"  Could not verify indexes: {e}")

        return True

    except Exception as e:
        print_error(f"Index verification failed: {e}")
        return False


async def verify_scheduled_jobs():
    """Verify new scheduled jobs are registered."""
    print_header("Scheduled Jobs")

    try:
        from src.scheduler.setup import create_scheduler, register_jobs

        scheduler = create_scheduler()
        register_jobs(scheduler)

        expected_jobs = [
            "outcome_tracking",
            "reload_stop_losses",
            "regime_classification",
        ]

        for job_id in expected_jobs:
            job = scheduler.get_job(job_id)
            if job:
                print_success(f"{job.name} (ID: {job_id})")
                # Show next run time
                if job.next_run_time:
                    print(f"         Next run: {job.next_run_time}")
            else:
                print_error(f"{job_id} - Not registered")

        scheduler.shutdown(wait=False)
        return True

    except Exception as e:
        print_error(f"Scheduler verification failed: {e}")
        return False


async def verify_tool_definitions():
    """Verify new Claude tools are defined."""
    print_header("Claude AI Tools")

    try:
        from src.tools.definitions import TOOL_DEFINITIONS

        tool_names = [tool["name"] for tool in TOOL_DEFINITIONS]

        new_tools = ["get_signal_performance"]

        for tool_name in new_tools:
            if tool_name in tool_names:
                print_success(f"{tool_name}")
            else:
                print_error(f"{tool_name} - Not found in tool definitions")

        print(f"\nTotal tools: {len(tool_names)}")

        return True

    except Exception as e:
        print_error(f"Tool verification failed: {e}")
        return False


async def run_all_checks():
    """Run all verification checks."""
    print(f"\n{BLUE}╔════════════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BLUE}║{RESET}  Stock AI v2.1 - Setup Verification                               {BLUE}║{RESET}")
    print(f"{BLUE}╚════════════════════════════════════════════════════════════════════╝{RESET}")

    results = []

    # Run checks
    results.append(("Configuration", await verify_configuration()))
    results.append(("Service Imports", await verify_service_imports()))
    results.append(("Database Collections", await verify_database_collections()))
    results.append(("Indexes", await verify_indexes()))
    results.append(("Scheduled Jobs", await verify_scheduled_jobs()))
    results.append(("Claude Tools", await verify_tool_definitions()))

    # Summary
    print_header("Summary")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for check_name, result in results:
        if result:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")

    print(f"\n{BLUE}{'─' * 70}{RESET}")
    if passed == total:
        print(f"{GREEN}All checks passed! ({passed}/{total}){RESET}")
        print(f"\n{GREEN}✓ Stock AI v2.1 is properly configured{RESET}\n")
        return 0
    else:
        print(f"{YELLOW}Some checks failed or incomplete ({passed}/{total}){RESET}")
        print(f"\n{YELLOW}⚠ Review errors above and check your setup{RESET}\n")
        return 1


def main():
    """Main entry point."""
    try:
        exit_code = asyncio.run(run_all_checks())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Verification cancelled by user{RESET}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Fatal error: {e}{RESET}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
