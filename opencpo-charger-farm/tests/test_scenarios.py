import asyncio

from scenarios import SCENARIOS, list_scenarios
from scenarios.base import INTENSITY_COUNTS


class _FakeFarm:
    def __init__(self):
        self.spawned = []

    async def spawn_charger(self, cp_id, profile_name=None, ocpp_version=None, quirks=None, **kw):
        self.spawned.append((cp_id, profile_name, ocpp_version))
        return object()


def test_registry_has_17_scenarios():
    assert len(SCENARIOS) == 17
    assert len(list_scenarios()) == 17


def test_all_scenarios_instantiate_at_all_intensities():
    for name, cls in SCENARIOS.items():
        for intensity in INTENSITY_COUNTS:
            assert cls(_FakeFarm(), intensity).name == name


def test_spawn_forwards_ocpp_version_and_profile():
    farm = _FakeFarm()
    sc = next(iter(SCENARIOS.values()))(farm, "low", ocpp_version="2.0.1")
    asyncio.run(sc._spawn_charger("X-1"))
    assert farm.spawned == [("X-1", "ENC-DCL120B", "2.0.1")]
    sc = next(iter(SCENARIOS.values()))(farm, "low")
    asyncio.run(sc._spawn_charger("X-2"))
    assert farm.spawned[-1] == ("X-2", "ENC-DCL120B-16", "1.6")


# ── found by live testing against a real core ─────────────────────────────

class _StopFarm(_FakeFarm):
    def __init__(self):
        super().__init__()
        self.stopped = []

    async def stop_charger(self, cp_id):
        self.stopped.append(cp_id)
        return True


def test_scenario_cleanup_stops_spawned_chargers_and_is_idempotent():
    farm = _StopFarm()
    sc = next(iter(SCENARIOS.values()))(farm, "low")

    async def go():
        await sc._spawn_charger("C-1")
        await sc._spawn_charger("C-2")
        await sc.cleanup()
        await sc.cleanup()

    asyncio.run(go())
    assert farm.stopped == ["C-1", "C-2"]


def test_scenario_keep_chargers_opt_out():
    farm = _StopFarm()
    sc = next(iter(SCENARIOS.values()))(farm, "low", keep_chargers=True)

    async def go():
        await sc._spawn_charger("C-1")
        await sc.cleanup()

    asyncio.run(go())
    assert farm.stopped == []


def test_spawn_same_id_with_other_version_replaces_charger():
    from farm import ChargerFarm as Farm
    from charger201 import VirtualCharger201

    async def go():
        f = Farm()
        f.settings["ocpp16_url"] = "ws://127.0.0.1:1/ocpp"
        f.settings["ocpp201_url"] = "ws://127.0.0.1:1/ocpp"
        try:
            a = await f.spawn_charger("DUP-1", "ENC-DCL120B-16", ocpp_version="1.6")
            same = await f.spawn_charger("DUP-1", "ENC-DCL120B-16", ocpp_version="1.6")
            assert same is a and not isinstance(a, VirtualCharger201)
            b = await f.spawn_charger("DUP-1", "ENC-DCL120B", ocpp_version="2.0.1")
            assert isinstance(b, VirtualCharger201) and f.chargers["DUP-1"] is b
        finally:
            await f.stop_all()

    asyncio.run(go())
