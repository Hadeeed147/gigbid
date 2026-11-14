"""Controlled skill vocabulary for the synthetic corpus.

Each skill has explicit names (what a README or job post would say) and
implied phrasings (what a case study says without naming the tool). The gap
between the two is deliberate: it is what makes naive dense retrieval miss
evidence (see docs/DATA_CARD.md).
"""
from __future__ import annotations

SKILLS: dict[str, dict] = {
    # --- shared / infra ---
    "python": {"names": ["Python"], "implied": ["scripting the whole pipeline end to end", "a typed service layer with dataclasses"]},
    "docker": {"names": ["Docker", "docker-compose"], "implied": ["containerised every service so it ran the same on every laptop", "shipped reproducible images to the client's servers"]},
    "aws": {"names": ["AWS", "S3", "Lambda", "EC2"], "implied": ["moved the workload to Amazon's cloud with object storage for raw files", "serverless functions triggered on file upload"]},
    "celery": {"names": ["Celery"], "implied": ["a background task queue that retried failed jobs overnight", "offloaded slow report generation to async workers"]},
    "airflow": {"names": ["Airflow", "Apache Airflow"], "implied": ["scheduled DAGs that pulled data every night", "an orchestrator with retries and backfills for daily batches"]},
    "postgres": {"names": ["PostgreSQL", "Postgres"], "implied": ["a relational database with careful indexes and migrations", "row-level locking to stop double bookings"]},
    "redis": {"names": ["Redis"], "implied": ["an in-memory cache that cut page loads", "a fast key-value store for session data and rate limiting"]},
    "fastapi": {"names": ["FastAPI"], "implied": ["a typed async Python REST API with auto-generated docs", "OpenAPI-documented endpoints served by uvicorn"]},
    # --- AI / ML ---
    "pytorch": {"names": ["PyTorch"], "implied": ["trained the network with a custom training loop on a single GPU", "wrote the model in a define-by-run deep learning framework"]},
    "transformers": {"names": ["Hugging Face Transformers", "BERT"], "implied": ["fine-tuned a pretrained encoder on the client's labelled tickets", "used an off-the-shelf language model checkpoint as the backbone"]},
    "llm_apps": {"names": ["LLM", "OpenAI API", "GPT"], "implied": ["a chat assistant that answers from company documents", "prompted a large language model to draft replies"]},
    "langchain": {"names": ["LangChain"], "implied": ["chained retrieval and generation steps with a popular orchestration library"]},
    "langgraph": {"names": ["LangGraph"], "implied": ["a stateful agent graph with human approval steps", "multi-step agents with checkpoints and interrupts"]},
    "rag": {"names": ["RAG", "retrieval-augmented generation"], "implied": ["grounded the assistant's answers in retrieved passages with citations", "search over chunked documents before answering"]},
    "vector_db": {"names": ["Pinecone", "Qdrant", "FAISS", "pgvector"], "implied": ["a managed vector index for semantic search", "nearest-neighbour search over embeddings"]},
    "computer_vision": {"names": ["OpenCV", "YOLO", "computer vision"], "implied": ["detected defects on the production line from camera frames", "counted objects in drone footage"]},
    "nlp": {"names": ["NLP", "spaCy"], "implied": ["extracted entities from contracts", "classified support tickets by intent"]},
    "fine_tuning": {"names": ["LoRA", "fine-tuning", "QLoRA"], "implied": ["adapted a 7B model to the client's tone with low-rank adapters", "trained adapters instead of the full model to save GPU memory"]},
    "mlops": {"names": ["MLflow", "MLOps"], "implied": ["tracked every experiment and promoted models through a registry", "automated retraining when data drifted"]},
    "sklearn": {"names": ["scikit-learn", "XGBoost"], "implied": ["gradient-boosted trees on tabular features", "a calibrated churn classifier with cross-validation"]},
    "forecasting": {"names": ["time series forecasting", "Prophet"], "implied": ["predicted weekly demand per store", "seasonal models for next-quarter sales"]},
    # --- full-stack web ---
    "react": {"names": ["React"], "implied": ["a component-based single-page front end with hooks", "reusable UI components with client-side state"]},
    "nextjs": {"names": ["Next.js"], "implied": ["server-rendered pages with file-based routing for SEO", "hybrid static and server rendering on Vercel"]},
    "typescript": {"names": ["TypeScript"], "implied": ["strict typing across front end and back end", "shared type definitions between client and server"]},
    "nodejs": {"names": ["Node.js", "Express"], "implied": ["a JavaScript back end with middleware for auth", "an event-driven server handling webhooks"]},
    "django": {"names": ["Django"], "implied": ["a batteries-included Python web framework with its admin panel", "ORM models and class-based views"]},
    "mongodb": {"names": ["MongoDB"], "implied": ["a document store for flexible product catalogues", "schemaless collections with aggregation pipelines"]},
    "graphql": {"names": ["GraphQL", "Apollo"], "implied": ["a single typed query endpoint so the app fetched only what it needed"]},
    "stripe": {"names": ["Stripe"], "implied": ["subscription billing with webhooks for failed payments", "checkout and invoicing integrated with the payment processor"]},
    "tailwind": {"names": ["Tailwind CSS"], "implied": ["utility-first styling with a consistent design system"]},
    "websockets": {"names": ["WebSockets", "Socket.IO"], "implied": ["real-time updates pushed to every open browser", "live chat with presence indicators"]},
    "react_native": {"names": ["React Native", "Expo"], "implied": ["one codebase shipped to both iOS and Android", "a cross-platform mobile app"]},
    "shopify": {"names": ["Shopify", "Liquid"], "implied": ["customised an e-commerce storefront theme and checkout", "a headless store connected to the merchant's catalogue"]},
    "wordpress": {"names": ["WordPress", "WooCommerce"], "implied": ["a CMS-based site with custom plugins", "migrated a blog with ten thousand posts"]},
    # --- data analytics ---
    "sql": {"names": ["SQL"], "implied": ["window functions and CTEs over the order tables", "wrote the queries behind every KPI"]},
    "pandas": {"names": ["pandas", "Jupyter"], "implied": ["cleaned messy spreadsheets with dataframes in notebooks", "merged and reshaped exports programmatically"]},
    "powerbi": {"names": ["Power BI", "DAX"], "implied": ["interactive Microsoft dashboards with row-level security", "measures for year-over-year growth in the BI model"]},
    "tableau": {"names": ["Tableau"], "implied": ["drag-and-drop visual dashboards published for executives", "calculated fields and story points for the board deck"]},
    "excel": {"names": ["Excel", "VBA"], "implied": ["spreadsheet models with macros that refreshed in one click", "pivot tables and lookups for the finance team"]},
    "dbt": {"names": ["dbt"], "implied": ["version-controlled SQL transformation models with tests", "a modelled warehouse layer with documented lineage"]},
    "snowflake": {"names": ["Snowflake", "BigQuery"], "implied": ["a cloud data warehouse with separate compute for analysts", "columnar warehouse queries over billions of rows"]},
    "looker": {"names": ["Looker", "Looker Studio"], "implied": ["a semantic modelling layer so every team used the same metric definitions"]},
    "ab_testing": {"names": ["A/B testing", "experimentation"], "implied": ["designed controlled experiments with power analysis", "measured lift from a pricing change against a holdout"]},
    "statistics": {"names": ["statistics", "regression analysis"], "implied": ["hypothesis tests and confidence intervals for the survey", "modelled drivers of retention with regression"]},
    "google_analytics": {"names": ["Google Analytics", "GA4"], "implied": ["tracked funnel events from landing page to checkout", "web analytics tagging and conversion goals"]},
    "etl": {"names": ["ETL", "data pipeline"], "implied": ["moved data from five SaaS tools into one warehouse every night", "extracted, cleaned and loaded the CRM exports"]},
}

