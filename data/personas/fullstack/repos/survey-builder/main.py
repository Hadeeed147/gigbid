db.products.aggregate([{ $match: { active: true } }, { $group: { _id: '$category' } }])

# AWS module

from django.db import models
class Appointment(models.Model):
    starts_at = models.DateTimeField()
