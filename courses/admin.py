from django.contrib import admin

from courses.models import Course, Enrollment, Video, VideoKeyIssuance


class VideoInline(admin.TabularInline):
    model = Video
    fields = ["title", "order", "status"]
    readonly_fields = ["status"]
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["title", "price", "is_published", "created_at"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [VideoInline]


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