PERSONA_SKILLS: dict[str, list[str]] = {
    "ai_ml": ["python", "pytorch", "transformers", "llm_apps", "langchain", "langgraph", "rag", "vector_db",
              "computer_vision", "nlp", "fine_tuning", "mlops", "sklearn", "forecasting", "fastapi", "docker",
              "aws", "celery", "airflow", "postgres"],
    "fullstack": ["react", "nextjs", "typescript", "nodejs", "django", "postgres", "mongodb", "graphql",
                  "stripe", "tailwind", "websockets", "react_native", "redis", "docker", "aws", "celery",
                  "python", "fastapi", "wordpress"],
    "data_analyst": ["sql", "python", "pandas", "powerbi", "tableau", "excel", "dbt", "snowflake", "looker",
                     "ab_testing", "statistics", "google_analytics", "etl", "airflow", "postgres", "forecasting",
                     "sklearn"],
}

# Skills a persona does NOT have; used to build off-domain or partial-fit jobs.
FOREIGN_SKILLS = ["shopify", "wordpress", "react_native", "stripe", "computer_vision", "fine_tuning",
                  "tableau", "dbt", "graphql", "django", "mongodb", "powerbi", "looker"]

CATEGORIES: dict[str, list[str]] = {
    "AI & Machine Learning": ["llm_apps", "rag", "langchain", "langgraph", "vector_db", "pytorch", "transformers",
                              "nlp", "computer_vision", "fine_tuning", "mlops", "sklearn", "forecasting", "fastapi"],
    "Web Development": ["react", "nextjs", "typescript", "nodejs", "django", "postgres", "mongodb", "graphql",
                        "stripe", "tailwind", "websockets", "redis", "fastapi", "docker"],
    "Mobile Development": ["react_native", "typescript", "nodejs", "stripe"],
    "E-commerce": ["shopify", "wordpress", "stripe", "react"],
    "Data Analytics": ["sql", "pandas", "powerbi", "tableau", "excel", "dbt", "snowflake", "looker", "ab_testing",
                       "statistics", "google_analytics", "etl"],
    "Data Engineering": ["airflow", "etl", "dbt", "snowflake", "sql", "python", "celery", "aws", "docker"],
}

INDUSTRIES = ["healthcare", "fintech", "e-commerce", "logistics", "real estate", "education", "SaaS",
              "manufacturing", "legal", "marketing agency", "travel", "non-profit", "media", "retail"]
