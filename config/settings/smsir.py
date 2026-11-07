from config.env import env

# Empty API key = SMS is logged instead of sent (local dev). Set all of these in production.
SMSIR_API_KEY = env("SMSIR_API_KEY", default="")
SMSIR_LINE_NUMBER = env.int("SMSIR_LINE_NUMBER", default=0)
# Template created in the sms.ir panel (ارسال سریع / verify) — used for OTP codes.
SMSIR_OTP_TEMPLATE_ID = env.int("SMSIR_OTP_TEMPLATE_ID", default=0)
# Must match the variable name inside that template, e.g. "#CODE#" -> "CODE".
SMSIR_OTP_PARAMETER_NAME = env("SMSIR_OTP_PARAMETER_NAME", default="CODE")
