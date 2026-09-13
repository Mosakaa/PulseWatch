import os

# Keep API tests independent from the local development database and Alembic state.
os.environ["DATABASE_URL"] = "sqlite://"
