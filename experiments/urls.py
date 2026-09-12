from django.urls import path
from experiments.views import MyVariantsView

urlpatterns = [
    path('experiments/variants/', MyVariantsView.as_view()),
]
