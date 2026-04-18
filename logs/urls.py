from django.urls import path
from .views import OperationLogListView

app_name = 'logs'

urlpatterns = [
    path('', OperationLogListView.as_view(), name='operation_log'),
]
