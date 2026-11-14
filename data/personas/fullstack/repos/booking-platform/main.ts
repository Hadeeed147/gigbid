const session = await stripe.checkout.sessions.create({ mode: 'subscription' });

io.on('connection', (socket) => socket.join(roomId));

import redis
cache = redis.Redis.from_url(REDIS_URL)

export interface Booking { id: string; startsAt: Date; seats: number }
