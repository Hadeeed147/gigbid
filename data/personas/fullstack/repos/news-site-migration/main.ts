CREATE INDEX CONCURRENTLY idx_orders_created ON orders (created_at);

import redis
cache = redis.Redis.from_url(REDIS_URL)

import { useState } from 'react';
export function Cart() {
  const [items, setItems] = useState([]);
}

from django.db import models
class Appointment(models.Model):
    starts_at = models.DateTimeField()
