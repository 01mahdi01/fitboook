from django.urls import path

from courses.apis import (
    AdminCourseLinkDetailApi,
    AdminCourseLinkListCreateApi,
    AdminCoursePdfDetailApi,
    AdminCoursePdfListUploadApi,
    CourseMaterialsApi,
    AdminCourseCoverUploadApi,
    AdminCourseDetailApi,
    AdminCourseEnrollmentApi,
    AdminCourseListCreateApi,
    AdminRenewEnrollmentApi,
    AdminUserEnrollmentsApi,
    AdminVideoDetailApi,
    AdminVideoListUploadApi,
    CourseDetailApi,
    CourseListApi,
    MyEnrollmentsApi,
    VideoKeyApi,
)

urlpatterns = [
    path("", CourseListApi.as_view(), name="course-list"),
    path("my-enrollments/", MyEnrollmentsApi.as_view(), name="my-enrollments"),
    path("videos/<int:video_id>/key/", VideoKeyApi.as_view(), name="video-key"),
    path("<int:course_id>/", CourseDetailApi.as_view(), name="course-detail"),
    path("<int:course_id>/materials/", CourseMaterialsApi.as_view(), name="course-materials"),
    path("admin/", AdminCourseListCreateApi.as_view(), name="admin-course-list-create"),
    path("admin/<int:course_id>/", AdminCourseDetailApi.as_view(), name="admin-course-detail"),
    path("admin/<int:course_id>/cover/", AdminCourseCoverUploadApi.as_view(), name="admin-course-cover-upload"),
    path("admin/<int:course_id>/videos/", AdminVideoListUploadApi.as_view(), name="admin-video-list-upload"),
    path("admin/videos/<int:video_id>/", AdminVideoDetailApi.as_view(), name="admin-video-detail"),
    path("admin/<int:course_id>/links/", AdminCourseLinkListCreateApi.as_view(), name="admin-course-link-list"),
    path("admin/links/<int:link_id>/", AdminCourseLinkDetailApi.as_view(), name="admin-course-link-detail"),
    path("admin/<int:course_id>/pdfs/", AdminCoursePdfListUploadApi.as_view(), name="admin-course-pdf-list"),
    path("admin/pdfs/<int:pdf_id>/", AdminCoursePdfDetailApi.as_view(), name="admin-course-pdf-detail"),
    path(
        "admin/<int:course_id>/enrollments/<int:user_id>/",
        AdminCourseEnrollmentApi.as_view(),
        name="admin-course-enrollment",
    ),
    path(
        "admin/<int:course_id>/enrollments/<int:user_id>/renew/",
        AdminRenewEnrollmentApi.as_view(),
        name="admin-course-enrollment-renew",
    ),
    path("admin/users/<int:user_id>/enrollments/", AdminUserEnrollmentsApi.as_view(), name="admin-user-enrollments"),
]
