"""Comprehensive Groww API holdings test."""
import asyncio
import json
from src.services.groww_service import groww_service


async def test_groww_holdings_api():
    """Test all ways to fetch holdings from Groww API."""

    try:
        print("=" * 80)
        print("GROWW API HOLDINGS TEST")
        print("=" * 80)
        print()

        # Step 1: Authenticate
        print("Step 1: Authenticating with Groww...")
        await groww_service.authenticate()
        print("[OK] Authentication successful")
        print()

        # Step 2: Get raw holdings response
        print("Step 2: Calling get_holdings_for_user() directly...")
        print("-" * 80)
        try:
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(groww_service.client.get_holdings_for_user),
                timeout=15.0
            )
            print(f"Response type: {type(raw_response)}")
            print(f"Response content:")
            print(json.dumps(raw_response, indent=2, default=str))
            print()

            # Check if holdings key exists
            if isinstance(raw_response, dict):
                if 'holdings' in raw_response:
                    holdings_list = raw_response['holdings']
                    print(f"Holdings array length: {len(holdings_list)}")
                    if holdings_list:
                        print(f"First holding sample:")
                        print(json.dumps(holdings_list[0], indent=2, default=str))
                    else:
                        print("Holdings array is EMPTY []")
                else:
                    print("No 'holdings' key in response")
                    print(f"Available keys: {list(raw_response.keys())}")
            elif isinstance(raw_response, list):
                print(f"Response is a list with {len(raw_response)} items")
                if raw_response:
                    print(f"First item: {json.dumps(raw_response[0], indent=2, default=str)}")
            else:
                print(f"Unexpected response format: {raw_response}")

        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            import traceback
            traceback.print_exc()

        print()
        print("-" * 80)

        # Step 3: Try using the service method
        print("Step 3: Using groww_service.get_holdings() method...")
        print("-" * 80)
        holdings = await groww_service.get_holdings()
        print(f"Parsed holdings count: {len(holdings)}")
        if holdings:
            for i, h in enumerate(holdings):
                print(f"\nHolding {i+1}:")
                print(f"  Symbol: {h.trading_symbol}")
                print(f"  ISIN: {h.isin}")
                print(f"  Quantity: {h.quantity}")
                print(f"  Avg Price: {h.average_price}")
        else:
            print("No holdings returned by service method")

        print()
        print("=" * 80)

        # Step 4: Try getting positions to compare
        print("Step 4: Checking positions (for comparison)...")
        print("-" * 80)
        try:
            positions_response = await asyncio.wait_for(
                asyncio.to_thread(groww_service.client.get_positions_for_user),
                timeout=15.0
            )
            print(f"Positions response type: {type(positions_response)}")
            print(f"Positions content:")
            print(json.dumps(positions_response, indent=2, default=str))
        except Exception as e:
            print(f"[ERROR] Positions API call failed: {e}")

        print()
        print("=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_groww_holdings_api())
