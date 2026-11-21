import asyncio

import pytest

from tests.mock_csms import MockCSMS


def test_charger201_imports():
    from charger201 import VirtualCharger201, EVSEState  # noqa: F401
    from ocpp.v201.enums import BootReasonType, ConnectorStatusEnumType  # noqa: F401


@pytest.mark.asyncio
async def test_201_boot_against_mock():
    from charger201 import VirtualCharger201
    from profiles import PROFILES

    csms = await MockCSMS(19140).start()
    profile = next(p for p in PROFILES.values() if p.ocpp_version.value == "2.0.1")
    ch = VirtualCharger201("TEST201", profile, "ws://127.0.0.1:19140/ocpp")
    task = asyncio.create_task(ch.start())
    try:
        for _ in range(50):
            if csms.counts["BootNotification"]:
                break
            await asyncio.sleep(0.1)
        assert csms.counts["BootNotification"] >= 1
        assert "ocpp2.0.1" in csms.subprotocols
    finally:
        await ch.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await csms.stop()
