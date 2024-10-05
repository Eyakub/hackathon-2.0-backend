from django.contrib import admin
from .models import Author, Content, Tag, ContentTag
# Register your models here.


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('name', 'username', 'unique_id', 'url', 'title', 'followers')
    search_fields = ('name', 'username', 'unique_id', 'url', 'title')
    list_filter = ('followers',)
    ordering = ('-followers',)

@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'content_tags__tag__name', 'created_at', 'updated_at')
    search_fields = ('title', 'author__name', 'author__username')
    list_filter = ('created_at', 'updated_at')
    ordering = ('-created_at',)

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)
    ordering = ('name',)

@admin.register(ContentTag)
class ContentTagAdmin(admin.ModelAdmin):
    list_display = ('content', 'tag')