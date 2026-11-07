from typing import Any

from sms.smsir_apiclient import call, get_client


def send_bulk(*, mobiles: list[str], message: str) -> Any:
    return call(lambda: get_client().send_bulk_sms(numbers=mobiles, message=message))


def send_verify(*, mobile: str, template_id: int, parameters: dict[str, str]) -> Any:
    return call(
        lambda: get_client().send_verify_code(
            number=mobile,
            template_id=template_id,
            parameters=[{"name": name, "value": value} for name, value in parameters.items()],
        )
    )
