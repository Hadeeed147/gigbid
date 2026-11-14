export default async function Page({ params }) {
  const data = await getListing(params.id);
}

const session = await stripe.checkout.sessions.create({ mode: 'subscription' });

from fastapi import FastAPI
app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}

import redis
cache = redis.Redis.from_url(REDIS_URL)
