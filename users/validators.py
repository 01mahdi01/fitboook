from django.core.validators import RegexValidator

validate_phone = RegexValidator(
    regex=r"^\+?\d{8,15}$",
    message="Enter a valid phone number (8-15 digits, optional leading +).",
)
