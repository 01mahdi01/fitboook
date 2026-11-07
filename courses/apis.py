from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from courses.models import Course, CourseLink, CoursePdf, Enrollment, Video
from courses.services import (
    create_course,
    create_course_link,
    delete_course_link,
    delete_course_pdf,
    get_course_materials,
    update_course_link,
    upload_course_pdf,
    create_video_upload,
    delete_course,
    delete_video,
    get_user_enrollments,
    get_video_download_key,
    grant_enrollment,
    renew_enrollment,
    revoke_enrollment,
    update_course,
    upload_course_cover,
)
from users.models import BaseUser


_COURSE_LIST_FIELDS = [
    "id",
    "title",
    "slug",
    "short_description",
    "description",
    "price",
    "instructor_name",
    "category",
    "level",
    "cover_image_url",
    "benefits",
    "access_duration_days",
]


@permission_classes([AllowAny])
class CourseListApi(APIView):
    class OutputCourseSerializer(serializers.ModelSerializer):
        class Meta:
            model = Course
            fields = _COURSE_LIST_FIELDS

    @extend_schema(responses=OutputCourseSerializer(many=True), summary="List published courses")
    def get(self, request):
        courses = Course.objects.filter(is_published=True)
        return Response(self.OutputCourseSerializer(courses, many=True).data)


class _CourseVideoOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Video
        fields = ["id", "title", "description", "order", "duration_seconds"]


@permission_classes([AllowAny])
class CourseDetailApi(APIView):
    class OutputCourseDetailSerializer(serializers.ModelSerializer):
        videos = _CourseVideoOutputSerializer(many=True, read_only=True)

        class Meta:
            model = Course
            fields = _COURSE_LIST_FIELDS + ["videos"]

    @extend_schema(
        responses=OutputCourseDetailSerializer,
        summary="Get a course's details and video list (published courses are public; "
        "unpublished/draft courses are visible to admins only)",
    )
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        if not course.is_published and not (request.user.is_authenticated and request.user.is_staff):
            raise Http404
        return Response(self.OutputCourseDetailSerializer(course).data)


class MyEnrollmentsApi(APIView):
    class OutputEnrolledCourseSerializer(serializers.ModelSerializer):
        starts_at = serializers.DateTimeField(source="enrollment.starts_at")
        expires_at = serializers.DateTimeField(source="enrollment.expires_at")

        class Meta:
            model = Course
            fields = ["id", "title", "slug", "description", "price", "starts_at", "expires_at"]

    @extend_schema(
        responses=OutputEnrolledCourseSerializer(many=True),
        summary="List courses the current user currently has active access to",
    )
    def get(self, request):
        enrollments = Enrollment.objects.filter(user=request.user).select_related("course")
        courses = []
        for enrollment in enrollments:
            if not enrollment.is_active:
                continue
            enrollment.course.enrollment = enrollment
            courses.append(enrollment.course)
        return Response(self.OutputEnrolledCourseSerializer(courses, many=True).data)


class VideoKeyApi(APIView):
    class OutputVideoKeySerializer(serializers.Serializer):
        download_url = serializers.CharField()
        decryption_key = serializers.CharField()
        nonce = serializers.CharField()
        expires_in = serializers.IntegerField()

    @extend_schema(
        responses=OutputVideoKeySerializer,
        summary="Issue a short-lived download URL + decryption key for a purchased video",
    )
    def get(self, request, video_id: int):
        result = get_video_download_key(
            user=request.user,
            video_id=video_id,
            ip_address=request.META.get("REMOTE_ADDR"),
            device_id=request.headers.get("X-Device-Id", ""),
        )
        return Response(self.OutputVideoKeySerializer(result).data)



class _CourseLinkOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseLink
        fields = ["id", "title", "url", "order"]


class _CoursePdfOutputSerializer(serializers.ModelSerializer):
    download_url = serializers.CharField()

    class Meta:
        model = CoursePdf
        fields = ["id", "title", "order", "file_size_bytes", "download_url"]


