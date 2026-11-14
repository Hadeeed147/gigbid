CREATE INDEX CONCURRENTLY idx_orders_created ON orders (created_at);

export default async function Page({ params }) {
  const data = await getListing(params.id);
}

# Tailwind CSS module

# Python module
