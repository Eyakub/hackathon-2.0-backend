from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from django_ratelimit.decorators import ratelimit

from django.db.models import F, Q, Sum, Count
from django.utils import timezone

from contents.models import Content, Author, Tag, ContentTag
from contents.serializers import ContentSerializer, ContentPostSerializer
from contents.tasks import ai_generated_comment

class CustomPageNumberPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'items_per_page'


class ContentAPIView(APIView):

    def get(self, request):
        """
        TODO: Client is complaining about the app performance, the app is loading very slowly, our QA identified that
         this api is slow af. Make the api performant. Need to add pagination. But cannot use rest framework view set.
         As frontend, app team already using this api, do not change the api schema.
         Need to send some additional data as well,
         --------------------------------
         1. Total Engagement = like_count + comment_count + share_count
         2. Engagement Rate = Total Engagement / Views
         Users are complaining these additional data is wrong.
         Need filter support for client side. Add filters for (author_id, author_username, timeframe )
         For timeframe, the content's timestamp must be withing 'x' days.
         Example: api_url?timeframe=7, will get contents that has timestamp now - '7' days
         --------------------------------
         So things to do:
         1. Make the api performant
         2. Fix the additional data point in the schema
            - Total Engagement = like_count + comment_count + share_count
            - Engagement Rate = Total Engagement / Views
            - Tags: List of tags connected with the content
         3. Filter Support for client side
            - author_id: Author's db id
            - author_username: Author's username
            - timeframe: Content that has timestamp: now - 'x' days
            - tag_id: Tag ID
            - title (insensitive match IE: SQL `ilike %text%`)
         4. Must not change the inner api schema
         5. Remove metadata and secret value from schema
         6. Add pagination
            - Should have page number pagination
            - Should have items per page support in query params
            Example: `api_url?items_per_page=10&page=2`
        """

        query_params = request.query_params.dict()
        queryset = Content.objects.select_related('author').prefetch_related('content_tags__tag').all()

        author_id = query_params.get('author_id', None)
        if author_id:
            queryset = queryset.filter(author_id=author_id)

        author_username = query_params.get('author_username')
        if author_username:
            queryset = queryset.filter(author__username=author_username)

        timeframe = query_params.get('timeframe', None)
        if timeframe:
            days = int(timeframe)
            queryset = queryset.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=days))

        tag_id = query_params.get('tag_id', None)
        if tag_id:
            queryset = queryset.filter(content_tags__tag_id=tag_id)

        title = query_params.get('title', None)
        if title:
            queryset = queryset.filter(title__icontains=title)

        queryset = queryset.order_by('-id')

        paginator = CustomPageNumberPagination()
        paginated_queryset = paginator.paginate_queryset(queryset, request)

        serialized = ContentSerializer(paginated_queryset, many=True)

        for serialized_data in serialized.data:
            # Calculating `Total Engagement`
            # Calculating `Engagement Rate`

            like_count = serialized_data.get("like_count", 0)
            comment_count = serialized_data.get("comment_count", 0)
            share_count = serialized_data.get("share_count", 0)
            view_count = serialized_data.get("view_count", 0)

            total_engagement = like_count + comment_count + share_count
            if view_count > 0:
                engagement_rate = total_engagement / view_count
            else:
                engagement_rate = 0
            serialized_data["content"]["engagement_rate"] = engagement_rate
            serialized_data["content"]["total_engagement"] = total_engagement
            tags = list(
                ContentTag.objects.filter(
                    content_id=serialized_data["content"]["id"]
                ).values_list("tag__name", flat=True)
            )
            serialized_data["content"]["tags"] = tags
        return Response(serialized.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        TODO: This api is very hard to read, and inefficient.
         The users complaining that the contents they are seeing is not being updated.
         Please find out, why the stats are not being updated.
         ------------------
         Things to change:
         1. This api is hard to read, not developer friendly
         2. Support list, make this api accept list of objects and save it
         3. Fix the users complain
        """

        data = request.data
        print("Request data: =====>", data)
        if not isinstance(data, list):
            data = [data]

        created_or_updated_contents = []

        for content_data in data:
            serializer = ContentPostSerializer(data=content_data)
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            author_data = validated_data['author']
            author, _ = Author.objects.update_or_create(
                unique_id=author_data['unique_external_id'],
                defaults={
                    'username': author_data['unique_name'],
                    'name': author_data['full_name'],
                    'url': author_data['url'],
                    'title': author_data['title'],
                    'big_metadata': author_data['big_metadata'],
                    'secret_value': author_data['secret_value'],
                }
            )
            print('Author Object: ======>', author)
            content, _ = Content.objects.update_or_create(
                unique_id=validated_data['unq_external_id'],
                defaults={
                    'author': author,
                    'title': validated_data.get('title'),
                    'big_metadata': validated_data.get('big_metadata'),
                    'secret_value': validated_data.get('secret_value'),
                    'thumbnail_url': validated_data.get('thumbnail_view_url'),
                    'like_count': validated_data['stats']['likes'],
                    'comment_count': validated_data['stats']['comments'],
                    'share_count': validated_data['stats']['shares'],
                    'view_count': validated_data['stats']['views'],
                }
            )
            print('Content Object: ======>', content)
            for tag_name in validated_data.get('hashtags', []):
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                content_tag = ContentTag.objects.get_or_create(tag=tag, content=content)
                print('Tag Object: ======>', tag)
                print('Content_tag Object: ======>', content_tag)

            created_or_updated_contents.append(content)

        serialized_contents = ContentSerializer(
            [{'content': c, 'author': c.author} for c in created_or_updated_contents],
            many=True
        )

        return Response(serialized_contents.data, status=status.HTTP_201_CREATED)


class ContentStatsAPIView(APIView):
    """
    TODO: This api is taking way too much time to resolve.
     Contents that will be fetched using `ContentAPIView`, we need stats for that
     So it must have the same filters as `ContentAPIView`
     Filter Support for client side
            - author_id: Author's db id
            - author_username: Author's username
            - timeframe: Content that has timestamp: now - 'x' days
            - tag_id: Tag ID
            - title (insensitive match IE: SQL `ilike %text%`)
     -------------------------
     Things To do:
     1. Make the api performant
     2. Fix the additional data point (IE: total engagement, total engagement rate)
     3. Filter Support for client side
         - author_id: Author's db id
         - author_id: Author's db id
         - author_username: Author's username
         - timeframe: Content that has timestamp: now - 'x' days
         - tag_id: Tag ID
         - title (insensitive match IE: SQL `ilike %text%`)
     --------------------------
     Bonus: What changes do we need if we want timezone support?
    """
    def get(self, request):
        query_params = request.query_params.dict()
        queryset = Content.objects.select_related('author').prefetch_related('content_tags__tag').all()

        author_id = query_params.get('author_id')
        if author_id:
            queryset = queryset.filter(author_id=author_id)

        author_username = query_params.get('author_username')
        if author_username:
            queryset = queryset.filter(author__username=author_username)

        timeframe = query_params.get('timeframe')
        if timeframe:
            days = int(timeframe)
            queryset = queryset.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=days))

        tag_id = query_params.get('tag_id')
        if tag_id:
            queryset = queryset.filter(content_tags__tag_id=tag_id)

        title = query_params.get('title')
        if title:
            queryset = queryset.filter(title__icontains=title)

        stats = queryset.aggregate(
            total_likes=Sum('like_count'),
            total_shares=Sum('share_count'),
            total_comments=Sum('comment_count'),
            total_views=Sum('view_count'),
            total_contents=Count('id'),
            total_followers=Sum('author__followers')
        )

        total_engagement = stats['total_likes'] + stats['total_shares'] + stats['total_comments']
        total_engagement_rate = total_engagement / stats['total_views'] if stats['total_views'] else 0

        data = {
            "total_likes": stats['total_likes'] or 0,
            "total_shares": stats['total_shares'] or 0,
            "total_views": stats['total_views'] or 0,
            "total_comments": stats['total_comments'] or 0,
            "total_engagement": total_engagement,
            "total_engagement_rate": total_engagement_rate,
            "total_contents": stats['total_contents'] or 0,
            "total_followers": stats['total_followers'] or 0,
        }

        return Response(data, status=status.HTTP_200_OK)


class GenerateAIComment(APIView):
    authentication_classes = [IsAuthenticated]

    @ratelimit(key='ip', rate='2/m')
    def get(self, request):
        ai_generated_comment.delay()
        return Response(status=status.HTTP_200_OK)
