# channels/urls.py
from django.urls import path
from channels.views import ( CreateChannelView, MyChannelView, DeleteChannelView, PublicChannelView, ChannelVideosView, ChannelListView)

urlpatterns = [
    path('channels/', ChannelListView.as_view()),                          # GET
    path('channels/create/', CreateChannelView.as_view()),                 # POST
    path('channels/me/', MyChannelView.as_view()),                         # GET, PATCH
    path('channels/me/delete/', DeleteChannelView.as_view()),              # DELETE
    path('channels/<slug:channel_slug>/', PublicChannelView.as_view()),    # GET
    path('channels/<slug:channel_slug>/videos/', ChannelVideosView.as_view()),  # GET
]