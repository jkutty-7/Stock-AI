"""Check all position types."""
import asyncio
import json
from src.services.groww_service import groww_service


async def test_all_positions():
    """Check all positions and their product types."""
    try:
        print("Authenticating with Groww...")
        await groww_service.authenticate()
        print("[OK]\n")

        print("Fetching all CASH positions...")
        print("=" * 80)
        positions = await groww_service.get_positions(segment="CASH")

        print(f"Total positions: {len(positions)}\n")

        cnc_count = 0
        mis_count = 0
        other_count = 0

        for pos in positions:
            print(f"Symbol: {pos.trading_symbol}")
            print(f"  Product: {pos.product} {'<-- DELIVERY' if pos.product == 'CNC' else '<-- INTRADAY' if pos.product == 'MIS' else ''}")
            print(f"  Quantity: {pos.quantity}")
            print(f"  Net Price: Rs.{pos.net_price}")
            print(f"  Segment: {pos.segment}")
            print()

            if pos.product == "CNC":
                cnc_count += 1
            elif pos.product == "MIS":
                mis_count += 1
            else:
                other_count += 1

        print("=" * 80)
        print(f"Summary:")
        print(f"  CNC (Delivery): {cnc_count} - Currently TRACKED ✓")
        print(f"  MIS (Intraday): {mis_count} - Currently NOT tracked ✗")
        print(f"  Other: {other_count}")
        print()

        if mis_count > 0:
            print("⚠️  You have MIS (intraday) positions!")
            print("   These are NOT currently tracked by the app.")
            print("   Would you like to add intraday tracking?")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_all_positions())
