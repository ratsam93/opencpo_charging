"""
OCPP 1.6 Reservation tests.
Tests ReserveNow and CancelReservation (OCPP 1.6 §5.13 / §5.2).
"""
from datetime import datetime, timedelta, timezone

from tests.base import OCPPTest, TestResult, Severity, make_exchange


def _reservation_unsupported(connection) -> bool:
    supported = connection.known_config.get("SupportedFeatureProfiles", "")
    return bool(supported) and "Reservation" not in supported


class ReserveNowAndCancel(OCPPTest):
    name = "reserve_now_cancel"
    category = "reservation"
    description = "ReserveNow → valid status; if Accepted, CancelReservation → Accepted"
    ocpp_spec_ref = "OCPP 1.6 §5.13, §5.2"
    severity = Severity.INFO
    versions = ["1.6"]

    RESERVE_STATUSES = {"Accepted", "Faulted", "Occupied", "Rejected", "Unavailable"}
    CANCEL_STATUSES = {"Accepted", "Rejected"}
    RESERVATION_ID = 424242

    async def run(self, connection) -> TestResult:
        if _reservation_unsupported(connection):
            return self.skip("Reservation not in SupportedFeatureProfiles")

        connector_id = connection.active_connector_id or 1
        id_tag = self.config.get("valid_rfid_tag",
                                 self.config.get("rfid", {}).get("valid_tag", "")) or "TESTTAG"
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        exchanges = []

        payload = {"connectorId": connector_id, "expiryDate": expiry,
                   "idTag": id_tag, "reservationId": self.RESERVATION_ID}
        resp = await connection.send_call_and_wait("ReserveNow", payload, timeout=15.0)
        exchanges.append(make_exchange("SENT", "ReserveNow", "reserve_now", payload))

        if resp is None:
            return self.result(False, "ReserveNow timed out — no response",
                expected="status: one of " + str(sorted(self.RESERVE_STATUSES)),
                actual="No response",
                fix="Implement ReserveNow handler (Reservation feature profile)",
                exchanges=exchanges)
        exchanges.append(make_exchange("RECEIVED", "ReserveNow.conf", "reserve_now", resp))

        if resp.get("_is_error"):
            code = resp.get("error_code", "")
            if code in ("NotImplemented", "NotSupported"):
                return self.result(True,
                    f"ReserveNow returned {code} — feature not supported (acceptable)",
                    exchanges=exchanges)
            return self.result(False, f"ReserveNow returned error: {code}", exchanges=exchanges)

        status = resp.get("status", "")
        if status not in self.RESERVE_STATUSES:
            return self.result(False, f"Invalid ReserveNow status: '{status}'",
                expected=f"One of: {sorted(self.RESERVE_STATUSES)}",
                actual=f"'{status}'",
                fix=f"ReserveNow.conf status must be one of {sorted(self.RESERVE_STATUSES)}",
                exchanges=exchanges)

        if status != "Accepted":
            return self.result(True,
                f"ReserveNow(connector={connector_id}) → {status} (valid; CancelReservation not exercised)",
                exchanges=exchanges)

        cancel_payload = {"reservationId": self.RESERVATION_ID}
        cancel = await connection.send_call_and_wait("CancelReservation", cancel_payload, timeout=15.0)
        exchanges.append(make_exchange("SENT", "CancelReservation", "cancel_reservation", cancel_payload))
        if cancel is None:
            return self.result(False, "CancelReservation timed out — no response",
                fix="Implement CancelReservation handler", exchanges=exchanges)
        exchanges.append(make_exchange("RECEIVED", "CancelReservation.conf", "cancel_reservation", cancel))

        cstatus = cancel.get("status", "") if not cancel.get("_is_error") else ""
        if cstatus != "Accepted":
            return self.result(False,
                f"CancelReservation of an accepted reservation returned "
                f"{cstatus or cancel.get('error_code', 'error')!r}",
                expected="status: Accepted",
                actual=str(cancel),
                fix="CancelReservation must return Accepted for an existing reservationId",
                exchanges=exchanges)

        return self.result(True,
            f"ReserveNow → Accepted, CancelReservation → Accepted (reservationId={self.RESERVATION_ID})",
            exchanges=exchanges)


class CancelReservationUnknownId(OCPPTest):
    name = "cancel_reservation_unknown_id"
    category = "reservation"
    description = "CancelReservation with an unknown reservationId → Rejected"
    ocpp_spec_ref = "OCPP 1.6 §5.2"
    severity = Severity.INFO
    versions = ["1.6"]

    async def run(self, connection) -> TestResult:
        if _reservation_unsupported(connection):
            return self.skip("Reservation not in SupportedFeatureProfiles")

        exchanges = []
        payload = {"reservationId": 987654321}
        resp = await connection.send_call_and_wait("CancelReservation", payload, timeout=15.0)
        exchanges.append(make_exchange("SENT", "CancelReservation", "cancel_unknown", payload))
        if resp is None:
            return self.result(False, "CancelReservation timed out — no response",
                fix="Implement CancelReservation handler", exchanges=exchanges)
        exchanges.append(make_exchange("RECEIVED", "CancelReservation.conf", "cancel_unknown", resp))

        if resp.get("_is_error"):
            code = resp.get("error_code", "")
            if code in ("NotImplemented", "NotSupported"):
                return self.result(True,
                    f"CancelReservation returned {code} — feature not supported (acceptable)",
                    exchanges=exchanges)
            return self.result(False, f"CancelReservation returned error: {code}", exchanges=exchanges)

        status = resp.get("status", "")
        if status != "Rejected":
            return self.result(False,
                f"CancelReservation of unknown reservationId returned '{status}'",
                expected="status: Rejected", actual=f"'{status}'",
                fix="Return Rejected when reservationId does not match an existing reservation",
                exchanges=exchanges)
        return self.result(True, "CancelReservation(unknown id) → Rejected", exchanges=exchanges)


ALL_TESTS = [
    ReserveNowAndCancel,
    CancelReservationUnknownId,
]
