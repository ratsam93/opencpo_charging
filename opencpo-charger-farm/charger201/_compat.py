"""
ocpp library compatibility shim for OCPP 2.0.1 enum names.

ocpp <= 1.0.0 names the 2.0.1 enums ``FooType`` (e.g. ``BootReasonType``,
``ConnectorStatusType``); ocpp >= 2.0 renamed them to ``FooEnumType``. The
charger code mixes both spellings, so no single release satisfies it
unmodified. This module makes both spellings resolvable on whichever
release is installed. Import it before any other ``ocpp.v201.enums`` import.
"""

import ocpp.v201.enums as _enums

# Names that changed in more than a simple Type <-> EnumType way.
_EXPLICIT = {
    "TriggerMessageType": "MessageTriggerEnumType",
    "MessageTriggerEnumType": "TriggerMessageType",
    "DataTransferStatusType": "DataTransferStatusEnumType",
    "ReservationUpdateStatusType": "ReserveNowStatusEnumType",
}


def _install_aliases() -> None:
    ns = vars(_enums)
    for name in list(ns):
        if name.endswith("EnumType"):
            ns.setdefault(name[: -len("EnumType")] + "Type", ns[name])
        elif name.endswith("Type") and not name.endswith("EnumType"):
            ns.setdefault(name[: -len("Type")] + "EnumType", ns[name])
    for missing, source in _EXPLICIT.items():
        if missing not in ns and source in ns:
            setattr(_enums, missing, ns[source])


_install_aliases()
