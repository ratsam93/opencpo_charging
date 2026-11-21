#!/usr/bin/env python3
"""Standalone charger CLI: run a single virtual charger against a CSMS.

Example:
    python charger_cli.py --url ws://localhost:9100/ocpp --cp-id TEST-001
    python charger_cli.py --version 2.0.1 --url ws://localhost:9201/ocpp
"""
import argparse
import asyncio
import logging
import os
import signal

from profiles import get_profile

log = logging.getLogger("charger_cli")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run one virtual OCPP charger.")
    p.add_argument("--url", default=None,
                   help="CSMS base URL (cp id is appended). Default: OCPP16_URL / OCPP201_URL env, "
                        "else ws://127.0.0.1:9100/ocpp (1.6) or :9201 (2.0.1)")
    p.add_argument("--cp-id", default=os.environ.get("CP_ID", "CLI-0001"))
    p.add_argument("--version", choices=["1.6", "2.0.1"], default="1.6")
    p.add_argument("--profile", default=None, help="Charger profile name (see profiles.py)")
    p.add_argument("--charge", action="store_true", help="Start a charging session after boot")
    return p.parse_args(argv)


async def run(args) -> None:
    from environment import EnvironmentSimulator

    if args.version == "2.0.1":
        from charger201 import VirtualCharger201 as Charger
        url = args.url or os.environ.get("OCPP201_URL", "ws://127.0.0.1:9201/ocpp")
    else:
        from charger16 import VirtualCharger16 as Charger
        url = args.url or os.environ.get("OCPP16_URL", "ws://127.0.0.1:9100/ocpp")

    profile = get_profile(args.profile or {"1.6": "ENC-DCL120B-16", "2.0.1": "ENC-DCL120B"}[args.version])
    charger = Charger(cp_id=args.cp_id, profile=profile, ws_url=url, env_sim=EnvironmentSimulator())

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    log.info("Starting %s (OCPP %s) -> %s", args.cp_id, args.version, url)
    task = asyncio.create_task(charger.start())
    if args.charge:
        await asyncio.sleep(5)
        await charger.start_charging()
    await asyncio.wait([task, asyncio.create_task(shutdown.wait())],
                       return_when=asyncio.FIRST_COMPLETED)
    await charger.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    log.info("Charger %s stopped", args.cp_id)


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
