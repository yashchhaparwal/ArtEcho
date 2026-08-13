from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# SQLAlchemy's defaults (pool_size=5, max_overflow=10) were fine when every
# request was fast, but the AI endpoints used to hold a connection open for the
# whole of a ~45s image generation or a multi-minute critique. A couple of those
# in flight starved the pool and made *every* page in the app crawl.
#
# Those calls now run on job threads that hold no connection while they wait
# (see app/services/jobs.py). The wider pool is belt-and-braces for the short
# transactions the workers still need at the end, plus the client polling that
# runs alongside them.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # Don't queue behind a leaked connection forever — fail loudly instead.
    pool_timeout=30,
    # Postgres drops idle connections; recycling below that avoids handing out
    # a stale one on the first request after a quiet spell.
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
