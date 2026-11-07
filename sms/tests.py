from unittest import mock

import requests

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from config.errors import ApplicationError
from sms import services
from sms.smsir_apiclient import SmsDeliveryError, normalize_mobile
from users.models import BaseUser

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCMEM, SMSIR_API_KEY="")
class SmsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def test_normalize_mobile(self):
        for raw in ["+989121234567", "00989121234567", "989121234567", "9121234567", "09121234567"]:
            self.assertEqual(normalize_mobile(raw), "09121234567")

    @mock.patch("sms.services.smsir_services.deliver_otp")
    def test_otp_cooldown_attempts_and_consume(self, delay):
        self.assertTrue(services.request_otp(phone="0912", purpose="t"))
        self.assertFalse(services.request_otp(phone="0912", purpose="t"))  # cooldown
        code = delay.call_args.kwargs["code"]
        with self.assertRaises(ApplicationError):
            services.verify_otp(phone="0912", purpose="other", code=code)  # purposes are isolated
        services.verify_otp(phone="0912", purpose="t", code=code)
        with self.assertRaises(ApplicationError):
            services.verify_otp(phone="0912", purpose="t", code=code)  # single use

    @mock.patch("sms.services.smsir_services.deliver_otp")
    def test_otp_burned_after_max_attempts(self, delay):
        services.request_otp(phone="0912", purpose="t")
        code = delay.call_args.kwargs["code"]
        for _ in range(services.OTP_MAX_ATTEMPTS):
            with self.assertRaises(ApplicationError):
                services.verify_otp(phone="0912", purpose="t", code="x")
        with self.assertRaises(ApplicationError) as ctx:
            services.verify_otp(phone="0912", purpose="t", code=code)
        self.assertEqual(ctx.exception.status_code, 429)

    @mock.patch("sms.services.smsir_services.deliver_otp")
    def test_password_reset_flow(self, delay):
        BaseUser.objects.create_user(phone="09121234567", password="old-Pass-123")
        api = APIClient()
        self.assertEqual(api.post("/api/users/password-reset/request/", {"phone": "09121234567"}).status_code, 204)
        code = delay.call_args.kwargs["code"]
        resp = api.post("/api/users/password-reset/verify/", {"phone": "09121234567", "code": code})
        self.assertEqual(resp.status_code, 200)
        body = {"reset_token": resp.data["reset_token"], "new_password": "new-Pass-456", "confirm_password": "new-Pass-456"}
        self.assertEqual(api.post("/api/users/password-reset/confirm/", body).status_code, 204)
        self.assertEqual(api.post("/api/users/password-reset/confirm/", body).status_code, 400)  # token single use
        self.assertTrue(BaseUser.objects.get(phone="09121234567").check_password("new-Pass-456"))

    @mock.patch("sms.smsir_apis.send_bulk")
    def test_admin_send(self, send_bulk):
        admin = BaseUser.objects.create_superuser(phone="09120000000", password="x")
        u1 = BaseUser.objects.create_user(phone="+989121111111", password="x")
        BaseUser.objects.create_user(phone="09122222222", password="x", is_active=False)
        api = APIClient()
        api.force_authenticate(admin)
        url = "/api/sms/admin/send/"
        self.assertEqual(api.post(url, {"message": "hi"}, format="json").status_code, 400)
        with override_settings(SMSIR_API_KEY="k"):
            resp = api.post(url, {"message": "hi", "user_ids": [u1.id]}, format="json")
            self.assertEqual((resp.status_code, resp.data["recipients"]), (200, 1))
            send_bulk.assert_called_once_with(mobiles=["09121111111"], message="hi")
            resp = api.post(url, {"message": "hi", "send_to_all": True}, format="json")
            self.assertEqual(resp.data["recipients"], 2)  # inactive user skipped

    @mock.patch("sms.smsir_apiclient.time.sleep")
    @mock.patch("sms.smsir_apiclient.requests.post")
    def test_retries_transient_then_succeeds(self, post, _sleep):
        ok = mock.Mock(status_code=200, json=lambda: {"status": 1, "data": {"packId": "x"}})
        post.side_effect = [requests.ConnectionError(), mock.Mock(status_code=503, json=lambda: {}), ok]
        with override_settings(SMSIR_API_KEY="k"):
            self.assertEqual(services.send_sms(phones=["09121234567"], message="hi"), 1)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args.kwargs["timeout"], 10)

    @mock.patch("sms.smsir_apiclient.time.sleep")
    @mock.patch("sms.smsir_apiclient.requests.post")
    def test_rejection_not_retried_and_admin_sees_reason(self, post, _sleep):
        post.return_value = mock.Mock(status_code=400, json=lambda: {"status": 0, "message": "insufficient credit"})
        admin = BaseUser.objects.create_superuser(phone="09120000000", password="x")
        api = APIClient()
        api.force_authenticate(admin)
        with override_settings(SMSIR_API_KEY="k"):
            resp = api.post("/api/sms/admin/send/", {"message": "hi", "send_to_all": True}, format="json")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("insufficient credit", resp.data["detail"])
        self.assertEqual(post.call_count, 1)

    @mock.patch("sms.smsir_services.BULK_CHUNK_SIZE", 1)
    @mock.patch("sms.smsir_apis.send_bulk")
    def test_partial_failure_reports_progress(self, send_bulk):
        send_bulk.side_effect = [None, SmsDeliveryError("SMS not sent: boom.")]
        with override_settings(SMSIR_API_KEY="k"), self.assertRaises(SmsDeliveryError) as ctx:
            services.send_sms(phones=["09121111111", "09122222222"], message="hi")
        self.assertIn("Already delivered to 1 of 2", ctx.exception.message)

    @mock.patch("sms.services.smsir_services.deliver_otp", side_effect=SmsDeliveryError("down"))
    def test_failed_otp_releases_cooldown(self, _deliver):
        for _ in range(2):  # second call isn't blocked by cooldown
            with self.assertRaises(SmsDeliveryError):
                services.request_otp(phone="0912", purpose="t")

    @mock.patch("sms.smsir_apis.send_bulk")
    def test_otp_goes_as_normal_sms(self, send_bulk):
        with override_settings(SMSIR_API_KEY="k"):
            services.request_otp(phone="+989121234567", purpose="t")
        mobiles, message = send_bulk.call_args.kwargs["mobiles"], send_bulk.call_args.kwargs["message"]
        self.assertEqual(mobiles, ["09121234567"])
        self.assertRegex(message, r"\d{6}")
