type Query { listing(id: ID!): Listing }

export default async function Page({ params }) {
  const data = await getListing(params.id);
}

import redis
cache = redis.Redis.from_url(REDIS_URL)

const session = await stripe.checkout.sessions.create({ mode: 'subscription' });

# React Native module
