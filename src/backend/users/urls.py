"""
URL configuration for users app.
"""
from django.urls import path

from users import views

app_name = 'users'

urlpatterns = [
    path('register/', views.register_view, name='register'),
]