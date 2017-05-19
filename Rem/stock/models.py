# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

from users.models import User

# Create your models here.


class Stock(models.Model):
    stock_id = models.IntegerField()
    name = models.CharField(max_length=255)
    module = models.CharField(max_length=255)

    def __unicode__(self):
        return '%d' % self.stock_id


class AccessRecord(models.Model):
    user = models.ForeignKey(User)
    stock = models.ForeignKey(Stock)
    created_time = models.DateTimeField('加入时间', null=True, blank=True)