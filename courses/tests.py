import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from courses.models import Course, CourseLink, CoursePdf, Enrollment
from users.models import BaseUser


@mock.patch("courses.services.minio_apis")
class CourseMaterialsTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(title="C", slug="c", price=100, is_published=True)
        CourseLink.objects.create(course=self.course, title="Group", url="https://t.me/x")
        CoursePdf.objects.create(course=self.course, title="Notes", object_name="course_1/a.pdf", file_size_bytes=10)
        self.user = BaseUser.objects.create_user(phone="09121111111", password="x")
        self.admin = BaseUser.objects.create_superuser(phone="09120000000", password="x")
        self.api = APIClient()
        self.url = f"/api/courses/{self.course.id}/materials/"

    def test_materials_gated_by_enrollment(self, minio):
        minio.get_download_url.return_value = "https://signed"
        self.api.force_authenticate(self.user)
        self.assertEqual(self.api.get(self.url).status_code, 403)  # not bought

        enrollment = Enrollment.objects.create(user=self.user, course=self.course)
        resp = self.api.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["links"][0]["url"], "https://t.me/x")
        self.assertEqual(resp.data["pdfs"][0]["download_url"], "https://signed")
        self.assertNotIn("object_name", resp.data["pdfs"][0])

        enrollment.expires_at = timezone.now() - datetime.timedelta(days=1)
        enrollment.save()
        self.assertEqual(self.api.get(self.url).status_code, 403)  # expired

        self.api.force_authenticate(None)
        self.assertEqual(self.api.get(self.url).status_code, 401)

    def test_public_course_detail_does_not_leak_materials(self, minio):
        resp = self.api.get(f"/api/courses/{self.course.id}/")
        self.assertNotIn("links", resp.data)
        self.assertNotIn("pdfs", resp.data)

    def test_admin_pdf_upload_and_delete(self, minio):
        self.api.force_authenticate(self.admin)
        url = f"/api/courses/admin/{self.course.id}/pdfs/"
        bad = SimpleUploadedFile("x.pdf", b"not a pdf", content_type="application/pdf")
        self.assertEqual(self.api.post(url, {"title": "Bad", "file": bad}, format="multipart").status_code, 400)

        good = SimpleUploadedFile("x.pdf", b"%PDF-1.4 hello", content_type="application/pdf")
        resp = self.api.post(url, {"title": "Book", "file": good}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["object_name"].startswith(f"course_{self.course.id}/"))
        self.assertEqual(minio.upload_private_file.call_args.kwargs["content_type"], "application/pdf")

        resp = self.api.delete(f"/api/courses/admin/pdfs/{resp.data['id']}/")
        self.assertEqual(resp.status_code, 204)
        minio.delete_file.assert_called_once()

    def test_admin_links_crud_and_non_admin_blocked(self, minio):
        url = f"/api/courses/admin/{self.course.id}/links/"
        self.api.force_authenticate(self.user)
        self.assertEqual(self.api.post(url, {"title": "x", "url": "https://a.b"}).status_code, 403)

        self.api.force_authenticate(self.admin)
        resp = self.api.post(url, {"title": "Form", "url": "https://forms.example/1", "order": 2})
        self.assertEqual(resp.status_code, 201)
        link_url = f"/api/courses/admin/links/{resp.data['id']}/"
        self.assertEqual(self.api.patch(link_url, {"title": "Form 2"}).data["title"], "Form 2")
        self.assertEqual(self.api.delete(link_url).status_code, 204)
        self.assertEqual(self.api.post(url, {"title": "x", "url": "not-a-url"}).status_code, 400)
