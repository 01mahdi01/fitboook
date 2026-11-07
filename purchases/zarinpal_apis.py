from purchases import zarinpal_apiclient


def create_payment_request(*, amount: int, description: str, callback_url: str) -> dict:
    return zarinpal_apiclient.request_payment(amount=amount, description=description, callback_url=callback_url)


def confirm_payment(*, amount: int, authority: str) -> dict:
    return zarinpal_apiclient.verify_payment(amount=amount, authority=authority)
