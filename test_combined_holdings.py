"""Test combined holdings + CNC positions."""
import asyncio
from src.services.portfolio_monitor import portfolio_monitor
from src.services.groww_service import groww_service


async def test_combined_holdings():
    """Test the new _get_all_holdings method."""
    try:
        print("Authenticating with Groww...")
        await groww_service.authenticate()
        print("[OK] Authentication successful\n")

        print("Fetching combined holdings (holdings + CNC positions)...")
        print("=" * 80)

        holdings = await portfolio_monitor._get_all_holdings()

        print(f"Total symbols found: {len(holdings)}\n")

        if holdings:
            for i, h in enumerate(holdings):
                print(f"{i+1}. {h.trading_symbol}")
                print(f"   ISIN: {h.isin}")
                print(f"   Quantity: {h.quantity}")
                print(f"   Avg Price: Rs.{h.average_price}")
                print()
        else:
            print("No holdings or CNC positions found")

        print("=" * 80)
        print(f"SUCCESS: Found {len(holdings)} symbol(s)")
        print("MicroMonitor will now track these symbols!")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_combined_holdings())