class CourseMaterialsApi(APIView):
    """Links and PDFs of a course — only for users with an active enrollment (or admins).
    PDF `download_url`s are presigned and expire after `expires_in` seconds; fetch this again for fresh ones."""

    class OutputCourseMaterialsSerializer(serializers.Serializer):
        links = _CourseLinkOutputSerializer(many=True)
        pdfs = _CoursePdfOutputSerializer(many=True)
        expires_in = serializers.IntegerField()

    @extend_schema(
        responses=OutputCourseMaterialsSerializer,
        summary="Get a purchased course's links and PDFs (403 if not enrolled or access expired)",
    )
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        result = get_course_materials(user=request.user, course=course)
        return Response(self.OutputCourseMaterialsSerializer(result).data)

class AdminCourseOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = _COURSE_LIST_FIELDS + ["is_published", "created_at"]


class AdminCourseListCreateApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCourseSerializer(serializers.Serializer):
        title = serializers.CharField()
        slug = serializers.SlugField()
        description = serializers.CharField(required=False, allow_blank=True, default="")
        short_description = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
        price = serializers.DecimalField(max_digits=12, decimal_places=0)
        is_published = serializers.BooleanField(default=False)
        instructor_name = serializers.CharField(required=False, allow_blank=True, default="")
        category = serializers.CharField(required=False, allow_blank=True, default="")
        level = serializers.ChoiceField(choices=Course.Level.choices, required=False, allow_blank=True, default="")
        benefits = serializers.CharField(required=False, allow_blank=True, default="")
        access_duration_days = serializers.IntegerField(required=False, allow_null=True, default=None)

    @extend_schema(responses=AdminCourseOutputSerializer(many=True), summary="List all courses (admin)")
    def get(self, request):
        courses = Course.objects.all().order_by("-created_at")
        return Response(AdminCourseOutputSerializer(courses, many=True).data)

    @extend_schema(
        request=InputCourseSerializer, responses=AdminCourseOutputSerializer, summary="Create a course (admin)"
    )
    def post(self, request):
        serializer = self.InputCourseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = create_course(**serializer.validated_data)
        return Response(AdminCourseOutputSerializer(course).data)


class AdminCourseDetailApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCourseUpdateSerializer(serializers.Serializer):
        title = serializers.CharField(required=False)
        slug = serializers.SlugField(required=False)
        description = serializers.CharField(required=False, allow_blank=True)
        short_description = serializers.CharField(required=False, allow_blank=True, max_length=500)
        price = serializers.DecimalField(max_digits=12, decimal_places=0, required=False)
        is_published = serializers.BooleanField(required=False)
        instructor_name = serializers.CharField(required=False, allow_blank=True)
        category = serializers.CharField(required=False, allow_blank=True)
        level = serializers.ChoiceField(choices=Course.Level.choices, required=False, allow_blank=True)
        benefits = serializers.CharField(required=False, allow_blank=True)
        access_duration_days = serializers.IntegerField(required=False, allow_null=True)

    @extend_schema(responses=AdminCourseOutputSerializer, summary="Get a course (admin)")
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        return Response(AdminCourseOutputSerializer(course).data)

    @extend_schema(
        request=InputCourseUpdateSerializer, responses=AdminCourseOutputSerializer, summary="Update a course (admin)"
    )
    def patch(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        serializer = self.InputCourseUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        course = update_course(course=course, **serializer.validated_data)
        return Response(AdminCourseOutputSerializer(course).data)

    @extend_schema(summary="Delete a course and its videos (admin)")
    def delete(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        delete_course(course=course)
        return Response(status=204)


class AdminCourseCoverUploadApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCoverUploadSerializer(serializers.Serializer):
        image = serializers.ImageField()

    @extend_schema(
        request=InputCoverUploadSerializer,
        responses=AdminCourseOutputSerializer,
        summary="Upload a course's cover image; stores it in MinIO and returns the course with its new cover_image_url",
    )
    def post(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        serializer = self.InputCoverUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = upload_course_cover(course=course, image_file=serializer.validated_data["image"])
        return Response(AdminCourseOutputSerializer(course).data)


class AdminVideoOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Video
        fields = ["id", "title", "description", "order", "duration_seconds", "file_size_bytes", "status", "created_at"]


class AdminVideoListUploadApi(APIView):
    permission_classes = [IsAdminUser]

    class InputVideoUploadSerializer(serializers.Serializer):
        title = serializers.CharField()
        description = serializers.CharField(required=False, allow_blank=True, default="")
        order = serializers.IntegerField(default=0)
        duration_seconds = serializers.IntegerField(required=False, allow_null=True, default=None)
        file = serializers.FileField()

    @extend_schema(responses=AdminVideoOutputSerializer(many=True), summary="List a course's videos (admin)")
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        return Response(AdminVideoOutputSerializer(course.videos.all(), many=True).data)

    @extend_schema(
        request=InputVideoUploadSerializer,
        responses=AdminVideoOutputSerializer,
        summary="Upload a raw video for a course; encryption happens asynchronously",
    )
    def post(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        serializer = self.InputVideoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        video = create_video_upload(
            course=course,
            title=serializer.validated_data["title"],
            description=serializer.validated_data["description"],
            order=serializer.validated_data["order"],
            source_file=serializer.validated_data["file"],
        )
        if serializer.validated_data["duration_seconds"] is not None:
            video.duration_seconds = serializer.validated_data["duration_seconds"]
            video.save(update_fields=["duration_seconds"])
        return Response(AdminVideoOutputSerializer(video).data)


class AdminVideoDetailApi(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(summary="Delete a video (admin)")
    def delete(self, request, video_id: int):
        video = get_object_or_404(Video, id=video_id)
        delete_video(video=video)
        return Response(status=204)


class AdminEnrollmentOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enrollment
        fields = ["id", "user", "course", "starts_at", "expires_at", "created_at"]


class AdminCourseEnrollmentApi(APIView):
    """Manually grant/revoke a specific user's access to a specific course, bypassing payment.

    The target user is identified by <user_id> in the URL (not the request body), so it's
    unambiguous in Swagger and works uniformly for POST/DELETE.
    Use for comps, support cases, and local testing without a live ZarinPal sandbox.
    Real purchases still go through purchases.zarinpal_services.confirm_course_purchase.
    """

    permission_classes = [IsAdminUser]

    class InputGrantEnrollmentSerializer(serializers.Serializer):
        expires_at = serializers.DateTimeField(
            required=False, allow_null=True, default=None, help_text="Blank = use the course's access_duration_days."
        )

    @extend_schema(
        request=InputGrantEnrollmentSerializer,
        responses=AdminEnrollmentOutputSerializer,
        summary="Grant a user access to a course without a payment (admin)",
    )
    def post(self, request, course_id: int, user_id: int):
        course = get_object_or_404(Course, id=course_id)
        user = get_object_or_404(BaseUser, id=user_id)
        serializer = self.InputGrantEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = grant_enrollment(user=user, course=course, expires_at=serializer.validated_data["expires_at"])
        return Response(AdminEnrollmentOutputSerializer(enrollment).data)

    @extend_schema(summary="Revoke a user's access to a course (admin)")
    def delete(self, request, course_id: int, user_id: int):
        course = get_object_or_404(Course, id=course_id)
        user = get_object_or_404(BaseUser, id=user_id)
        revoke_enrollment(user=user, course=course)
        return Response(status=204)


class AdminRenewEnrollmentApi(APIView):
    permission_classes = [IsAdminUser]

    class InputRenewEnrollmentSerializer(serializers.Serializer):
        expires_at = serializers.DateTimeField(
            required=False, allow_null=True, default=None, help_text="Blank = use the course's access_duration_days."
        )

    @extend_schema(
        request=InputRenewEnrollmentSerializer,
        responses=AdminEnrollmentOutputSerializer,
        summary="Renew/extend a user's existing access to a course (admin)",
    )
    def post(self, request, course_id: int, user_id: int):
        course = get_object_or_404(Course, id=course_id)
        user = get_object_or_404(BaseUser, id=user_id)
        serializer = self.InputRenewEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = renew_enrollment(user=user, course=course, expires_at=serializer.validated_data["expires_at"])
        return Response(AdminEnrollmentOutputSerializer(enrollment).data)


class AdminUserEnrollmentsApi(APIView):
    """List a specific user's active and past course access, for the admin user-detail page."""

    permission_classes = [IsAdminUser]

    class OutputUserEnrollmentsSerializer(serializers.Serializer):
        active = AdminEnrollmentOutputSerializer(many=True)
        expired = AdminEnrollmentOutputSerializer(many=True)

    @extend_schema(
        responses=OutputUserEnrollmentsSerializer,
        summary="List a user's active and expired course enrollments (admin)",
    )
    def get(self, request, user_id: int):
        user = get_object_or_404(BaseUser, id=user_id)
        result = get_user_enrollments(user=user)
        return Response(self.OutputUserEnrollmentsSerializer(result).data)


class AdminCourseLinkListCreateApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCourseLinkSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=255)
        url = serializers.URLField(max_length=1000)
        order = serializers.IntegerField(min_value=0, default=0)

    @extend_schema(responses=_CourseLinkOutputSerializer(many=True), summary="List a course's links (admin)")
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        return Response(_CourseLinkOutputSerializer(course.links.all(), many=True).data)

    @extend_schema(
        request=InputCourseLinkSerializer, responses=_CourseLinkOutputSerializer, summary="Add a link to a course (admin)"
    )
    def post(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        serializer = self.InputCourseLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = create_course_link(course=course, **serializer.validated_data)
        return Response(_CourseLinkOutputSerializer(link).data, status=201)


class AdminCourseLinkDetailApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCourseLinkUpdateSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=255, required=False)
        url = serializers.URLField(max_length=1000, required=False)
        order = serializers.IntegerField(min_value=0, required=False)

    @extend_schema(
        request=InputCourseLinkUpdateSerializer, responses=_CourseLinkOutputSerializer, summary="Update a course link (admin)"
    )
    def patch(self, request, link_id: int):
        link = get_object_or_404(CourseLink, id=link_id)
        serializer = self.InputCourseLinkUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        link = update_course_link(link=link, **serializer.validated_data)
        return Response(_CourseLinkOutputSerializer(link).data)

    @extend_schema(summary="Delete a course link (admin)")
    def delete(self, request, link_id: int):
        delete_course_link(link=get_object_or_404(CourseLink, id=link_id))
        return Response(status=204)


class AdminCoursePdfOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoursePdf
        fields = ["id", "title", "order", "object_name", "file_size_bytes", "created_at"]


class AdminCoursePdfListUploadApi(APIView):
    permission_classes = [IsAdminUser]

    class InputCoursePdfUploadSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=255)
        order = serializers.IntegerField(min_value=0, default=0)
        file = serializers.FileField()

    @extend_schema(responses=AdminCoursePdfOutputSerializer(many=True), summary="List a course's PDFs (admin)")
    def get(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        return Response(AdminCoursePdfOutputSerializer(course.pdfs.all(), many=True).data)

    @extend_schema(
        request={"multipart/form-data": InputCoursePdfUploadSerializer},
        responses=AdminCoursePdfOutputSerializer,
        summary="Upload a PDF for a course (admin); stored in the private MinIO bucket",
    )
    def post(self, request, course_id: int):
        course = get_object_or_404(Course, id=course_id)
        serializer = self.InputCoursePdfUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pdf = upload_course_pdf(course=course, **serializer.validated_data)
        return Response(AdminCoursePdfOutputSerializer(pdf).data, status=201)


class AdminCoursePdfDetailApi(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(summary="Delete a course PDF and its file in MinIO (admin)")
    def delete(self, request, pdf_id: int):
        delete_course_pdf(pdf=get_object_or_404(CoursePdf, id=pdf_id))
        return Response(status=204)
