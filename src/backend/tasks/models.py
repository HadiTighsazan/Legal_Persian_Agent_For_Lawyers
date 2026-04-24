"""
Processing task models for the DocuChat system.
"""
import uuid

from django.db import models
from django.utils import timezone

from documents.models import Document


class ProcessingTask(models.Model):
    """
    Processing task model for tracking document processing jobs.
    """
    TASK_TYPE_CHOICES = [
        ('extract', 'Extract'),
        ('chunk', 'Chunk'),
        ('embed', 'Embed'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='processing_tasks')
    task_type = models.CharField(max_length=50, choices=TASK_TYPE_CHOICES)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0)  # 0-100
    result = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'processing_tasks'
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['celery_task_id']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.task_type} task for {self.document.title}"