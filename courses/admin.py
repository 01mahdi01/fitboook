from django.contrib import admin

from courses.models import Course, CourseLink, CoursePdf, Enrollment, Video, VideoKeyIssuance


class VideoInline(admin.TabularInline):
    model = Video
    fields = ["title", "order", "status"]
    readonly_fields = ["status"]
    extra = 0


class CourseLinkInline(admin.TabularInline):
    model = CourseLink
    fields = ["title", "url", "order"]
    extra = 0


class CoursePdfInline(admin.TabularInline):
    # Read-only here: uploading goes through the API so the file actually lands in MinIO.
    model = CoursePdf
    fields = ["title", "order", "object_name", "file_size_bytes"]
    readonly_fields = ["object_name", "file_size_bytes"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["title", "price", "is_published", "created_at"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [VideoInline, CourseLinkInline, CoursePdfInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "starts_at", "expires_at", "created_at"]
    list_filter = ["course"]


@admin.register(VideoKeyIssuance)
class VideoKeyIssuanceAdmin(admin.ModelAdmin):
    list_display = ["user", "video", "ip_address", "device_id", "created_at"]
    list_filter = ["video__course"]
    readonly_fields = [f.name for f in VideoKeyIssuance._meta.fields]

    def has_add_permission(self, request):
        return False
