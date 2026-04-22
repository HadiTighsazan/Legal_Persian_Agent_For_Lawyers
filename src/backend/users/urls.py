"""
URL configuration for users app.
"""
from django.urls import path

from users import views

app_name = 'users'

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('refresh/', views.refresh_view, name='refresh'),
    path('logout/', views.logout_view, name='logout'),
]
